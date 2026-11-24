"""HTTP fallback and transactional evidence with a real SQLite session."""

import json

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.api.routes.chat as route
import app.core.domain.provider_factory as factory
from app.core.domain.manual_model_catalog import build_chat_generation
from app.core.domain.provider import ProviderResult, ProviderStreamResult, ProviderStreamSession
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.settings import settings
from app.infra.db.session import get_db
from app.main import app
from tests.api.test_chat_response_cache import FakeCache


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("selected", [False, True])
async def test_http_fallback_and_atomic_writes_with_real_session(monkeypatch, stream, selected):
    cfg = settings.model_copy(deep=True)
    cfg.provider = "bedrock"
    cfg.bedrock_model = "primary-model"
    cfg.bedrock_region = "us-east-1"
    cfg.fallback_provider = "openai"
    cfg.openai_api_key = "test-key"
    cfg.chat_rag_augmentation_enabled = False
    cfg.conversation_history_enabled = False
    cfg.rag_request_metrics_enabled = False
    cfg.manual_model_allowlist_json = json.dumps([["bedrock", "primary-model", "us-east-1"]])
    cfg.manual_model_catalog_json = json.dumps([{
        "id": "selected", "enabled": True, "display_name": "Selected", "description": "",
        "provider": "bedrock", "model": "primary-model", "location": "us-east-1", "max_output_tokens": 37,
    }])
    monkeypatch.setattr(app.state, "chat_generation", build_chat_generation(cfg), raising=False)
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: FakeCache())
    calls = []

    class Primary:
        provider_name = "bedrock"
        def __init__(self, config):
            pass
        async def generate(self, input):
            calls.append("primary")
            raise ProviderError(ProviderErrorKind.upstream, "synthetic failure", provider="bedrock", retryable=True)
        async def stream(self, input):
            calls.append("primary")
            async def chunks():
                raise ProviderError(ProviderErrorKind.upstream, "synthetic failure", provider="bedrock", retryable=True)
                yield "unreachable"
            async def final():
                raise AssertionError("failed stream must not finalize")
            return ProviderStreamSession(chunks=chunks(), get_final_result=final)

    class Fallback:
        provider_name = "openai"
        def __init__(self, config):
            pass
        async def generate(self, input):
            calls.append("fallback")
            return result()
        async def stream(self, input):
            calls.append("fallback")
            async def chunks():
                yield "fallback answer"
            async def final():
                return ProviderStreamResult(content="fallback answer", provider_result=result())
            return ProviderStreamSession(chunks=chunks(), get_final_result=final)

    def result():
        return ProviderResult(content="fallback answer", provider="openai", model_version="fallback-model", prompt_version="v1")

    monkeypatch.setattr(factory, "BedrockProvider", Primary)
    monkeypatch.setattr(factory, "OpenAIProvider", Fallback)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # SQLite substitutes for PostgreSQL transaction semantics; the schema only
    # adapts JSONB and the PostgreSQL-generated message sequence for this test.
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE conversations (id UUID PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, title VARCHAR(255), metadata JSON)"))
        await connection.execute(text("CREATE TABLE messages (id UUID PRIMARY KEY, sequence BIGINT NOT NULL DEFAULT 0, conversation_id UUID NOT NULL, role VARCHAR(20) NOT NULL, tenant_id VARCHAR(64) NOT NULL, content TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
        await connection.execute(text("CREATE TABLE usage_events (id UUID PRIMARY KEY, conversation_id UUID, message_id UUID, provider VARCHAR(64) NOT NULL, model_version VARCHAR(128) NOT NULL, prompt_version VARCHAR(64) NOT NULL, request_id UUID, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, latency_ms INTEGER, status VARCHAR(32), error_message TEXT, feedback VARCHAR(8), feedback_updated_at DATETIME, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    inserts = []

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def record_inserts(conn, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().upper()
        if normalized.startswith("INSERT INTO CONVERSATIONS"):
            inserts.append("conversation")
        elif normalized.startswith("INSERT INTO MESSAGES"):
            inserts.append("message")

    async def override_db():
        async with maker() as session:
            yield session
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    body = {"message": "hello", "stream": stream}
    if selected:
        body["model_id"] = "selected"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", headers={"X-Tenant-ID": "tenant-a"}, json=body)
        assert response.status_code == 200
        if selected:
            assert calls == ["primary"]
            assert ("event: error" in response.text) if stream else response.json()["status"] == "error"
        else:
            assert calls == ["primary", "fallback"]
            assert ("fallback answer" in response.text and "event: done" in response.text) if stream else response.json()["assistant_content"] == "fallback answer"
        async with engine.connect() as connection:
            conversations = (await connection.execute(text("SELECT tenant_id FROM conversations"))).all()
            messages = (await connection.execute(text("SELECT tenant_id, role, content FROM messages ORDER BY role DESC"))).all()
        if selected:
            assert conversations == []
            assert messages == []
            if not stream:
                assert inserts == ["conversation", "message"]
        else:
            assert conversations == [("tenant-a",)]
            assert sorted(messages) == sorted([("tenant-a", "user", "hello"), ("tenant-a", "assistant", "fallback answer")])
    finally:
        await engine.dispose()
