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


# --- AC24: retrieval_outcome, one value per branch -------------------------
#
# `sources` alone cannot carry this. An empty tuple comes back from a timeout,
# from a pipeline error, and from a run that matched nothing, and AC24 requires
# the field to be distinguishable from `generation_outcome` and
# `memory_outcome`. The domain classifies; this boundary records.


@asynccontextmanager
async def _rag_session_cm(_request):
    yield object()


def _collector():
    import uuid as _uuid

    from app.http import pipeline_metrics

    instance, token = pipeline_metrics.init_collector(
        request_instance_id=str(_uuid.uuid4()), correlation_id=None
    )
    return instance, token


def _install_pipeline(monkeypatch, *, chunks=None, raises=None, hang=False):
    """A pipeline double whose `retrieve` behaves as the arm requires."""
    from app.core.domain.retrieval_pipeline import RetrievalPipelineResult

    class _Pipeline:
        async def retrieve(self, *, request_id, query):
            if hang:
                await asyncio.sleep(10)
            if raises is not None:
                raise raises
            return RetrievalPipelineResult(
                request_id=request_id, query=query, rewritten_query=query,
                chunks=tuple(chunks or ()), fallback_triggered=False,
                evaluator_triggered=False, evaluator_verdict=None,
            )

    monkeypatch.setattr(deps.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(deps, "short_lived_rag_session", _rag_session_cm)
    monkeypatch.setattr(deps, "build_retrieval_pipeline", lambda db, cfg: _Pipeline())


def _chunk(text="a relevant passage", rank=1):
    from app.core.domain.retrieval_pipeline import RankedChunk
    from types import SimpleNamespace as _NS

    return RankedChunk(
        chunk=_NS(text=text, document_id="doc-1", chunk_id="chunk-1"), rank=rank
    )


async def _run(monkeypatch):
    from app.http import pipeline_metrics

    instance, token = _collector()
    try:
        context = await deps.get_chat_rag_context(
            ChatRequest(message="question"), SimpleNamespace()
        )
        return context, instance.snapshot().get("retrieval_outcome")
    finally:
        pipeline_metrics.reset_collector(token)


@pytest.mark.asyncio
async def test_retrieval_outcome_is_skipped_when_the_flag_is_off(monkeypatch) -> None:
    monkeypatch.setattr(deps.settings, "chat_rag_augmentation_enabled", False)
    context, recorded = await _run(monkeypatch)
    assert context.outcome == "skipped"
    assert recorded == "skipped"


@pytest.mark.asyncio
async def test_retrieval_outcome_is_ok_when_sources_are_retained(monkeypatch) -> None:
    _install_pipeline(monkeypatch, chunks=[_chunk()])
    context, recorded = await _run(monkeypatch)
    assert len(context.sources) == 1
    assert context.outcome == "ok"
    assert recorded == "ok"


@pytest.mark.asyncio
async def test_retrieval_outcome_is_empty_when_nothing_is_retained(monkeypatch) -> None:
    """Ran fine, produced nothing. NOT the same statement as a failure."""
    _install_pipeline(monkeypatch, chunks=[])
    context, recorded = await _run(monkeypatch)
    assert context.sources == ()
    assert context.outcome == "empty"
    assert recorded == "empty"


@pytest.mark.asyncio
async def test_retrieval_outcome_is_timeout_where_wait_for_observes_it(
    monkeypatch,
) -> None:
    """Classified by the augmentor, which owns the `wait_for`.

    Inferred downstream from an empty result, a timeout would be
    indistinguishable from a corpus that matched nothing.
    """
    monkeypatch.setattr(deps.settings, "chat_rag_retrieval_timeout_s", 0.01)
    _install_pipeline(monkeypatch, hang=True)
    context, recorded = await _run(monkeypatch)
    assert context.sources == ()
    assert context.outcome == "timeout"
    assert recorded == "timeout"


@pytest.mark.asyncio
async def test_retrieval_outcome_is_error_for_a_non_timeout_failure(
    monkeypatch,
) -> None:
    _install_pipeline(monkeypatch, raises=RuntimeError("vector store is down"))
    context, recorded = await _run(monkeypatch)
    assert context.sources == ()
    assert context.outcome == "error"
    assert recorded == "error"


@pytest.mark.asyncio
async def test_construction_failure_is_error_not_timeout(monkeypatch) -> None:
    """`wait_for` lives inside the augmentor, so this path can never time out."""
    monkeypatch.setattr(deps.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(deps, "short_lived_rag_session", _rag_session_cm)

    def _fail(*a, **k):
        raise RuntimeError("missing provider configuration")

    monkeypatch.setattr(deps, "build_retrieval_pipeline", _fail)
    context, recorded = await _run(monkeypatch)
    assert context.outcome == "error"
    assert recorded == "error"


@pytest.mark.asyncio
async def test_a_hostile_collector_cannot_change_the_returned_context(
    monkeypatch,
) -> None:
    """Telemetry is best-effort: a sink that raises must not reach the request.

    Same containment N-2 gave the memory recorders, asserted here rather than
    assumed because this recorder is new.
    """
    from app.http import pipeline_metrics

    class _Hostile:
        request_instance_id = "x"
        correlation_id = None

        def record(self, **fields):
            raise RuntimeError("metrics sink down")

        def snapshot(self):
            return {}

    _install_pipeline(monkeypatch, chunks=[_chunk()])
    token = pipeline_metrics._collector_var.set(_Hostile())
    try:
        context = await deps.get_chat_rag_context(
            ChatRequest(message="question"), SimpleNamespace()
        )
    finally:
        pipeline_metrics.reset_collector(token)

    assert len(context.sources) == 1
    assert context.outcome == "ok"
