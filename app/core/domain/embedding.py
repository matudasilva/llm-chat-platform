from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: Sequence[Sequence[float]]
    model: str
    dimensions: int


class EmbeddingPort(Protocol):
    """
    ORQ-21 / ADR-006 §1: a corpus-level embedding provider, deliberately
    separate from ProviderPort — embeddings have a different shape (batched
    vectors, no streaming, no chat semantics) and are not per-tenant, unlike
    the chat provider.
    """

    async def embed_one(self, text: str) -> Sequence[float]:
        ...

    async def embed_many(self, texts: Sequence[str]) -> EmbeddingResult:
        ...
