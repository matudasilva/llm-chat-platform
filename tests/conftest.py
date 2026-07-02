# tests/conftest.py
from __future__ import annotations

from contextlib import AbstractAsyncContextManager
import os
from typing import Any

import httpx
import pytest
import uvloop
from httpx import ASGITransport
from asgi_lifespan import LifespanManager
from pydantic import AliasChoices
from pydantic_settings import PydanticBaseSettingsSource

# Prevent the module-level production singleton from reading .env during this
# import. The Settings class is then made dotenv-free for direct constructions
# performed by unit tests.
os.environ["APP_SETTINGS_ENV_FILE"] = ""
import app.core.settings as settings_module

settings_module.Settings.model_config["env_file"] = None


def _clear_exported_settings() -> None:
    for field_name, field in settings_module.Settings.model_fields.items():
        names = {field_name, field_name.upper()}
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias)
        elif isinstance(alias, AliasChoices):
            names.update(choice for choice in alias.choices if isinstance(choice, str))

        for name in names:
            os.environ.pop(name, None)


_clear_exported_settings()


class _TestSettings(settings_module.Settings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[settings_module.Settings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


# Replace the settings singleton before importing app.main. _TestSettings only
# accepts direct init values, so neither .env nor exported shell variables can
# affect pytest.
settings_module.settings = _TestSettings(
    app_env="test",
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    PRIMARY_PROVIDER="stub",
    FALLBACK_PROVIDER=None,
    routing_policy="static",
    routing_shadow_policy=None,
    routing_shadow_mode_enabled=False,
    stub_provider_mode="ok",
    notion_mcp_enabled=False,
    notion_read_enabled=False,
    notion_write_enabled=False,
    web_read_enabled=False,
)

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
