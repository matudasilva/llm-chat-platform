# tests/conftest.py
from __future__ import annotations

import pytest
import httpx
from httpx import ASGITransport
from asgi_lifespan import LifespanManager

from app.main import app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            ac.app = app  # type: ignore[attr-defined]
            yield ac