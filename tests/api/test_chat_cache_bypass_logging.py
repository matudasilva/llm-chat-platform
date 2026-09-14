"""TQ-1 — `ChatResponseCache.log_bypass()` must not be able to break `/chat`.

Every other Redis interaction in `ChatResponseCache` is already wrapped in a
best-effort boundary. `log_bypass` was not, and it is called from two places
that cannot tolerate an exception: once immediately before the streaming
response is constructed, and once *inside* the single `/chat` write
transaction, between the user message's flush and the assistant message's.
A raise at the second site aborts the transaction and loses the user turn.

The hostile injection here is a `logging.Filter` that raises. That is a real
propagation path, unlike a raising *handler*: `Handler.emit` routes its own
failures through `handleError`, but `Logger.filter` is called by
`Logger.handle` outside any try/except, so whatever it raises reaches the
caller. `_HostileFilter` counts its own invocations and every test asserts it
actually fired, because `logger.info` short-circuits on `isEnabledFor` before
filters run -- a hostile-logging test against a logger left at WARNING passes
while proving nothing.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

import app.api.routes.chat as chat_routes
from app.core.settings import settings
from app.schemas.chat import ChatRequest
from app.services import chat_response_cache as cache_module
from app.services.chat_response_cache import ChatResponseCache

from tests.api.test_chat_response_cache import (
    FakeAsyncSession,
    FakeChatService,
    _collect_sse_events,
)

BYPASS_LOGGER = "app.services.chat_response_cache"


class _HostileFilter(logging.Filter):
    """A logging filter that raises, and records that it was reached."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self._error = error
        self.calls = 0

    def filter(self, record: logging.LogRecord) -> bool:
        self.calls += 1
        raise self._error


@pytest.fixture
def hostile_logging():
    """Install a raising filter on the cache logger, INFO-enabled.

    Returns the filter so each test can assert it was actually reached. The
    teardown is explicit rather than `monkeypatch`-managed: `monkeypatch`
    restores the *same* `filters` list object that `addFilter` mutated, which
    silently leaks the hostile filter into later tests in this file.

    `setLevel` rather than assigning `.level`, because `isEnabledFor` consults
    a per-logger cache that only `setLevel` invalidates.
    """
    installed: list[_HostileFilter] = []
    original_level = cache_module.logger.level

    def _install(error: BaseException | None = None) -> _HostileFilter:
        hostile = _HostileFilter(error or RuntimeError("hostile logging filter"))
        cache_module.logger.setLevel(logging.INFO)
        cache_module.logger.addFilter(hostile)
        installed.append(hostile)
        return hostile

    yield _install

    for hostile in installed:
        cache_module.logger.removeFilter(hostile)
    cache_module.logger.setLevel(original_level)


def _use_real_cache(monkeypatch) -> ChatResponseCache:
    cache = ChatResponseCache()
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache, raising=True)
    return cache


# --- 1. the non-streaming request survives -----------------------------------


@pytest.mark.asyncio
async def test_hostile_bypass_logging_does_not_break_the_non_streaming_request(
    monkeypatch, hostile_logging
) -> None:
    hostile = hostile_logging()
    _use_real_cache(monkeypatch)
    monkeypatch.setattr(settings, "chat_rag_augmentation_enabled", True, raising=False)
    chat_service = FakeChatService(content="survived")

    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        db=FakeAsyncSession(),
        chat_service=chat_service,
    )

    assert hostile.calls >= 1, "hostile filter never ran; the test proves nothing"
    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "survived"
    assert chat_service.run_calls == 1


# --- 2. the streaming response and its frames survive ------------------------


@pytest.mark.asyncio
async def test_hostile_bypass_logging_does_not_prevent_the_streaming_frames(
    monkeypatch, hostile_logging
) -> None:
    hostile = hostile_logging()
    _use_real_cache(monkeypatch)
    monkeypatch.setattr(settings, "chat_rag_augmentation_enabled", False, raising=False)

    response = await chat_routes.chat(
        ChatRequest(message="hello", stream=True),
        db=FakeAsyncSession(),
        chat_service=FakeChatService(),
    )
    events = await _collect_sse_events(response)

    assert hostile.calls >= 1, "hostile filter never ran; the test proves nothing"
    assert [event for event, _ in events] == ["token", "done"]


# --- 3. the transaction is not aborted at the second call site ---------------


@pytest.mark.asyncio
async def test_hostile_bypass_logging_keeps_chat_persistence_atomic(
    monkeypatch, hostile_logging
) -> None:
    """The second call site sits between the user flush and the assistant
    flush. An escaping exception there would abort `db.begin()` with the user
    turn already flushed, so both messages must still be persisted."""
    hostile = hostile_logging()
    _use_real_cache(monkeypatch)
    monkeypatch.setattr(settings, "chat_rag_augmentation_enabled", True, raising=False)
    db = FakeAsyncSession()

    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        db=db,
        chat_service=FakeChatService(content="atomic"),
    )

    assert hostile.calls >= 1, "hostile filter never ran; the test proves nothing"
    assert response.status == chat_routes.ChatStatus.success
    assert [m.role.value for m in db.messages] == ["user", "assistant"]


# --- 4. normal logging behavior and `reason` are preserved -------------------


def test_normal_bypass_logging_still_emits_the_event_and_reason(caplog) -> None:
    caplog.set_level(logging.INFO, logger=BYPASS_LOGGER)

    ChatResponseCache().log_bypass(reason="rag_augmentation")

    records = [r for r in caplog.records if r.name == BYPASS_LOGGER]
    assert len(records) == 1
    assert records[0].message == "chat_cache_bypass"
    assert records[0].event == "chat.cache.bypass"
    assert records[0].reason == "rag_augmentation"


# --- 5. the boundary is Exception, not BaseException -------------------------


def test_cancellation_is_not_swallowed_by_the_bypass_guard(hostile_logging) -> None:
    """`CancelledError` derives from `BaseException`. Widening the guard to
    `BaseException` would make a cancelled request look like it completed."""
    hostile = hostile_logging(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        ChatResponseCache().log_bypass(reason="streaming")

    assert hostile.calls == 1
