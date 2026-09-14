from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .retrieval_pipeline import RetrievalPipeline

logger = logging.getLogger(__name__)

RAG_SCHEMA_VERSION = "rag-generation-v1"


@dataclass(frozen=True, slots=True)
class RagSource:
    citation: str
    document_id: UUID
    chunk_id: UUID
    rank: int
    content: str
    truncated: bool

    def provider_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "document_id": str(self.document_id),
            "chunk_id": str(self.chunk_id),
            "rank": self.rank,
            "truncated": self.truncated,
            "content": self.content,
        }


# AC24's vocabulary, mirroring `memory_outcome`'s shape. `skipped` is set by
# the dependency, the only layer that knows the feature flag.
RETRIEVAL_SKIPPED = "skipped"
RETRIEVAL_OK = "ok"
RETRIEVAL_EMPTY = "empty"
RETRIEVAL_TIMEOUT = "timeout"
RETRIEVAL_ERROR = "error"


@dataclass(frozen=True, slots=True)
class RagGenerationContext:
    sources: tuple[RagSource, ...] = ()
    # AC24: what the retrieval channel DID, distinct from what it produced.
    #
    # `sources` alone cannot say it: an empty tuple is returned by a timeout, by
    # a pipeline error, and by a run that simply matched nothing. Those are
    # three different facts, and the criterion requires this field to be
    # distinguishable from `generation_outcome` and `memory_outcome`.
    #
    # Pure data, no behaviour: `provider_metadata` still depends only on
    # `sources`, so the prompt is byte-identical whatever this holds. The domain
    # SETS it and never reports it -- recording belongs to the dependency
    # boundary, exactly as the memory channel keeps
    # `ConversationHistoryAssembler` free of the collector.
    outcome: str | None = None

    @property
    def provider_metadata(self) -> dict[str, Any] | None:
        if not self.sources:
            return None
        return {
            "rag": {
                "schema_version": RAG_SCHEMA_VERSION,
                "sources": [source.provider_dict() for source in self.sources],
            }
        }


class RagGenerationAugmentor:
    """Build bounded, provider-neutral RAG context for one chat request."""

    def __init__(
        self,
        *,
        pipeline: RetrievalPipeline,
        timeout_s: float,
        max_sources: int,
        max_source_chars: int,
        max_context_chars: int,
    ) -> None:
        self._pipeline = pipeline
        self._timeout_s = timeout_s
        self._max_sources = max_sources
        self._max_source_chars = max_source_chars
        self._max_context_chars = max_context_chars

    async def augment(self, *, request_id: UUID, query: str) -> RagGenerationContext:
        try:
            result = await asyncio.wait_for(
                self._pipeline.retrieve(request_id=request_id, query=query),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError as exc:
            # Classified HERE, where `wait_for` actually observes it. Inferred
            # downstream from an empty result, a timeout would be
            # indistinguishable from a corpus that matched nothing.
            self._log_degraded(request_id=request_id, reason=type(exc).__name__)
            return RagGenerationContext(outcome=RETRIEVAL_TIMEOUT)
        except Exception as exc:
            self._log_degraded(request_id=request_id, reason=type(exc).__name__)
            return RagGenerationContext(outcome=RETRIEVAL_ERROR)

        remaining = self._max_context_chars
        retained: list[RagSource] = []
        for ranked in sorted(result.chunks, key=lambda item: item.rank):
            if len(retained) >= self._max_sources or remaining <= 0:
                break
            original = ranked.chunk.text
            if not original:
                continue
            allowed = min(self._max_source_chars, remaining)
            content = original[:allowed]
            if not content:
                continue
            retained.append(
                RagSource(
                    citation=f"S{len(retained) + 1}",
                    document_id=ranked.chunk.document_id,
                    chunk_id=ranked.chunk.chunk_id,
                    rank=ranked.rank,
                    content=content,
                    truncated=len(content) < len(original),
                )
            )
            remaining -= len(content)

        # `empty` deliberately does NOT separate "matched nothing" from
        # "trimmed to nothing by the budget" (operator decision, 2026-09-13):
        # AC24 does not ask for it, and the distinction would need the pre-trim
        # chunk count surfaced too. A real loss of diagnosis, recorded rather
        # than explained away.
        return RagGenerationContext(
            sources=tuple(retained),
            outcome=RETRIEVAL_OK if retained else RETRIEVAL_EMPTY,
        )

    @staticmethod
    def _log_degraded(*, request_id: UUID, reason: str) -> None:
        try:
            logger.warning(
                "chat_rag.degraded",
                extra={
                    "event": "chat_rag.degraded",
                    "request_id": str(request_id),
                    "reason": reason,
                },
            )
        except Exception:
            pass
