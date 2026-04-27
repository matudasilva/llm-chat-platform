from __future__ import annotations

import uuid
from typing import Any, Dict, Tuple, Type

import pytest

import app.api.routes.chat as chat_routes
from app.core.domain.chat_service import ChatService
from app.core.domain.disabled_provider import DisabledProvider
from app.core.providers.stub_provider import StubProvider
from app.models.conversation import Conversation
from app.schemas.chat import ChatRequest


class _BeginTx:
    def __init__(self, session: "FakeAsyncSession") -> None:
        self._session = session

    async def __aenter__(self) -> "FakeAsyncSession":
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeAsyncSession:
    """
    Minimal AsyncSession-like fake to execute /chat endpoint without a real DB.
    Only implements what chat.py uses.
    """

    def __init__(self) -> None:
        self._store: Dict[Tuple[Type[Any], uuid.UUID], Any] = {}

    def begin(self) -> _BeginTx:
        return _BeginTx(self)

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        if isinstance(obj, Conversation):
            self._store[(Conversation, obj.id)] = obj

    async def get(self, model: Type[Any], pk: uuid.UUID) -> Any:
        return self._store.get((model, pk))

    async def rollback(self) -> None:
        return None


class NoopCache:
    async def get(self, *, request_id, message):
        return None

    async def set(self, *, message, result) -> None:
        return None

    def log_bypass(self, *, reason: str) -> None:
        return None


@pytest.mark.asyncio
async def test_chat_telemetry_failure_does_not_break_chat(monkeypatch) -> None:
    """
    Telemetry (UsageEvent) is best-effort.
    If telemetry fails, /chat must still succeed.
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("telemetry down")

    monkeypatch.setattr(chat_routes, "UsageEvent", _boom, raising=True)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: NoopCache(), raising=True)

    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        db=FakeAsyncSession(),
        chat_service=ChatService(StubProvider(simulated_latency_ms=0, mode="ok"), timeout_s=1.0),
    )

    assert response.status == chat_routes.ChatStatus.success
    assert response.request_id is not None
    assert response.conversation_id is not None
    assert response.assistant_content is not None


@pytest.mark.asyncio
async def test_chat_error_telemetry_uses_active_provider(monkeypatch) -> None:
    """
    When /chat fails, the error UsageEvent should reflect the configured provider.
    """

    captured: dict[str, Any] = {}

    def _capture_usage_event(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(chat_routes, "UsageEvent", _capture_usage_event, raising=True)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: NoopCache(), raising=True)

    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        db=FakeAsyncSession(),
        chat_service=ChatService(
            DisabledProvider("openai", "OPENAI_API_KEY missing"),
            timeout_s=1.0,
        ),
    )

    assert response.status == chat_routes.ChatStatus.error
    assert response.error_message
    assert captured["provider"] == "openai"
    assert captured["provider"] != "stub"
