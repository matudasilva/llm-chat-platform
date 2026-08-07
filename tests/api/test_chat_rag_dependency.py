from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, nullcontext
from types import SimpleNamespace

import pytest

import app.api.deps as deps
from app.infra.db.session import short_lived_rag_session
from app.schemas.chat import ChatRequest


@asynccontextmanager
async def _session(_request):
    yield object()


@pytest.mark.asyncio
async def test_chat_rag_dependency_is_inert_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(deps.settings, "chat_rag_augmentation_enabled", False)

    context = await deps.get_chat_rag_context(
        ChatRequest(message="question"),
        SimpleNamespace(),
    )

    assert context.sources == ()


@pytest.mark.asyncio
async def test_chat_rag_dependency_degrades_when_pipeline_construction_fails(monkeypatch) -> None:
    monkeypatch.setattr(deps.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(deps, "short_lived_rag_session", _session)

    def _fail(*args, **kwargs):
        raise RuntimeError("missing provider configuration")

    monkeypatch.setattr(deps, "build_retrieval_pipeline", _fail)

    context = await deps.get_chat_rag_context(
        ChatRequest(message="question"),
        SimpleNamespace(),
    )

    assert context.sources == ()


class _RagSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.transaction_open = True

    def in_transaction(self) -> bool:
        return self.transaction_open

    async def rollback(self) -> None:
        self.events.append("rag_rollback")
        self.transaction_open = False


class _SessionContext:
    def __init__(self, session: _RagSession) -> None:
        self.session = session

    async def __aenter__(self):
        self.session.events.append("rag_begin")
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.session.events.append("rag_close")


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_short_lived_rag_session_rolls_back_and_closes_on_every_exit(raises) -> None:
    events: list[str] = []
    session = _RagSession(events)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(rag_db_sessionmaker=lambda: _SessionContext(session))
        )
    )

    expectation = pytest.raises(RuntimeError) if raises else nullcontext()
    with expectation:
        async with short_lived_rag_session(request):
            events.append("retrieve")
            if raises:
                raise RuntimeError("pipeline failed")

    events.append("business_begin")
    assert events == [
        "rag_begin",
        "retrieve",
        "rag_rollback",
        "rag_close",
        "business_begin",
    ]


@pytest.mark.asyncio
async def test_retrieval_timeout_closes_rag_session_before_provider_stream(monkeypatch) -> None:
    events: list[str] = []
    session = _RagSession(events)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(rag_db_sessionmaker=lambda: _SessionContext(session))
        )
    )

    class _DelayedPipeline:
        async def retrieve(self, *, request_id, query):
            events.append("retrieve")
            await asyncio.sleep(0.05)

    monkeypatch.setattr(deps.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(deps.settings, "chat_rag_retrieval_timeout_s", 0.001)
    monkeypatch.setattr(deps, "build_retrieval_pipeline", lambda db, settings: _DelayedPipeline())

    context = await deps.get_chat_rag_context(ChatRequest(message="question"), request)
    events.append("provider_stream")

    assert context.sources == ()
    assert events == [
        "rag_begin",
        "retrieve",
        "rag_rollback",
        "rag_close",
        "provider_stream",
    ]
