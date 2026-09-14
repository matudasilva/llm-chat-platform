"""The five remaining logging calls in `ChatResponseCache.get()`/`set()`.

TQ-1 contained `log_bypass()`. These five were left as follow-up debt and are
the same defect class: logging treated as infallible on paths that cannot
tolerate a raise.

Where each one sits, and why the severity differs:

- The four `get()` calls run at `chat.py:286`, *inside* the `/chat` write
  transaction, after the user message's flush and before the assistant
  message's. An escaping exception aborts the transaction and loses the user
  turn. `chat_cache_miss` is the worst-exposed of the five: it is the normal
  path of every non-streaming request with a cold cache.
- The two `logger.warning` calls sit inside `except` blocks, so a raise there
  also replaces the original Redis/decode failure -- the graceful `return None`
  never happens.
- The `set()` call runs at `chat.py:356`, *after* the commit but still inside
  the route's outer `try`. Its generic handler (`chat.py:411`) returns a
  `ChatResponse` with `status=error` and both message ids `None` -- while the
  rows are already durable. The client is told nothing persisted when in fact
  everything did, which invites a retry that duplicates the turn.

The hostile injection is a `logging.Filter` that raises, targeted at one event
at a time so `miss` and `hit` can be exercised independently. A raising filter
propagates; a raising *handler* would not (`Handler.emit` routes its own
failures through `handleError`). Every test asserts the filter actually ran,
because `logger.info` short-circuits on `isEnabledFor` before filters run and a
logger left at WARNING would make these tests pass while proving nothing.

Note the streaming path is untouched here: it never calls `get()` or `set()`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass

import pytest

import app.api.routes.chat as chat_routes
from app.core.settings import settings
from app.schemas.chat import ChatRequest
from app.services import chat_response_cache as cache_module
from app.services.chat_response_cache import ChatResponseCache

from tests.api.test_chat_response_cache import (
    FakeAsyncSession,
    FakeChatService,
    _chat_service_result,
)

CACHE_LOGGER = "app.services.chat_response_cache"


# --- hostile logging ---------------------------------------------------------


class _EventFilter(logging.Filter):
    """Raises only for one `event`, so each log call can be targeted alone."""

    def __init__(self, event: str, error: BaseException) -> None:
        super().__init__()
        self._event = event
        self._error = error
        self.calls = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "event", None) != self._event:
            return True
        self.calls += 1
        raise self._error


@pytest.fixture
def hostile_logging():
    """Install an event-targeted raising filter on the cache logger.

    Teardown is explicit rather than `monkeypatch`-managed: `monkeypatch`
    restores the same `filters` list object that `addFilter` mutated, which
    leaks the filter into later tests. `setLevel` rather than assigning
    `.level`, because `isEnabledFor` consults a cache only `setLevel` clears.
    """
    installed: list[_EventFilter] = []
    original_level = cache_module.logger.level

    def _install(event: str, error: BaseException | None = None) -> _EventFilter:
        hostile = _EventFilter(event, error or RuntimeError(f"hostile logging on {event}"))
        cache_module.logger.setLevel(logging.INFO)
        cache_module.logger.addFilter(hostile)
        installed.append(hostile)
        return hostile

    yield _install

    for hostile in installed:
        cache_module.logger.removeFilter(hostile)
    cache_module.logger.setLevel(original_level)


# --- redis doubles -----------------------------------------------------------


@dataclass
class _Redis:
    """Drives each `get()`/`set()` branch: miss, hit, decode failure, errors."""

    payload: str | None = None
    get_error: Exception | None = None
    set_error: Exception | None = None
    sets: int = 0

    async def get(self, key: str) -> str | None:
        if self.get_error is not None:
            raise self.get_error
        return self.payload

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.sets += 1
        if self.set_error is not None:
            raise self.set_error
        return True


def _cached_payload(content: str) -> str:
    return json.dumps(
        {
            "assistant_content": content,
            "provider_result": {
                "provider": "stub",
                "model_version": "stub-model",
                "prompt_version": "v1",
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
            },
        }
    )


def _arrange(monkeypatch, redis: _Redis) -> None:
    """Real cache + fake redis, with the cache read path actually reachable."""
    monkeypatch.setattr(
        chat_routes, "get_chat_response_cache", lambda: ChatResponseCache(), raising=True
    )
    monkeypatch.setattr(cache_module, "redis_client", redis, raising=True)
    # `cache.get()` only runs on the `else` branch of chat.py:283.
    monkeypatch.setattr(settings, "chat_rag_augmentation_enabled", False, raising=False)


async def _post(db: FakeAsyncSession, chat_service: FakeChatService):
    return await chat_routes.chat(
        ChatRequest(message="hello"), db=db, chat_service=chat_service
    )


# --- 1. hostile logging on cache miss ----------------------------------------


@pytest.mark.asyncio
async def test_hostile_logging_on_cache_miss_does_not_break_chat(
    monkeypatch, hostile_logging
) -> None:
    hostile = hostile_logging("chat.cache.miss")
    _arrange(monkeypatch, _Redis(payload=None))
    db = FakeAsyncSession()

    response = await _post(db, FakeChatService(content="miss survived"))

    assert hostile.calls >= 1, "hostile filter never ran; the test proves nothing"
    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "miss survived"
    assert [m.role.value for m in db.messages] == ["user", "assistant"]


# --- 2. hostile logging on cache hit, and the hit stays a hit ----------------


@pytest.mark.asyncio
async def test_hostile_logging_on_cache_hit_preserves_the_hit(
    monkeypatch, hostile_logging
) -> None:
    """The containment boundary must not turn a hit into a miss.

    This is what rules out wrapping the whole of `get()`: such a guard would
    have to `return None` when the hit log fails, silently re-running the
    provider for a request the cache had already answered.
    """
    hostile = hostile_logging("chat.cache.hit")
    _arrange(monkeypatch, _Redis(payload=_cached_payload("cached answer")))
    chat_service = FakeChatService(content="provider must not run")

    response = await _post(FakeAsyncSession(), chat_service)

    assert hostile.calls >= 1, "hostile filter never ran; the test proves nothing"
    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "cached answer"
    assert chat_service.run_calls == 0, "the cache hit was silently downgraded to a miss"


# --- 3. redis read failure + hostile logging ---------------------------------


@pytest.mark.asyncio
async def test_hostile_logging_while_handling_a_redis_read_failure_stays_best_effort(
    monkeypatch, hostile_logging
) -> None:
    """This log call lives inside an `except`. A raise there does not merely
    escape -- it replaces the handling of the Redis failure, so the documented
    degrade-to-miss never happens."""
    hostile = hostile_logging("chat.cache.error")
    _arrange(monkeypatch, _Redis(get_error=RuntimeError("redis down")))
    chat_service = FakeChatService(content="degraded to provider")
    db = FakeAsyncSession()

    response = await _post(db, chat_service)

    assert hostile.calls >= 1, "hostile filter never ran; the test proves nothing"
    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "degraded to provider"
    assert chat_service.run_calls == 1, "the Redis failure did not degrade to a miss"
    assert [m.role.value for m in db.messages] == ["user", "assistant"]


# --- 4. decode failure + hostile logging -------------------------------------


@pytest.mark.asyncio
async def test_hostile_logging_while_handling_a_decode_failure_does_not_break_chat(
    monkeypatch, hostile_logging
) -> None:
    hostile = hostile_logging("chat.cache.error")
    _arrange(monkeypatch, _Redis(payload="{not valid json"))
    chat_service = FakeChatService(content="decoded fallback")
    db = FakeAsyncSession()

    response = await _post(db, chat_service)

    assert hostile.calls >= 1, "hostile filter never ran; the test proves nothing"
    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "decoded fallback"
    assert chat_service.run_calls == 1
    assert [m.role.value for m in db.messages] == ["user", "assistant"]


# --- 5. cache write failure + hostile logging --------------------------------


@pytest.mark.asyncio
async def test_hostile_logging_during_a_cache_write_failure_stays_best_effort(
    monkeypatch, hostile_logging
) -> None:
    """`cache.set()` runs after the commit but inside the route's outer `try`.
    An escape is caught by the generic handler, which answers `status=error`
    with both message ids `None` -- for a request whose rows are already
    durable. The response must keep reporting what actually happened."""
    hostile = hostile_logging("chat.cache.error")
    redis = _Redis(payload=None, set_error=RuntimeError("redis write down"))
    _arrange(monkeypatch, redis)
    db = FakeAsyncSession()

    response = await _post(db, FakeChatService(content="written anyway"))

    assert redis.sets == 1, "the cache write path was never reached"
    assert hostile.calls >= 1, "hostile filter never ran; the test proves nothing"
    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "written anyway"
    assert response.user_message_id is not None
    assert response.assistant_message_id is not None
    assert [m.role.value for m in db.messages] == ["user", "assistant"]


# --- 6. normal logging, including the real call site -------------------------


@pytest.mark.asyncio
async def test_normal_cache_logging_is_preserved_with_the_real_call_site(
    monkeypatch, caplog
) -> None:
    """Routing the calls through a helper must not move the reported origin.

    Without `stacklevel=2` every record would report the helper's own
    `funcName`/`lineno`, silently destroying call-site attribution in logs.
    """
    caplog.set_level(logging.INFO, logger=CACHE_LOGGER)
    monkeypatch.setattr(cache_module, "redis_client", _Redis(payload=None), raising=True)

    cache = ChatResponseCache()
    result = await cache.get(request_id=uuid.uuid4(), messages=[], tenant_id="acme")

    assert result is None
    records = [r for r in caplog.records if r.name == CACHE_LOGGER]
    assert len(records) == 1
    record = records[0]
    assert record.message == "chat_cache_miss"
    assert record.event == "chat.cache.miss"
    assert record.tenant_id == "acme"
    assert record.funcName == "get", f"call site lost: reported {record.funcName}"


@pytest.mark.asyncio
async def test_normal_cache_error_logging_keeps_operation_and_traceback(
    monkeypatch, caplog
) -> None:
    caplog.set_level(logging.INFO, logger=CACHE_LOGGER)
    monkeypatch.setattr(
        cache_module, "redis_client", _Redis(get_error=RuntimeError("redis down")), raising=True
    )

    cache = ChatResponseCache()
    result = await cache.get(request_id=uuid.uuid4(), messages=[], tenant_id="acme")

    assert result is None
    record = next(r for r in caplog.records if r.name == CACHE_LOGGER)
    assert record.levelno == logging.WARNING
    assert record.event == "chat.cache.error"
    assert record.operation == "read"
    # Not `is not None`: a record logged with `exc_info=False` stores literal
    # `False`, which passes that check while carrying no traceback at all.
    assert record.exc_info, "exc_info=True was dropped"
    assert record.exc_info[0] is RuntimeError
    assert str(record.exc_info[1]) == "redis down"
    assert record.funcName == "get", f"call site lost: reported {record.funcName}"


# --- 7. cancellation is not swallowed ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event,redis",
    [
        ("chat.cache.miss", _Redis(payload=None)),
        ("chat.cache.hit", _Redis(payload=_cached_payload("cached"))),
        ("chat.cache.error", _Redis(get_error=RuntimeError("redis down"))),
        ("chat.cache.error", _Redis(payload="{not valid json")),
    ],
)
async def test_cancellation_is_not_swallowed_by_the_get_guard(
    monkeypatch, hostile_logging, event, redis
) -> None:
    """`CancelledError` derives from `BaseException`. Widening the boundary
    would make a cancelled request look like a cache miss."""
    hostile = hostile_logging(event, asyncio.CancelledError())
    monkeypatch.setattr(cache_module, "redis_client", redis, raising=True)

    with pytest.raises(asyncio.CancelledError):
        await ChatResponseCache().get(request_id=uuid.uuid4(), messages=[], tenant_id="acme")

    assert hostile.calls == 1


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed_by_the_set_guard(
    monkeypatch, hostile_logging
) -> None:
    hostile = hostile_logging("chat.cache.error", asyncio.CancelledError())
    monkeypatch.setattr(
        cache_module,
        "redis_client",
        _Redis(set_error=RuntimeError("redis write down")),
        raising=True,
    )

    with pytest.raises(asyncio.CancelledError):
        await ChatResponseCache().set(
            messages=[],
            result=_chat_service_result(request_id=uuid.uuid4(), content="x"),
            tenant_id="acme",
        )

    assert hostile.calls == 1
