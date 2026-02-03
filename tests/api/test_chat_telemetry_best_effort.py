from __future__ import annotations

import uuid
from typing import Any, AsyncIterator, Dict, Tuple, Type

from fastapi.testclient import TestClient

import app.api.routes.chat as chat_routes
from app.infra.db.session import get_db
from app.main import app
from app.models.conversation import Conversation


class _BeginTx:
    def __init__(self, session: "FakeAsyncSession") -> None:
        self._session = session

    async def __aenter__(self) -> "FakeAsyncSession":
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        # Do not suppress exceptions from the endpoint.
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
        # Persist only what the route needs for db.get(Conversation, id)
        if isinstance(obj, Conversation):
            self._store[(Conversation, obj.id)] = obj

    async def get(self, model: Type[Any], pk: uuid.UUID) -> Any:
        return self._store.get((model, pk))

    async def rollback(self) -> None:
        return None


async def _override_get_db() -> AsyncIterator[FakeAsyncSession]:
    yield FakeAsyncSession()


def test_chat_telemetry_failure_does_not_break_chat(monkeypatch) -> None:
    """
    Telemetry (UsageEvent) is best-effort.
    If telemetry fails, /chat must still succeed.
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("telemetry down")

    # Force UsageEvent constructor to fail
    monkeypatch.setattr(chat_routes, "UsageEvent", _boom, raising=True)

    # Override DB dependency to avoid real Postgres in this test.
    app.dependency_overrides[get_db] = _override_get_db

    try:
        client = TestClient(app)

        r = client.post(
            "/chat",
            json={"message": "hello"},
        )

        assert r.status_code == 200

        body = r.json()
        assert body["status"] == "success"
        assert body["request_id"] is not None
        assert body["conversation_id"] is not None
        assert body["assistant_content"] is not None

    finally:
        app.dependency_overrides.clear()
