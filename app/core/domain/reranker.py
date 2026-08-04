from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class RerankRequest:
    """Provider-neutral reranking input.

    Result indices refer to the zero-based position of each document in
    ``documents``. Adapters must not use provider-specific identifiers in this
    contract.
    """

    query: str
    documents: Sequence[str]
    top_n: int | None = None


@dataclass(frozen=True, slots=True)
class RankedDocument:
    """Normalized reranking result ordered by authoritative one-based rank."""

    index: int
    rank: int
    relevance_score: float | None = None


class RerankerError(Exception):
    """Safe, normalized failure raised by a reranker adapter."""

    retryable = False

    def __init__(
        self,
        message: str,
        *,
        backend: str,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.backend = backend
        self.error_code = error_code

    def __str__(self) -> str:
        return self.message


class TransientRerankerError(RerankerError):
    """Transport, throttling, or upstream 5xx failure that may be retried."""

    retryable = True


class TerminalRerankerError(RerankerError):
    """Authentication, payload, or configuration failure that must not retry."""


class RerankerPort(Protocol):
    """Provider-agnostic contract for isolated reranking backends."""

    async def rerank(self, request: RerankRequest) -> Sequence[RankedDocument]:
        ...
