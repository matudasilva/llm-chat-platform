"""ORQ-23 AC4: the new /rag/retrieve endpoint is read-only and gated behind
`retrieval_pipeline_enabled`. Hermetic -- overrides the pipeline dependency
directly, no real Postgres/AWS/OpenAI involved. Cross-tenant RLS isolation
(AC3) is covered separately in tests/core/test_retrieval_pipeline_rls.py,
which requires a real Postgres and is marked `postgres`.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

import app.api.routes.retrieval as retrieval_routes
from app.api.routes.retrieval import get_retrieval_pipeline
from app.core.domain.retrieval_pipeline import RankedChunk, RetrievalPipelineResult
from app.core.domain.vector_store import RetrievedChunk
from app.main import app


class _FakePipeline:
    def __init__(self, result: RetrievalPipelineResult) -> None:
        self._result = result
        self.calls: list[dict] = []

    async def retrieve(self, *, request_id, query, top_n=None):
        self.calls.append({"request_id": request_id, "query": query, "top_n": top_n})
        return self._result


def _result(**overrides) -> RetrievalPipelineResult:
    chunk = RetrievedChunk(chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), text="hello", score=1.0)
    defaults = dict(
        request_id=uuid.uuid4(),
        query="q",
        rewritten_query="q rewritten",
        chunks=(RankedChunk(chunk=chunk, rank=1),),
        fallback_triggered=False,
        evaluator_triggered=False,
        evaluator_verdict=None,
    )
    defaults.update(overrides)
    return RetrievalPipelineResult(**defaults)


@pytest.mark.asyncio
async def test_retrieve_returns_403_when_disabled(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retrieval_routes.settings, "retrieval_pipeline_enabled", False)

    resp = await client.post("/rag/retrieve", json={"query": "hello"})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_retrieve_happy_path(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retrieval_routes.settings, "retrieval_pipeline_enabled", True)
    fake = _FakePipeline(_result())
    app.dependency_overrides[get_retrieval_pipeline] = lambda: fake
    try:
        resp = await client.post("/rag/retrieve", json={"query": "hello", "top_n": 3})
    finally:
        app.dependency_overrides.pop(get_retrieval_pipeline, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["rewritten_query"] == "q rewritten"
    assert body["fallback_triggered"] is False
    assert len(body["chunks"]) == 1
    assert fake.calls[0]["query"] == "hello"
    assert fake.calls[0]["top_n"] == 3


@pytest.mark.asyncio
async def test_retrieve_rejects_empty_query(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retrieval_routes.settings, "retrieval_pipeline_enabled", True)
    fake = _FakePipeline(_result())
    app.dependency_overrides[get_retrieval_pipeline] = lambda: fake
    try:
        resp = await client.post("/rag/retrieve", json={"query": ""})
    finally:
        app.dependency_overrides.pop(get_retrieval_pipeline, None)

    assert resp.status_code == 422
    assert fake.calls == []
