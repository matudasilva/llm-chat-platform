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


@dataclass(frozen=True, slots=True)
class RagGenerationContext:
    sources: tuple[RagSource, ...] = ()

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
        except Exception as exc:
            self._log_degraded(request_id=request_id, reason=type(exc).__name__)
            return RagGenerationContext()

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

        return RagGenerationContext(sources=tuple(retained))

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
