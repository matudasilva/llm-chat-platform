from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from app.core.observability.tracing import set_attribute, span

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

# The only two values `_EVALUATOR_PROMPT` asks for, and therefore the only two
# an attribute may carry verbatim (H4/AC4). Anything else is a model doing
# something other than what it was asked, and its text must not reach a span.
_EVALUATOR_VERDICTS = frozenset({"SUFFICIENT", "INSUFFICIENT"})


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

        # Stage boundary only -- the pipeline is not restructured to make
        # tracing convenient. An embedding or search failure propagates exactly
        # as before; the seam reports it to the span and re-raises.
        with span(
            "rag.retrieve", **{"rag.top_k_candidates": self._top_k_candidates}
        ) as retrieve_span:
            embedding = await self._embedding.embed_one(rewritten)
            candidates = await self._vector_store.hybrid_search(
                rewritten, embedding, top_k=self._top_k_candidates
            )
            set_attribute(retrieve_span, "rag.candidate_count", len(candidates))
            set_attribute(
                retrieve_span,
                "rag.retrieval_outcome",
                "candidates" if candidates else "empty",
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
        # The span opens where the stage is *attempted*, so a rewrite that
        # falls back to the original query still counts as reached.
        with span("rag.rewrite") as rewrite_span:
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
                set_attribute(rewrite_span, "rag.rewrite_outcome", "failed")
                logger.warning(
                    "retrieval_pipeline.rewrite_failed",
                    extra={
                        "event": "retrieval_pipeline.rewrite_failed",
                        "request_id": str(request_id),
                    },
                )
                return query
            rewritten = result.content.strip()
            set_attribute(
                rewrite_span,
                "rag.rewrite_outcome",
                "rewritten" if rewritten else "unchanged",
            )
            return rewritten or query

    async def _rerank(
        self,
        *,
        request_id: UUID,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_n: int,
    ) -> tuple[list[RankedChunk], bool]:
        # The span wraps the whole body, fallback branch included: this stage is
        # entered unconditionally once candidates exist, so a reranker that
        # falls back is *reached*, not skipped. Emitting the span only on the
        # success path would exclude the fallback from its own denominator and
        # make a missing span undetectable (§Diseño 1, "Expected spans").
        with span("rag.rerank", **{"rag.top_n": top_n}) as rerank_span:
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
                set_attribute(rerank_span, "rag.fallback_used", True)
                set_attribute(rerank_span, "rag.ranked_count", len(fallback_chunks))
                return fallback_chunks, True

            ordered = sorted(ranked, key=lambda item: item.rank)
            ranked_chunks = [
                RankedChunk(chunk=candidates[item.index], rank=item.rank)
                for item in ordered
            ]
            set_attribute(rerank_span, "rag.fallback_used", False)
            set_attribute(rerank_span, "rag.ranked_count", len(ranked_chunks))
            return ranked_chunks, False

    async def _evaluate(
        self, *, request_id: UUID, query: str, chunks: Sequence[RankedChunk]
    ) -> str | None:
        context = "\n\n".join(ranked.chunk.text for ranked in chunks)
        # Reached only when the evaluator actually triggered -- unlike rerank,
        # this stage is genuinely conditional, so no span is emitted when the
        # caller skipped it.
        with span(
            "rag.evaluate", **{"rag.evaluator_triggered": True}
        ) as evaluate_span:
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
                set_attribute(evaluate_span, "rag.evaluate_outcome", "failed")
                logger.warning(
                    "retrieval_pipeline.evaluator_failed",
                    extra={
                        "event": "retrieval_pipeline.evaluator_failed",
                        "request_id": str(request_id),
                    },
                )
                return None
            verdict = result.content.strip().upper()
            set_attribute(
                evaluate_span,
                "rag.evaluate_outcome",
                "verdict" if verdict else "empty",
            )
            # H4/AC4: the ATTRIBUTE carries the verdict only when it is one of
            # the two words the evaluator was asked for. The previous comment
            # here asserted "A one-word classification (SUFFICIENT /
            # INSUFFICIENT), not content" -- an assumption about a model's
            # output, not a guarantee. Nothing constrained it, so an evaluator
            # that echoed its input (a legitimate provider double did exactly
            # this in independent validation) put the query and passage text
            # into a span attribute. AC4 requires that no attribute VALUE
            # carry query, chunk or message content; allow-listing the key
            # alone cannot enforce that.
            #
            # Only the attribute is constrained. The RETURN value is passed
            # through unchanged: what the pipeline does with an unexpected
            # verdict is abstention behaviour, which §No-alcance excludes from
            # this ORQ.
            set_attribute(
                evaluate_span,
                "rag.evaluator_verdict",
                verdict if verdict in _EVALUATOR_VERDICTS else ("unrecognized" if verdict else None),
            )
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
