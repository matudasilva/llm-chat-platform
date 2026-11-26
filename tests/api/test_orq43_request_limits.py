"""Request-size and message-length limits still apply when `model_id` is supplied."""
import httpx
import pytest

import app.core.domain.provider_factory as factory
from app.core.settings import settings
from app.infra.db.session import get_db
from app.main import app
from tests.api.test_orq43_chat_integration import generation


@pytest.fixture
def untouched(monkeypatch):
    """Selected catalog entry plus spies proving no DB session or provider is reached."""
    monkeypatch.setattr(app.state, "chat_generation", generation(), raising=False)
    calls = []

    async def override_db():
        calls.append("db")
        yield object()

    class SpyBedrock:
        def __init__(self, cfg):
            calls.append("provider")

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setattr(factory, "BedrockProvider", SpyBedrock)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_oversized_body_with_model_id_returns_413(untouched, stream):
    body = ('{"message":"hi","model_id":"selected","stream":%s,"pad":"%s"}'
            % ("true" if stream else "false", "a" * settings.max_request_bytes)).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert untouched == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_overlong_message_with_model_id_is_rejected_before_side_effects(untouched, stream):
    payload = {"message": "x" * (settings.max_message_chars + 1), "model_id": "selected", "stream": stream}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json=payload)
    assert response.status_code in (413, 422)
    assert untouched == []
