from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from .embedding import EmbeddingPort
from .provider import ProviderInput, ProviderPort
from .reranker import RankedDocument, RerankerError, RerankerPort, RerankRequest
from .types import ChatMessage
from .vector_store import RetrievedChunk, VectorStorePort

logger = logging.getLogger(__name__)

# ORQ-23 spec.md §Scope: paraphrase/expand only, never answer the query --
# regression-tested against ORQ-21's golden set so a bad rewrite is caught
# as a recall regression, not silently shipped (R1).
_REWRITE_PROMPT = (
    "You rewrite a user's search query to improve retrieval over a technical "
    "document corpus. Preserve the query's original language. Paraphrase and "
    "expand likely abbreviations or synonyms; do not narrow or answer the "
    "query. Reply with only the rewritten query, one line, no commentary."
)

# ORQ-23 spec.md §Design decisions 5: single-shot, conditional, no agentic
# retry loop.
_EVALUATOR_PROMPT = (
    "You judge whether the passages below are sufficient to answer the "
    "query. Reply with exactly one word: SUFFICIENT or INSUFFICIENT."
)


@dataclass(frozen=True, slots=True)
class RankedChunk:
    """A retrieved chunk paired with its final, authoritative one-based rank."""

    chunk: RetrievedChunk
    rank: int


@dataclass(frozen=True, slots=True)
class RetrievalPipelineResult:
    request_id: UUID
    query: str
    rewritten_query: str
    chunks: Sequence[RankedChunk]
    fallback_triggered: bool
    evaluator_triggered: bool
    evaluator_verdict: str | None


class RetrievalPipeline:
    """
    Pure orchestration service (mirrors ChatService, spec.md §Design
    decisions 3): rewrite -> retrieve -> rerank -> lightweight evaluator.

    Rules:
    - No DB access, no FastAPI/HTTP semantics -- every dependency arrives as
      an injected port.
    - Never raises on a reranker failure: degrades to pre-rerank RRF order
      (spec.md §Design decisions 4, tech-stack invariant 9).
    - The evaluator trigger is rank/count-based only, never
      `relevance_score` (spec.md §Design decisions 5 -- ORQ-22 found
      `relevance_score` incomparable across reranker backends).
    """

    def __init__(
        self,
        *,
        provider: ProviderPort,
        embedding: EmbeddingPort,
        vector_store: VectorStorePort,
        reranker: RerankerPort,
        top_k_candidates: int = 20,
        top_n: int = 5,
        min_reranked_results: int = 5,
    ) -> None:
        self._provider = provider
        self._embedding = embedding
        self._vector_store = vector_store
        self._reranker = reranker
        self._top_k_candidates = top_k_candidates
        self._top_n = top_n
        self._min_reranked_results = min_reranked_results

    async def retrieve(
        self, *, request_id: UUID, query: str, top_n: int | None = None
    ) -> RetrievalPipelineResult:
        effective_top_n = top_n if top_n is not None else self._top_n
        started = time.monotonic()

        rewritten = await self._rewrite(request_id=request_id, query=query)

        embedding = await self._embedding.embed_one(rewritten)
        candidates = await self._vector_store.hybrid_search(
            rewritten, embedding, top_k=self._top_k_candidates
        )

        if not candidates:
            self._log_completed(
                request_id=request_id,
                candidate_count=0,
                reranked_count=0,
                fallback_triggered=False,
                evaluator_triggered=False,
                started=started,
            )
            return RetrievalPipelineResult(
                request_id=request_id,
                query=query,
                rewritten_query=rewritten,
                chunks=(),
                fallback_triggered=False,
                evaluator_triggered=False,
                evaluator_verdict=None,
            )

        ranked_chunks, fallback_triggered = await self._rerank(
            request_id=request_id,
            query=rewritten,
            candidates=candidates,
            top_n=effective_top_n,
        )

        evaluator_triggered = len(ranked_chunks) < self._min_reranked_results
        evaluator_verdict: str | None = None
        if evaluator_triggered:
            evaluator_verdict = await self._evaluate(
                request_id=request_id, query=rewritten, chunks=ranked_chunks
            )

        self._log_completed(
            request_id=request_id,
            candidate_count=len(candidates),
            reranked_count=len(ranked_chunks),
            fallback_triggered=fallback_triggered,
            evaluator_triggered=evaluator_triggered,
            started=started,
        )

        return RetrievalPipelineResult(
            request_id=request_id,
            query=query,
            rewritten_query=rewritten,
            chunks=ranked_chunks,
            fallback_triggered=fallback_triggered,
            evaluator_triggered=evaluator_triggered,
            evaluator_verdict=evaluator_verdict,
        )

    async def _rewrite(self, *, request_id: UUID, query: str) -> str:
        try:
            result = await self._provider.generate(
                ProviderInput(
                    request_id=request_id,
                    messages=[
                        ChatMessage(role="system", content=_REWRITE_PROMPT),
                        ChatMessage(role="user", content=query),
                    ],
                )
            )
        except Exception:
            # Best-effort: a broken rewrite call must not break retrieval
            # (tech-stack invariant 9) -- fall back to the original query.
            logger.warning(
                "retrieval_pipeline.rewrite_failed",
                extra={
                    "event": "retrieval_pipeline.rewrite_failed",
                    "request_id": str(request_id),
                },
            )
            return query
        rewritten = result.content.strip()
        return rewritten or query

    async def _rerank(
        self,
        *,
        request_id: UUID,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_n: int,
    ) -> tuple[list[RankedChunk], bool]:
        try:
            ranked: Sequence[RankedDocument] = await self._reranker.rerank(
                RerankRequest(
                    query=query,
                    documents=[c.text for c in candidates],
                    top_n=top_n,
                )
            )
        except RerankerError:
            logger.warning(
                "retrieval_pipeline.rerank_fallback",
                extra={
                    "event": "retrieval_pipeline.rerank_fallback",
                    "request_id": str(request_id),
                    "candidate_count": len(candidates),
                },
            )
            fallback_chunks = [
                RankedChunk(chunk=chunk, rank=i + 1)
                for i, chunk in enumerate(candidates[:top_n])
            ]
            return fallback_chunks, True

        ordered = sorted(ranked, key=lambda item: item.rank)
        ranked_chunks = [
            RankedChunk(chunk=candidates[item.index], rank=item.rank) for item in ordered
        ]
        return ranked_chunks, False

    async def _evaluate(
        self, *, request_id: UUID, query: str, chunks: Sequence[RankedChunk]
    ) -> str | None:
        context = "\n\n".join(ranked.chunk.text for ranked in chunks)
        try:
            result = await self._provider.generate(
                ProviderInput(
                    request_id=request_id,
                    messages=[
                        ChatMessage(role="system", content=_EVALUATOR_PROMPT),
                        ChatMessage(
                            role="user",
                            content=f"Query: {query}\n\nPassages:\n{context}",
                        ),
                    ],
                )
            )
        except Exception:
            logger.warning(
                "retrieval_pipeline.evaluator_failed",
                extra={
                    "event": "retrieval_pipeline.evaluator_failed",
                    "request_id": str(request_id),
                },
            )
            return None
        verdict = result.content.strip().upper()
        return verdict or None

    def _log_completed(
        self,
        *,
        request_id: UUID,
        candidate_count: int,
        reranked_count: int,
        fallback_triggered: bool,
        evaluator_triggered: bool,
        started: float,
    ) -> None:
        # Content-free by construction (ORQ-23 AC8): only counts, flags and
        # latency -- no query text, no chunk text.
        logger.info(
            "retrieval_pipeline.completed",
            extra={
                "event": "retrieval_pipeline.completed",
                "request_id": str(request_id),
                "candidate_count": candidate_count,
                "reranked_count": reranked_count,
                "fallback_triggered": fallback_triggered,
                "evaluator_triggered": evaluator_triggered,
                "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
            },
        )
