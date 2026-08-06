"""ORQ-24 AC1-AC5: CascadingRerankerAdapter unit tests against fake ports.

Covers: primary success (no cascade), transient GCP failure (cascade to
AWS), terminal GCP failure (no cascade, propagates directly), unnormalized
GCP exception (defensive boundary catch still cascades), both providers
failing (propagates so RetrievalPipeline's own RRF fallback applies), and
content-free cascade telemetry.
"""

from __future__ import annotations

import logging

import pytest

from app.core.domain.reranker import (
    RankedDocument,
    RerankerError,
    RerankerPort,
    RerankRequest,
    TerminalRerankerError,
    TransientRerankerError,
)
from app.core.providers.cascading_reranker import CascadingRerankerAdapter
from app.core.domain.provider import ProviderInput, ProviderResult
from app.core.domain.retrieval_pipeline import RetrievalPipeline
from app.core.domain.vector_store import RetrievedChunk
import uuid


class _FakeRerankerPort:
    def __init__(self, *, results: list[RankedDocument] | None = None, raises: Exception | None = None) -> None:
        self._results = results if results is not None else []
        self._raises = raises
        self.calls = 0

    async def rerank(self, request: RerankRequest):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._results


_REQUEST = RerankRequest(query="q", documents=["a", "b"], top_n=2)
_RESULTS = [RankedDocument(index=0, rank=1, relevance_score=0.9)]


@pytest.mark.asyncio
async def test_primary_success_never_calls_fallback():
    primary = _FakeRerankerPort(results=_RESULTS)
    fallback = _FakeRerankerPort(results=_RESULTS)
    adapter = CascadingRerankerAdapter(primary=primary, fallback=fallback)

    results = await adapter.rerank(_REQUEST)

    assert results == _RESULTS
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_transient_primary_failure_cascades_to_fallback():
    primary = _FakeRerankerPort(raises=TransientRerankerError("throttled", backend="gcp", error_code="ThrottlingException"))
    fallback = _FakeRerankerPort(results=_RESULTS)
    adapter = CascadingRerankerAdapter(primary=primary, fallback=fallback)

    results = await adapter.rerank(_REQUEST)

    assert results == _RESULTS
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_terminal_primary_failure_propagates_without_cascade():
    primary = _FakeRerankerPort(raises=TerminalRerankerError("bad config", backend="gcp"))
    fallback = _FakeRerankerPort(results=_RESULTS)
    adapter = CascadingRerankerAdapter(primary=primary, fallback=fallback)

    with pytest.raises(TerminalRerankerError):
        await adapter.rerank(_REQUEST)

    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_unnormalized_primary_exception_still_cascades():
    primary = _FakeRerankerPort(raises=ValueError("unexpected bug in gcp adapter"))
    fallback = _FakeRerankerPort(results=_RESULTS)
    adapter = CascadingRerankerAdapter(primary=primary, fallback=fallback)

    results = await adapter.rerank(_REQUEST)

    assert results == _RESULTS
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_both_providers_failing_propagates_rerankererror():
    primary = _FakeRerankerPort(raises=TransientRerankerError("throttled", backend="gcp"))
    fallback = _FakeRerankerPort(raises=TerminalRerankerError("bad request", backend="aws"))
    adapter = CascadingRerankerAdapter(primary=primary, fallback=fallback)

    with pytest.raises(RerankerError):
        await adapter.rerank(_REQUEST)


@pytest.mark.asyncio
async def test_both_providers_failing_lets_retrieval_pipeline_fall_back_to_rrf():
    """AC4 end-to-end: RetrievalPipeline's existing `except RerankerError` fallback
    applies unchanged when the cascade itself is exhausted -- no pipeline change
    needed for this ORQ."""

    class _FakeProvider:
        async def generate(self, input: ProviderInput) -> ProviderResult:
            return ProviderResult(content="rewritten query", provider="stub", model_version="v1", prompt_version="v1")

    class _FakeEmbedding:
        async def embed_one(self, text: str):
            return [0.1, 0.2, 0.3]

        async def embed_many(self, texts):
            raise NotImplementedError

    candidate = RetrievedChunk(chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), text="chunk 0", score=1.0)

    class _FakeVectorStore:
        async def upsert_chunks(self, chunks):
            raise NotImplementedError

        async def hybrid_search(self, query_text, query_embedding, *, top_k=20):
            return [candidate]

    primary = _FakeRerankerPort(raises=TransientRerankerError("throttled", backend="gcp"))
    fallback = _FakeRerankerPort(raises=TerminalRerankerError("bad request", backend="aws"))
    cascade = CascadingRerankerAdapter(primary=primary, fallback=fallback)

    pipeline = RetrievalPipeline(
        provider=_FakeProvider(),
        embedding=_FakeEmbedding(),
        vector_store=_FakeVectorStore(),
        reranker=cascade,
        top_n=5,
        min_reranked_results=5,
    )

    result = await pipeline.retrieve(request_id=uuid.uuid4(), query="q")

    # Cascade exhausted (both providers failed) -> pipeline degrades to
    # pre-rerank RRF order (the single candidate from hybrid_search),
    # exactly as it already does for a plain RerankerError today.
    assert [c.chunk.text for c in result.chunks] == ["chunk 0"]


@pytest.mark.asyncio
async def test_cascade_telemetry_is_content_free(caplog):
    caplog.set_level(logging.INFO, logger="app.reranker_cascade")
    primary = _FakeRerankerPort(raises=ValueError("unexpected bug"))
    fallback = _FakeRerankerPort(results=_RESULTS)
    adapter = CascadingRerankerAdapter(primary=primary, fallback=fallback)

    await adapter.rerank(RerankRequest(query="secret query text", documents=["secret document content"], top_n=1))

    for record in caplog.records:
        haystack = record.getMessage() + " ".join(str(v) for v in vars(record).values())
        assert "secret query text" not in haystack
        assert "secret document content" not in haystack

    cascade_records = [r for r in caplog.records if r.name == "app.reranker_cascade"]
    assert cascade_records
    assert cascade_records[-1].error_code == "unnormalized"
    assert cascade_records[-1].fallback_attempted is True
