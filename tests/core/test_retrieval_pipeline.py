"""ORQ-23 AC2 / AC8 / AC9: RetrievalPipeline unit tests against fake ports.

Covers: happy path, reranker-failure fallback, both evaluator branches, and
content-free telemetry (query text / chunk text never appear in emitted log
records).
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

import pytest

from app.core.domain.provider import ProviderInput, ProviderResult
from app.core.domain.reranker import RankedDocument, RerankRequest, TerminalRerankerError
from app.core.domain.retrieval_pipeline import RetrievalPipeline
from app.core.domain.vector_store import RetrievedChunk

_QUERY = "why does the platform favor capabilities over an orchestrator"
_REWRITTEN = "why capabilities-first instead of execution orchestrator"


class _FakeProvider:
    def __init__(self, *, rewritten: str | None = None, evaluator_verdict: str = "SUFFICIENT", fail_on: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self._rewritten = rewritten
        self._evaluator_verdict = evaluator_verdict
        self._fail_on = fail_on or set()

    async def generate(self, input: ProviderInput) -> ProviderResult:
        system = input.messages[0].content
        stage = "evaluator" if "SUFFICIENT" in system or "INSUFFICIENT" in system else "rewrite"
        self.calls.append(stage)
        if stage in self._fail_on:
            raise RuntimeError("provider unavailable")
        content = self._rewritten if stage == "rewrite" else self._evaluator_verdict
        return ProviderResult(content=content or _QUERY, provider="stub", model_version="v1", prompt_version="v1")


class _FakeEmbedding:
    async def embed_one(self, text: str) -> Sequence[float]:
        return [0.1, 0.2, 0.3]

    async def embed_many(self, texts):
        raise NotImplementedError


def _chunk(i: int, text: str = "chunk text") -> RetrievedChunk:
    return RetrievedChunk(chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), text=f"{text} {i}", score=1.0 / (i + 1))


class _FakeVectorStore:
    def __init__(self, candidates: list[RetrievedChunk]) -> None:
        self._candidates = candidates
        self.calls = 0

    async def upsert_chunks(self, chunks):
        raise NotImplementedError

    async def hybrid_search(self, query_text, query_embedding, *, top_k=20):
        self.calls += 1
        return self._candidates


class _FakeReranker:
    def __init__(self, *, results: list[RankedDocument] | None = None, raises: Exception | None = None) -> None:
        self._results = results
        self._raises = raises
        self.calls = 0

    async def rerank(self, request: RerankRequest):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._results if self._results is not None else []


def _pipeline(*, provider, vector_store, reranker, min_reranked_results=5, top_n=5):
    return RetrievalPipeline(
        provider=provider,
        embedding=_FakeEmbedding(),
        vector_store=vector_store,
        reranker=reranker,
        top_n=top_n,
        min_reranked_results=min_reranked_results,
    )


@pytest.mark.asyncio
async def test_happy_path_rewrite_retrieve_rerank_no_evaluator():
    candidates = [_chunk(i) for i in range(5)]
    provider = _FakeProvider(rewritten=_REWRITTEN)
    vector_store = _FakeVectorStore(candidates)
    # Rerank reverses the order and returns all 5 -- enough to skip the evaluator.
    reranker = _FakeReranker(
        results=[RankedDocument(index=i, rank=5 - i) for i in range(5)]
    )
    pipeline = _pipeline(provider=provider, vector_store=vector_store, reranker=reranker, min_reranked_results=5)

    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.rewritten_query == _REWRITTEN
    assert result.fallback_triggered is False
    assert result.evaluator_triggered is False
    assert result.evaluator_verdict is None
    assert [rc.rank for rc in result.chunks] == [1, 2, 3, 4, 5]
    assert provider.calls == ["rewrite"]  # no evaluator call
    assert reranker.calls == 1


@pytest.mark.asyncio
async def test_reranker_failure_falls_back_to_rrf_order():
    candidates = [_chunk(i) for i in range(5)]
    provider = _FakeProvider(rewritten=_REWRITTEN, evaluator_verdict="INSUFFICIENT")
    vector_store = _FakeVectorStore(candidates)
    reranker = _FakeReranker(raises=TerminalRerankerError("denied", backend="aws"))
    pipeline = _pipeline(provider=provider, vector_store=vector_store, reranker=reranker, top_n=3, min_reranked_results=5)

    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.fallback_triggered is True
    assert [rc.chunk.chunk_id for rc in result.chunks] == [c.chunk_id for c in candidates[:3]]
    assert [rc.rank for rc in result.chunks] == [1, 2, 3]
    # 3 < min_reranked_results=5 -> evaluator still triggers even on fallback.
    assert result.evaluator_triggered is True
    assert result.evaluator_verdict == "INSUFFICIENT"


@pytest.mark.asyncio
async def test_evaluator_triggered_when_reranked_results_are_thin():
    candidates = [_chunk(i) for i in range(2)]
    provider = _FakeProvider(rewritten=_REWRITTEN, evaluator_verdict="INSUFFICIENT")
    vector_store = _FakeVectorStore(candidates)
    reranker = _FakeReranker(results=[RankedDocument(index=0, rank=1), RankedDocument(index=1, rank=2)])
    pipeline = _pipeline(provider=provider, vector_store=vector_store, reranker=reranker, min_reranked_results=5)

    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.evaluator_triggered is True
    assert result.evaluator_verdict == "INSUFFICIENT"
    assert provider.calls == ["rewrite", "evaluator"]


@pytest.mark.asyncio
async def test_evaluator_not_triggered_when_reranked_results_meet_minimum():
    candidates = [_chunk(i) for i in range(5)]
    provider = _FakeProvider(rewritten=_REWRITTEN)
    vector_store = _FakeVectorStore(candidates)
    reranker = _FakeReranker(results=[RankedDocument(index=i, rank=i + 1) for i in range(5)])
    pipeline = _pipeline(provider=provider, vector_store=vector_store, reranker=reranker, min_reranked_results=5)

    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.evaluator_triggered is False
    assert provider.calls == ["rewrite"]


@pytest.mark.asyncio
async def test_no_candidates_returns_empty_without_reranking():
    provider = _FakeProvider(rewritten=_REWRITTEN)
    vector_store = _FakeVectorStore([])
    reranker = _FakeReranker(results=[])
    pipeline = _pipeline(provider=provider, vector_store=vector_store, reranker=reranker, min_reranked_results=5)

    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.chunks == ()
    assert result.fallback_triggered is False
    assert result.evaluator_triggered is False
    assert reranker.calls == 0


@pytest.mark.asyncio
async def test_rewrite_failure_falls_back_to_original_query():
    candidates = [_chunk(i) for i in range(5)]
    provider = _FakeProvider(fail_on={"rewrite"})
    vector_store = _FakeVectorStore(candidates)
    reranker = _FakeReranker(results=[RankedDocument(index=i, rank=i + 1) for i in range(5)])
    pipeline = _pipeline(provider=provider, vector_store=vector_store, reranker=reranker, min_reranked_results=5)

    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.rewritten_query == _QUERY  # fell back, pipeline did not raise


@pytest.mark.asyncio
async def test_top_n_override_is_forwarded_to_reranker():
    candidates = [_chunk(i) for i in range(5)]
    provider = _FakeProvider(rewritten=_REWRITTEN)
    vector_store = _FakeVectorStore(candidates)
    seen_top_n: list[int | None] = []

    class _CapturingReranker(_FakeReranker):
        async def rerank(self, request: RerankRequest):
            seen_top_n.append(request.top_n)
            return await super().rerank(request)

    reranker = _CapturingReranker(results=[RankedDocument(index=i, rank=i + 1) for i in range(2)])
    pipeline = _pipeline(provider=provider, vector_store=vector_store, reranker=reranker, top_n=5, min_reranked_results=1)

    await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY, top_n=2)

    assert seen_top_n == [2]


@pytest.mark.asyncio
async def test_telemetry_excludes_query_and_chunk_content(caplog):
    candidates = [_chunk(i, text="the secret document content") for i in range(2)]
    provider = _FakeProvider(rewritten=_REWRITTEN, evaluator_verdict="INSUFFICIENT")
    vector_store = _FakeVectorStore(candidates)
    reranker = _FakeReranker(results=[RankedDocument(index=0, rank=1), RankedDocument(index=1, rank=2)])
    pipeline = _pipeline(provider=provider, vector_store=vector_store, reranker=reranker, min_reranked_results=5)

    with caplog.at_level(logging.INFO, logger="app.core.domain.retrieval_pipeline"):
        await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    for record in caplog.records:
        payload = str(record.getMessage()) + str(getattr(record, "__dict__", {}))
        assert _QUERY not in payload
        assert _REWRITTEN not in payload
        assert "secret document content" not in payload
