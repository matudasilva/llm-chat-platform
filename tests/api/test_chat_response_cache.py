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
