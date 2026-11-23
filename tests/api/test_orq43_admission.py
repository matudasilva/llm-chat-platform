from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.api.deps import ChatAdmission, admit_chat_request, get_chat_db
from app.core.domain.manual_model_catalog import ManualModelCatalog, ManualModelEntry
from app.core.settings import settings
from app.infra.db.session import get_db
from app.schemas.chat import ChatRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("model_id", ["missing", "disabled"])
async def test_invalid_selection_does_not_acquire_database(stream, model_id):
    app = FastAPI()
    disabled = ManualModelEntry("disabled", False, "Disabled", "", "bedrock", "m", "us-east-1", 100)
    app.state.chat_generation = SimpleNamespace(settings=settings.model_copy(deep=True), catalog=ManualModelCatalog((disabled,)))
    calls = []

    async def override_db():
        calls.append("db")
        yield object()

    app.dependency_overrides[get_db] = override_db

    @app.post("/chat")
    async def chat(payload: ChatRequest, db=Depends(get_chat_db)):
        calls.append("handler")
        return {}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"message": "hello", "stream": stream, "model_id": model_id})
    assert response.status_code == 422
    assert "text/event-stream" not in response.headers.get("content-type", "")
    assert calls == []


@pytest.mark.asyncio
async def test_valid_admission_precedes_database_override_and_is_cached():
    app = FastAPI()
    entry = ManualModelEntry("selected", True, "Selected", "", "bedrock", "m", "us-east-1", 100)
    app.state.chat_generation = SimpleNamespace(settings=settings.model_copy(deep=True), catalog=ManualModelCatalog((entry,)))
    calls = []

    async def override_db():
        calls.append("db")
        yield object()

    app.dependency_overrides[get_db] = override_db

    @app.post("/chat")
    async def chat(payload: ChatRequest, db=Depends(get_chat_db), admission: ChatAdmission = Depends(admit_chat_request)):
        calls.append(admission.entry.id)
        return {"bypass": admission.cache_bypass}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"message": "hello", "model_id": "selected"})
    assert response.json() == {"bypass": True}
    assert calls == ["db", "selected"]
