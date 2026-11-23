"""Hermetic HTTP coverage of the installed chat route and manual resolver."""
import json

import httpx
import pytest

import app.api.routes.chat as route
import app.core.domain.provider_factory as factory
from app.core.domain.manual_model_catalog import build_chat_generation
from app.core.domain.provider import ProviderResult, ProviderStreamResult, ProviderStreamSession
from app.core.settings import settings
from app.infra.db.session import get_db
from app.main import app
from app.http.middleware.tenant import get_tenant_id
from tests.api.test_chat_response_cache import FakeAsyncSession, FakeCache


def generation(model="model-a", cap=37):
    cfg = settings.model_copy(deep=True)
    cfg.chat_rag_augmentation_enabled = False
    cfg.conversation_history_enabled = False
    cfg.rag_request_metrics_enabled = False
    cfg.manual_model_allowlist_json = json.dumps([["bedrock", model, "us-east-1"]])
    cfg.manual_model_catalog_json = json.dumps([
        {"id": "selected", "enabled": True, "display_name": "Selected", "description": "",
         "provider": "bedrock", "model": model, "location": "us-east-1", "max_output_tokens": cap},
        {"id": "disabled", "enabled": False, "display_name": "Disabled", "description": "",
         "provider": "bedrock", "model": model, "location": "us-east-1", "max_output_tokens": cap},
    ])
    return build_chat_generation(cfg)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("tenant", ["tenant-a", "tenant-b"])
async def test_manual_selection_through_real_route_bypasses_cache_and_binds_snapshot(monkeypatch, stream, tenant):
    initial = generation()
    monkeypatch.setattr(app.state, "chat_generation", initial, raising=False)
    calls = []
    cache = FakeCache()
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: cache)
    session = FakeAsyncSession()

    async def override_db():
        calls.append(("db", get_tenant_id()))
        yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)

    class FakeBedrock:
        def __init__(self, cfg):
            calls.append(("provider", cfg.model, cfg.region))
            # Simulate publication after the request has already been admitted.
            app.state.chat_generation = generation("model-b", 99)

        async def generate(self, input):
            calls.append(("generate", input.max_tokens, get_tenant_id()))
            return result()

        async def stream(self, input):
            calls.append(("stream", input.max_tokens, get_tenant_id()))
            async def chunks():
                yield "hello"
            async def final():
                return ProviderStreamResult(content="hello", provider_result=result())
            return ProviderStreamSession(chunks=chunks(), get_final_result=final)

    def result():
        return ProviderResult(content="hello", provider="bedrock", model_version="model-a", prompt_version="v1")

    monkeypatch.setattr(factory, "BedrockProvider", FakeBedrock)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", headers={"X-Tenant-ID": tenant}, json={"message": "hello", "model_id": "selected", "stream": stream})
    assert response.status_code == 200
    if stream:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: token" in response.text and "hello" in response.text
    else:
        assert response.json()["assistant_content"] == "hello"
    assert ("provider", "model-a", "us-east-1") in calls
    assert ("stream" if stream else "generate", 37, tenant) in calls
    assert cache.reads == cache.writes == 0
    assert calls.count(("db", tenant)) == 1


@pytest.mark.asyncio
async def test_models_endpoint_has_the_same_safe_global_projection_for_each_tenant(monkeypatch):
    monkeypatch.setattr(app.state, "chat_generation", generation(), raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/models", headers={"X-Tenant-ID": "tenant-a"})
        second = await client.get("/models", headers={"X-Tenant-ID": "tenant-b"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {
        "models": [{"id": "selected", "display_name": "Selected", "description": ""}]
    }
    assert set(first.json()["models"][0]) == {"id", "display_name", "description"}


@pytest.mark.asyncio
async def test_two_messages_in_one_conversation_can_select_different_models(monkeypatch):
    cfg = settings.model_copy(deep=True)
    cfg.chat_rag_augmentation_enabled = False
    cfg.conversation_history_enabled = False
    cfg.rag_request_metrics_enabled = False
    cfg.manual_model_allowlist_json = json.dumps([
        ["bedrock", "model-a", "us-east-1"], ["bedrock", "model-b", "us-east-1"]
    ])
    cfg.manual_model_catalog_json = json.dumps([
        {"id": "first", "enabled": True, "display_name": "First", "description": "",
         "provider": "bedrock", "model": "model-a", "location": "us-east-1", "max_output_tokens": 37},
        {"id": "second", "enabled": True, "display_name": "Second", "description": "",
         "provider": "bedrock", "model": "model-b", "location": "us-east-1", "max_output_tokens": 51},
    ])
    monkeypatch.setattr(app.state, "chat_generation", build_chat_generation(cfg), raising=False)
    session, cache, selections = FakeAsyncSession(), FakeCache(), []
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: cache)

    async def override_db():
        yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)

    class FakeBedrock:
        def __init__(self, provider_cfg):
            self.model = provider_cfg.model
            selections.append(self.model)

        async def generate(self, input):
            return ProviderResult(content="answer", provider="bedrock", model_version=self.model, prompt_version="v1")

    monkeypatch.setattr(factory, "BedrockProvider", FakeBedrock)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/chat", headers={"X-Tenant-ID": "tenant-a"},
                                  json={"message": "first turn", "model_id": "first"})
        conversation_id = first.json()["conversation_id"]
        second = await client.post("/chat", headers={"X-Tenant-ID": "tenant-a"},
                                   json={"message": "second turn", "model_id": "second",
                                         "conversation_id": conversation_id})
    assert first.status_code == second.status_code == 200
    assert selections == ["model-a", "model-b"]
    assert len(session.messages) == 4
    assert cache.reads == cache.writes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["disabled", "unknown", "bad id"])
@pytest.mark.parametrize("stream", [False, True])
async def test_invalid_selection_has_no_side_effects_in_real_route(monkeypatch, model_id, stream):
    monkeypatch.setattr(app.state, "chat_generation", generation(), raising=False)
    calls = []
    async def override_db():
        calls.append("db")
        yield FakeAsyncSession()
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: calls.append("cache"))
    monkeypatch.setattr(factory, "BedrockProvider", lambda cfg: calls.append("provider"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", headers={"X-Tenant-ID": "tenant-a"}, json={"message": "hello", "model_id": model_id, "stream": stream})
    assert response.status_code == 422
    assert not response.headers.get("content-type", "").startswith("text/event-stream")
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"stream": False},
    {"message": "hello", "unexpected": True},
    {"message": "hello", "model_id": "x" * 1000},
])
async def test_malformed_body_fails_before_chat_dependencies(monkeypatch, body):
    monkeypatch.setattr(app.state, "chat_generation", generation(), raising=False)
    calls = []

    async def override_db():
        calls.append("db")
        yield FakeAsyncSession()

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: calls.append("cache"))
    monkeypatch.setattr(factory, "BedrockProvider", lambda cfg: calls.append("provider"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json=body)
    assert response.status_code == 422
    assert not response.headers.get("content-type", "").startswith("text/event-stream")
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_manual_provider_failure_never_falls_back_or_persists(monkeypatch, stream):
    from app.core.domain.provider_errors import ProviderError, ProviderErrorKind

    monkeypatch.setattr(app.state, "chat_generation", generation(), raising=False)
    class Transaction:
        async def __aenter__(self):
            return session
        async def __aexit__(self, exc_type, exc, tb):
            if exc_type is not None:
                session.messages.clear()
            return False
    class RollbackSession(FakeAsyncSession):
        def begin(self):
            return Transaction()
    session = RollbackSession()
    cache = FakeCache()
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: cache)
    async def override_db():
        yield session
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    calls = []

    class FailingBedrock:
        def __init__(self, cfg):
            calls.append("selected")
        async def generate(self, input):
            raise ProviderError(ProviderErrorKind.upstream, "failed", provider="bedrock", retryable=True)
        async def stream(self, input):
            async def chunks():
                yield "partial"
                raise ProviderError(ProviderErrorKind.upstream, "failed", provider="bedrock", retryable=True)
            async def final():
                raise AssertionError("failed stream must not finalize")
            return ProviderStreamSession(chunks=chunks(), get_final_result=final)

    monkeypatch.setattr(factory, "BedrockProvider", FailingBedrock)
    monkeypatch.setattr(factory, "ResilientProvider", lambda *args, **kwargs: calls.append("fallback"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"message": "hello", "model_id": "selected", "stream": stream})
    if stream:
        assert "partial" in response.text and "event: error" in response.text
    else:
        assert response.json()["status"] == "error"
    assert calls == ["selected"]
    assert session.messages == []
    assert cache.reads == cache.writes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_real_vertex_adapter_receives_context_cap_and_finalizes_usage(monkeypatch, stream):
    import uuid
    import app.api.deps as deps
    import app.core.observability.routing_evidence as evidence
    from app.core.domain.chat_memory import ChatMemoryContext, RetrievedMemoryEvent
    from app.core.domain.rag_generation import RagGenerationContext, RagSource
    from app.core.domain.types import ChatMessage
    from app.core.providers.vertex_provider import VertexProvider
    from app.models.usage_event import UsageEvent

    cfg = settings.model_copy(deep=True)
    cfg.manual_vertex_enabled = True
    cfg.vertex_project_id = "test-project"
    cfg.chat_rag_augmentation_enabled = True
    cfg.conversation_history_enabled = True
    cfg.rag_request_metrics_enabled = False
    cfg.manual_model_allowlist_json = json.dumps([["vertex", "gemini-test", "us-central1"]])
    cfg.manual_model_catalog_json = json.dumps([{
        "id": "selected", "enabled": True, "display_name": "Test", "description": "",
        "provider": "vertex", "model": "gemini-test", "location": "us-central1", "max_output_tokens": 47,
    }])
    monkeypatch.setattr(app.state, "chat_generation", build_chat_generation(cfg), raising=False)
    cache = FakeCache()
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: cache)
    usage_events = []

    class Session(FakeAsyncSession):
        def add(self, obj):
            super().add(obj)
            if isinstance(obj, UsageEvent):
                usage_events.append(obj)

    session = Session()
    async def override_db():
        yield session
    async def memory():
        return ChatMemoryContext(messages=(ChatMessage(role="user", content="earlier question"),
                                           ChatMessage(role="assistant", content="earlier answer")),
                                 retrieved_events=(RetrievedMemoryEvent(event_id=1, content="memory evidence"),))
    async def rag():
        return RagGenerationContext(sources=(RagSource(citation="S1", document_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(), rank=1, content="document evidence", truncated=False),))
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setitem(app.dependency_overrides, deps.get_chat_memory_context, memory)
    monkeypatch.setitem(app.dependency_overrides, deps.get_chat_rag_context, rag)
    seen, emitted, token_calls = [], [], []
    monkeypatch.setattr(evidence, "_emit", lambda payload: emitted.append(payload))
    usage = {"promptTokenCount": 12, "candidatesTokenCount": 3, "thoughtsTokenCount": 2, "totalTokenCount": 17}
    final = {"candidates": [{"content": {"parts": [{"text": "answer"}]}, "finishReason": "STOP"}],
             "usageMetadata": usage, "modelVersion": "gemini-reported"}

    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield ("data: " + json.dumps(final) + "\n\n").encode()

    def respond(request):
        seen.append(request)
        if stream:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Bytes())
        return httpx.Response(200, json=final)

    async def token():
        token_calls.append(True)
        return "fake-token"

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as vertex_client:
        monkeypatch.setattr(factory, "VertexProvider", lambda cfg: VertexProvider(cfg, http_client=vertex_client, access_token_provider=token))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"message": "current question", "model_id": "selected", "stream": stream})
    assert response.status_code == 200
    assert ("event: token" in response.text and "answer" in response.text) if stream else response.json()["assistant_content"] == "answer"
    assert len(seen) == len(token_calls) == 1
    payload = json.loads(seen[0].content)
    assert payload["generationConfig"]["maxOutputTokens"] == 47
    assert [x["role"] for x in payload["contents"]] == ["user", "model", "user"]
    assert [x["parts"][0]["text"] for x in payload["contents"]] == ["earlier question", "earlier answer", "current question"]
    systems = " ".join(part["text"] for part in payload["systemInstruction"]["parts"])
    assert "memory evidence" in systems and "document evidence" in systems
    assert len(usage_events) == 1
    assert (usage_events[0].input_tokens, usage_events[0].output_tokens, usage_events[0].total_tokens) == (12, 5, 17)
    assert len(emitted) == 1
    event = emitted[0]
    assert (event["selected_provider"], event["selected_model"]) == ("vertex", "gemini-test")
    assert (event["input_tokens"], event["output_tokens"], event["total_tokens"]) == (12, 5, 17)
    assert event["final_model"] is None and event["final_provider"] is None
    assert event["final_generation_estimated_cost_usd"] is None
    assert cache.reads == cache.writes == 0


def vertex_failure_generation():
    cfg = settings.model_copy(deep=True)
    cfg.manual_vertex_enabled = True
    cfg.vertex_project_id = "test-project"
    cfg.vertex_max_attempts = 1
    cfg.chat_rag_augmentation_enabled = False
    cfg.conversation_history_enabled = False
    cfg.rag_request_metrics_enabled = False
    cfg.manual_model_allowlist_json = json.dumps([["vertex", "gemini-test", "us-central1"]])
    cfg.manual_model_catalog_json = json.dumps([{
        "id": "selected", "enabled": True, "display_name": "Test", "description": "",
        "provider": "vertex", "model": "gemini-test", "location": "us-central1", "max_output_tokens": 47,
    }])
    return build_chat_generation(cfg)


@pytest.mark.asyncio
@pytest.mark.parametrize("emit_first", [False, True])
async def test_vertex_stream_transport_failure_never_falls_back_or_writes(monkeypatch, emit_first):
    from app.core.providers.vertex_provider import VertexProvider

    monkeypatch.setattr(app.state, "chat_generation", vertex_failure_generation(), raising=False)
    session, cache, calls = FakeAsyncSession(), FakeCache(), []
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: cache)
    async def override_db():
        yield session
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setattr(factory, "ResilientProvider", lambda *a, **kw: calls.append("fallback"))

    class BrokenStream(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            if emit_first:
                chunk = {"candidates": [{"content": {"parts": [{"text": "partial"}]}}]}
                yield ("data: " + json.dumps(chunk) + "\n\n").encode()
            raise httpx.ReadError("synthetic transport failure")
        async def aclose(self):
            self.closed = True

    body = BrokenStream()
    def respond(request):
        calls.append("vertex")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)
    async def token():
        return "fake-token"
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as vertex_client:
        monkeypatch.setattr(factory, "VertexProvider", lambda cfg: VertexProvider(cfg, http_client=vertex_client, access_token_provider=token))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"message": "hello", "model_id": "selected", "stream": True})
    assert response.status_code == 200
    assert response.text.count("event: error") == 1
    assert "event: done" not in response.text
    assert ("partial" in response.text) is emit_first
    assert calls == ["vertex"] and body.closed
    assert session.messages == [] and session._store == {}
    assert cache.reads == cache.writes == 0


@pytest.mark.asyncio
async def test_vertex_http_disconnect_closes_upstream_stream(monkeypatch):
    import asyncio
    from app.core.providers.vertex_provider import VertexProvider

    monkeypatch.setattr(app.state, "chat_generation", vertex_failure_generation(), raising=False)
    session, cache, calls = FakeAsyncSession(), FakeCache(), []
    monkeypatch.setattr(route, "get_chat_response_cache", lambda: cache)
    async def override_db():
        yield session
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setattr(factory, "ResilientProvider", lambda *a, **kw: calls.append("fallback"))
    disconnected = asyncio.Event()
    closed = asyncio.Event()

    class HangingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            chunk = {"candidates": [{"content": {"parts": [{"text": "partial"}]}}]}
            yield ("data: " + json.dumps(chunk) + "\n\n").encode()
            await asyncio.Event().wait()
        async def aclose(self):
            closed.set()
    def respond(request):
        calls.append("vertex")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=HangingStream())
    async def token():
        return "fake-token"
    raw = json.dumps({"message": "hello", "model_id": "selected", "stream": True}).encode()
    received = False
    messages = []
    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}
    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and b"partial" in message.get("body", b""):
            disconnected.set()
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
             "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/chat",
             "raw_path": b"/chat", "query_string": b"", "root_path": "",
             "headers": [(b"host", b"test"), (b"content-type", b"application/json"),
                         (b"content-length", str(len(raw)).encode())],
             "client": ("test", 1234), "server": ("test", 80)}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as vertex_client:
        monkeypatch.setattr(factory, "VertexProvider", lambda cfg: VertexProvider(cfg, http_client=vertex_client, access_token_provider=token))
        await asyncio.wait_for(app(scope, receive, send), timeout=2)
        await asyncio.wait_for(closed.wait(), timeout=2)
    assert disconnected.is_set() and calls == ["vertex"]
    assert session.messages == [] and session._store == {}
    assert cache.reads == cache.writes == 0
