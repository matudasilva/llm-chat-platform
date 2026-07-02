# tests/conftest.py
from __future__ import annotations

import os
from contextlib import AbstractAsyncContextManager
from typing import Any

# Test configuration must be set before importing app modules. An empty
# APP_SETTINGS_ENV_FILE disables the developer's .env completely.
os.environ.update(
    {
        "APP_ENV": "test",
        "APP_SETTINGS_ENV_FILE": "",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "PRIMARY_PROVIDER": "stub",
        "STUB_PROVIDER_MODE": "ok",
        "NOTION_MCP_ENABLED": "false",
        "NOTION_READ_ENABLED": "false",
        "NOTION_WRITE_ENABLED": "false",
        "WEB_READ_ENABLED": "false",
    }
)

import httpx
import pytest
import uvloop
from httpx import ASGITransport
from asgi_lifespan import LifespanManager

from app.infra.db.session import get_db
from app.main import app
from app.services import chat_response_cache


class _Transaction(AbstractAsyncContextManager):
    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _TestSession:
    def __init__(self) -> None:
        self.objects: list[Any] = []

    def begin(self) -> _Transaction:
        return _Transaction()

    def add(self, obj: Any) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model: type[Any], object_id: Any) -> Any | None:
        return next(
            (
                obj
                for obj in self.objects
                if isinstance(obj, model) and getattr(obj, "id", None) == object_id
            ),
            None,
        )


class _TestRedis:
    async def get(self, key: str) -> None:
        return None

    async def set(self, key: str, value: str, *, ex: int) -> None:
        return None


@pytest.fixture(scope="session")
def event_loop_policy():
    return uvloop.EventLoopPolicy()


@pytest.fixture(autouse=True)
def _external_service_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_response_cache, "redis_client", _TestRedis())


@pytest.fixture
async def client() -> httpx.AsyncClient:
    session = _TestSession()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                ac.app = app  # type: ignore[attr-defined]
                yield ac
        finally:
            app.dependency_overrides.pop(get_db, None)
