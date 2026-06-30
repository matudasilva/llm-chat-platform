from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import pytest
from fastapi import HTTPException

import app.api.routes.chat as chat_routes
from app.core.domain.chat_service import ChatServiceStreamSession, StreamChatResult
from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.provider import ProviderResult
from app.core.domain.types import ChatMessage
from app.http.middleware.tenant import _tenant_id_ctx
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.chat import ChatRequest
from app.services.chat_response_cache import ChatResponseCache


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _BeginTx:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    async def __aenter__(self) -> "FakeSession":
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeSession:
    def __init__(self) -> None:
        self._store: dict[tuple[type[Any], uuid.UUID], Any] = {}
        self.conversations: list[Conversation] = []
        self.messages: list[Message] = []

    def begin(self) -> _BeginTx:
        return _BeginTx(self)

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        if isinstance(obj, Conversation):
            self._store[(Conversation, obj.id)] = obj
            self.conversations.append(obj)
        elif isinstance(obj, Message):
            self.messages.append(obj)

    async def get(self, model: type[Any], pk: uuid.UUID) -> Any:
        return self._store.get((model, pk))

    async def rollback(self) -> None:
        return None


@dataclass
class FakeCache:
    reads: int = 0
    writes: int = 0
    bypasses: list[str] = field(default_factory=list)

    async def get(self, *, request_id: uuid.UUID, messages: list, tenant_id: str) -> ChatServiceResult | None:
        self.reads += 1
        return None

    async def set(self, *, messages: list, result: ChatServiceResult, tenant_id: str) -> None:
        self.writes += 1

    def log_bypass(self, *, reason: str) -> None:
        self.bypasses.append(reason)


@dataclass
class FakeChatService:
    content: str = "response"
    run_calls: int = 0
    stream_calls: int = 0

    async def run(self, *, request_id: uuid.UUID, messages: list[ChatMessage]) -> ChatServiceResult:
        self.run_calls += 1
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=ChatMessage(role="assistant", content=self.content),
            provider_result=ProviderResult(
                content=self.content,
                provider="stub",
                model_version="stub-model",
                prompt_version="v1",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                latency_ms=5,
            ),
        )

    async def stream_chat(self, *, request_id: uuid.UUID, messages: list[ChatMessage]) -> ChatServiceStreamSession:
        self.stream_calls += 1

        async def _chunks() -> AsyncIterator[str]:
            yield self.content

        async def _final():
            return StreamChatResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content=self.content),
                provider_result=None,
            )

        return ChatServiceStreamSession(chunks=_chunks(), get_final_result=_final)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_tenant(tenant_id: str):
    return _tenant_id_ctx.set(tenant_id)


# ---------------------------------------------------------------------------
# Tests: persistence propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conversation_created_with_correct_tenant_id(monkeypatch) -> None:
    cache = FakeCache()
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache)
    db = FakeSession()

    token = _set_tenant("acme")
    try:
        response = await chat_routes.chat(
            ChatRequest(message="hello"),
            db=db,
            chat_service=FakeChatService(),
        )
    finally:
        _tenant_id_ctx.reset(token)

    assert response.status == chat_routes.ChatStatus.success
    assert len(db.conversations) == 1
    assert db.conversations[0].tenant_id == "acme"


@pytest.mark.asyncio
async def test_messages_created_with_correct_tenant_id(monkeypatch) -> None:
    cache = FakeCache()
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache)
    db = FakeSession()

    token = _set_tenant("beta-corp")
    try:
        await chat_routes.chat(
            ChatRequest(message="hello"),
            db=db,
            chat_service=FakeChatService(),
        )
    finally:
        _tenant_id_ctx.reset(token)

    # user message + assistant message
    assert len(db.messages) == 2
    assert all(m.tenant_id == "beta-corp" for m in db.messages)


@pytest.mark.asyncio
async def test_cross_tenant_lookup_returns_404(monkeypatch) -> None:
    cache = FakeCache()
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache)

    existing_conv_id = uuid.uuid4()
    db = FakeSession()
    db._store[(Conversation, existing_conv_id)] = Conversation(
        id=existing_conv_id, tenant_id="tenant-a"
    )

    token = _set_tenant("tenant-b")
    try:
        with pytest.raises(HTTPException) as exc_info:
            await chat_routes.chat(
                ChatRequest(message="hello", conversation_id=existing_conv_id),
                db=db,
                chat_service=FakeChatService(),
            )
    finally:
        _tenant_id_ctx.reset(token)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_same_tenant_lookup_succeeds(monkeypatch) -> None:
    cache = FakeCache()
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache)

    existing_conv_id = uuid.uuid4()
    db = FakeSession()
    db._store[(Conversation, existing_conv_id)] = Conversation(
        id=existing_conv_id, tenant_id="tenant-a"
    )

    token = _set_tenant("tenant-a")
    try:
        response = await chat_routes.chat(
            ChatRequest(message="hello", conversation_id=existing_conv_id),
            db=db,
            chat_service=FakeChatService(),
        )
    finally:
        _tenant_id_ctx.reset(token)

    assert response.status == chat_routes.ChatStatus.success


# ---------------------------------------------------------------------------
# Tests: cache isolation
# ---------------------------------------------------------------------------

def test_cache_key_differs_for_different_tenants() -> None:
    cache = ChatResponseCache()
    msgs = [ChatMessage(role="user", content="hello")]
    key_a = cache._cache_key(messages=msgs, tenant_id="tenant-a")
    key_b = cache._cache_key(messages=msgs, tenant_id="tenant-b")
    assert key_a != key_b
    assert key_a.startswith("chat:response:tenant-a:")
    assert key_b.startswith("chat:response:tenant-b:")


def test_cache_key_same_for_same_tenant_and_messages() -> None:
    cache = ChatResponseCache()
    msgs = [ChatMessage(role="user", content="hello")]
    key1 = cache._cache_key(messages=msgs, tenant_id="acme")
    key2 = cache._cache_key(messages=msgs, tenant_id="acme")
    assert key1 == key2


def test_fingerprint_changes_with_message_history() -> None:
    cache = ChatResponseCache()
    msgs_short = [ChatMessage(role="user", content="hello")]
    msgs_long = [
        ChatMessage(role="user", content="first message"),
        ChatMessage(role="assistant", content="first response"),
        ChatMessage(role="user", content="hello"),
    ]
    key_short = cache._cache_key(messages=msgs_short, tenant_id="acme")
    key_long = cache._cache_key(messages=msgs_long, tenant_id="acme")
    assert key_short != key_long
