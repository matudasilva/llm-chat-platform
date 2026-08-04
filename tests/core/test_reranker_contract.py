from __future__ import annotations

from typing import get_type_hints

from app.core.domain.reranker import (
    RankedDocument,
    RerankerPort,
    RerankRequest,
    TerminalRerankerError,
    TransientRerankerError,
)


class _ContractReranker(RerankerPort):
    async def rerank(self, request: RerankRequest) -> list[RankedDocument]:
        return [
            RankedDocument(index=index, rank=rank)
            for rank, index in enumerate(range(len(request.documents)), start=1)
        ][: request.top_n]


async def test_reranker_port_uses_zero_based_indices_and_one_based_ranks() -> None:
    request = RerankRequest(query="query", documents=("first", "second"), top_n=1)

    results = await _ContractReranker().rerank(request)

    assert results == [RankedDocument(index=0, rank=1, relevance_score=None)]


def test_reranker_errors_expose_retryability_without_provider_types() -> None:
    transient = TransientRerankerError("throttled", backend="aws", error_code="ThrottlingException")
    terminal = TerminalRerankerError("denied", backend="aws", error_code="AccessDeniedException")

    assert transient.retryable is True
    assert terminal.retryable is False
    assert str(terminal) == "denied"


def test_reranker_contract_signatures_are_provider_neutral() -> None:
    request_hints = get_type_hints(RerankRequest)
    result_hints = get_type_hints(RankedDocument)

    assert set(request_hints) == {"query", "documents", "top_n"}
    assert set(result_hints) == {"index", "rank", "relevance_score"}
    assert all("boto" not in str(value).lower() for value in (*request_hints.values(), *result_hints.values()))
    assert all("google" not in str(value).lower() for value in (*request_hints.values(), *result_hints.values()))
