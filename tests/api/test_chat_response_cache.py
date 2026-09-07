from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.responses import StreamingResponse

import app.api.routes.chat as chat_routes
from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.provider import ProviderResult
from app.core.domain.types import ChatMessage
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.chat import ChatRequest
from app.services import chat_response_cache as cache_module
from app.services.chat_response_cache import ChatResponseCache


class _BeginTx:
    def __init__(self, session: "FakeAsyncSession") -> None:
        self._session = session

    async def __aenter__(self) -> "FakeAsyncSession":
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeAsyncSession:
    def __init__(self) -> None:
        self._store: dict[tuple[type[Any], uuid.UUID], Any] = {}
        self.messages: list[Message] = []

    def begin(self) -> _BeginTx:
        return _BeginTx(self)

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        if isinstance(obj, Conversation):
            self._store[(Conversation, obj.id)] = obj
        if isinstance(obj, Message):
            self.messages.append(obj)

    async def get(self, model: type[Any], pk: uuid.UUID) -> Any:
        return self._store.get((model, pk))

    async def rollback(self) -> None:
        return None


@dataclass
class FakeRedisClient:
    get_error: Exception | None = None
    set_error: Exception | None = None

    async def get(self, key: str) -> str | None:
        if self.get_error is not None:
            raise self.get_error
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if self.set_error is not None:
            raise self.set_error
        return True


@dataclass
class FakeCache:
    hit_result: ChatServiceResult | None = None
    read_error: Exception | None = None
    write_error: Exception | None = None
    reads: int = 0
    writes: int = 0
    bypasses: list[str] = field(default_factory=list)

    async def get(self, *, request_id: uuid.UUID, messages: list, tenant_id: str) -> ChatServiceResult | None:
        self.reads += 1
        if self.read_error is not None:
            raise self.read_error
        if self.hit_result is None:
            return None
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=self.hit_result.assistant_message,
            provider_result=self.hit_result.provider_result,
        )

    async def set(self, *, messages: list, result: ChatServiceResult, tenant_id: str) -> None:
        self.writes += 1
        if self.write_error is not None:
            raise self.write_error

    def log_bypass(self, *, reason: str) -> None:
        self.bypasses.append(reason)


@dataclass
class FakeChatService:
    content: str = "hello from provider"
    run_calls: int = 0
    stream_calls: int = 0

    async def run(self, *, request_id: uuid.UUID, messages: list[ChatMessage]) -> ChatServiceResult:
        self.run_calls += 1
        return _chat_service_result(request_id=request_id, content=self.content)

    async def stream_chat(self, *, request_id: uuid.UUID, messages: list[ChatMessage]):
        self.stream_calls += 1

        async def _chunks() -> AsyncIterator[str]:
            yield "stream"

        async def _final_result():
            from app.core.domain.chat_service import StreamChatResult

            return StreamChatResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content="stream"),
                provider_result=None,
            )

        from app.core.domain.chat_service import ChatServiceStreamSession

        return ChatServiceStreamSession(chunks=_chunks(), get_final_result=_final_result)


class ExplodingChatService(FakeChatService):
    async def run(self, *, request_id: uuid.UUID, messages: list[ChatMessage]) -> ChatServiceResult:
        raise AssertionError("chat service run must not be called on cache hit")


def _chat_service_result(*, request_id: uuid.UUID, content: str) -> ChatServiceResult:
    return ChatServiceResult(
        request_id=request_id,
        assistant_message=ChatMessage(role="assistant", content=content),
        provider_result=ProviderResult(
            content=content,
            provider="stub",
            model_version="stub-model",
            prompt_version="v1",
            input_tokens=1,
            output_tokens=2,
            total_tokens=3,
            latency_ms=5,
        ),
    )


async def _collect_sse_events(response: StreamingResponse) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    parts: list[str] = []

    async for chunk in response.body_iterator:
        parts.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))

    current_event: str | None = None
    for line in "".join(parts).splitlines():
        if not line:
            continue
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ").strip()
            continue
        if line.startswith("data: ") and current_event is not None:
            raw = line.removeprefix("data: ").strip()
            if current_event == "token":
                events.append((current_event, raw))
            else:
                events.append((current_event, json.loads(raw)))

    return events


@pytest.mark.asyncio
async def test_chat_non_streaming_cache_miss_runs_service_and_writes_cache(monkeypatch) -> None:
    cache = FakeCache()
    chat_service = FakeChatService(content="miss response")
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache, raising=True)

    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        db=FakeAsyncSession(),
        chat_service=chat_service,
    )

    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "miss response"
    assert chat_service.run_calls == 1
    assert cache.reads == 1
    assert cache.writes == 1


@pytest.mark.asyncio
async def test_chat_non_streaming_cache_hit_skips_service_and_preserves_write_path(monkeypatch) -> None:
    request_id = uuid.uuid4()
    cache = FakeCache(hit_result=_chat_service_result(request_id=request_id, content="cached response"))
    db = FakeAsyncSession()
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache, raising=True)

    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        db=db,
        chat_service=ExplodingChatService(),
    )

    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "cached response"
    assert cache.reads == 1
    assert cache.writes == 0
    assert len(db.messages) == 2


@pytest.mark.asyncio
async def test_chat_streaming_bypasses_cache(monkeypatch) -> None:
    cache = FakeCache()
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache, raising=True)

    response = await chat_routes.chat(
        ChatRequest(message="hello", stream=True),
        db=FakeAsyncSession(),
        chat_service=FakeChatService(),
    )
    events = await _collect_sse_events(response)

    assert [event for event, _ in events] == ["token", "done"]
    assert cache.reads == 0
    assert cache.writes == 0
    assert cache.bypasses == ["streaming"]


@pytest.mark.asyncio
async def test_chat_cache_read_failure_is_non_fatal(monkeypatch) -> None:
    chat_service = FakeChatService(content="read fallback")
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: ChatResponseCache(), raising=True)
    monkeypatch.setattr(
        cache_module,
        "redis_client",
        FakeRedisClient(get_error=RuntimeError("redis down")),
        raising=True,
    )

    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        db=FakeAsyncSession(),
        chat_service=chat_service,
    )

    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "read fallback"
    assert chat_service.run_calls == 1


@pytest.mark.asyncio
async def test_chat_cache_write_failure_is_non_fatal(monkeypatch) -> None:
    chat_service = FakeChatService(content="write fallback")
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: ChatResponseCache(), raising=True)
    monkeypatch.setattr(
        cache_module,
        "redis_client",
        FakeRedisClient(set_error=RuntimeError("redis write down")),
        raising=True,
    )

    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        db=FakeAsyncSession(),
        chat_service=chat_service,
    )

    assert response.status == chat_routes.ChatStatus.success
    assert response.assistant_content == "write fallback"
    assert chat_service.run_calls == 1


# --- ORQ-37 T11 (Gate B1 half): AC17 clause 1 -- the window is in the key --
#
# Uses the REAL `ChatResponseCache`, not `FakeCache`: the property under test
# is `_cache_key`'s actual behaviour, and a double would only prove that the
# double behaves as written. `FakeRedisClient` above returns `None`
# unconditionally, so it cannot show non-reuse; this uses a tiny dict-backed
# stand-in instead, keyed exactly as Redis would be.
#
# Clause 2 (bypassing the cache when `ebm25_enabled` is on) is NOT attempted
# here. `settings.py` has no `ebm25_enabled` field -- it is introduced by
# T18 -- so there is nothing to gate on yet. See the note in
# `implementation.md` recording the deferral.


@dataclass
class _DictRedis:
    """Minimal stand-in with real key-based storage, unlike `FakeRedisClient`."""

    store: dict[str, str] = field(default_factory=dict)

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True


def _memory_context(*pairs: tuple[str, str]):
    from app.core.domain.chat_memory import ChatMemoryContext
    from app.core.domain.types import ChatMessage as _CM

    return ChatMemoryContext(
        messages=tuple(_CM(role=role, content=content) for role, content in pairs)
    )


@pytest.mark.asyncio
async def test_cache_key_differs_when_only_the_memory_window_differs(monkeypatch) -> None:
    """`_cache_key` directly: same tenant, same current message, different windows."""
    monkeypatch.setattr(cache_module, "redis_client", _DictRedis())
    cache = ChatResponseCache()

    current = ChatMessage(role="user", content="what did we decide?")
    messages_a = [
        ChatMessage(role="user", content="topic is X"),
        ChatMessage(role="assistant", content="noted, X"),
        current,
    ]
    messages_b = [
        ChatMessage(role="user", content="topic is Y"),
        ChatMessage(role="assistant", content="noted, Y"),
        current,
    ]

    key_a = cache._cache_key(messages=messages_a, tenant_id="acme")
    key_b = cache._cache_key(messages=messages_b, tenant_id="acme")

    assert key_a != key_b, "identical latest message must not collide across windows"


@pytest.mark.asyncio
async def test_end_to_end_no_reuse_across_differing_windows(monkeypatch) -> None:
    """The read AND write gates (`chat.py:302-305`, `:373-374`), not `_cache_key` alone.

    Two real requests through `chat_routes.chat`, same current message, memory
    windows that differ only in their out-of-window content. The second must
    not reuse the first response -- the failure this would catch is `_messages`
    someday being built from only the current message, silently restoring the
    pre-T9 collision.
    """
    monkeypatch.setattr(cache_module, "redis_client", _DictRedis())
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache_module._cache)
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", False)
    # Without this the route's fail-closed reset (chat.py:79-82, mirrored for
    # memory) empties BOTH windows to `ChatMemoryContext()` before the cache
    # ever sees them, which would make the two requests collide for a reason
    # that has nothing to do with `_cache_key` -- the very failure this test
    # exists to catch, reached by a different door.
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", True)

    request = ChatRequest(message="what did we decide?")

    service_a = FakeChatService(content="response for window A")
    response_a = await chat_routes.chat(
        request,
        db=FakeAsyncSession(),
        chat_service=service_a,
        memory_context=_memory_context(("user", "topic is X"), ("assistant", "noted, X")),
    )
    assert response_a.assistant_content == "response for window A"
    assert service_a.run_calls == 1

    service_b = FakeChatService(content="response for window B")
    response_b = await chat_routes.chat(
        request,
        db=FakeAsyncSession(),
        chat_service=service_b,
        memory_context=_memory_context(("user", "topic is Y"), ("assistant", "noted, Y")),
    )

    # Not reused: the service ran again and the (different) result came back.
    assert service_b.run_calls == 1, "a cache hit would have skipped the provider call"
    assert response_b.assistant_content == "response for window B"


@pytest.mark.asyncio
async def test_end_to_end_reuse_when_the_window_is_identical(monkeypatch) -> None:
    """Control for the previous test: it must be ABLE to hit, or non-reuse proves nothing."""
    monkeypatch.setattr(cache_module, "redis_client", _DictRedis())
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache_module._cache)
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", False)
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", True)

    request = ChatRequest(message="what did we decide?")
    window = _memory_context(("user", "topic is X"), ("assistant", "noted, X"))

    service_a = FakeChatService(content="first answer")
    await chat_routes.chat(
        request, db=FakeAsyncSession(), chat_service=service_a, memory_context=window
    )

    service_b = ExplodingChatService()
    response_b = await chat_routes.chat(
        request, db=FakeAsyncSession(), chat_service=service_b, memory_context=window
    )

    assert response_b.assistant_content == "first answer"
