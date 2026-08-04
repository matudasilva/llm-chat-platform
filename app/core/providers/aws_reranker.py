from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.domain.reranker import (
    RankedDocument,
    RerankerPort,
    RerankRequest,
    TerminalRerankerError,
    TransientRerankerError,
)

_BACKEND = "aws"
_TRANSIENT_CODES = {
    "InternalServerException",
    "ModelNotReadyException",
    "ServiceQuotaExceededException",
    "ServiceUnavailableException",
    "ThrottlingException",
    "TooManyRequestsException",
}


class AwsReranker(RerankerPort):
    def __init__(
        self,
        *,
        region: str = "ca-central-1",
        model: str = "amazon.rerank-v1:0",
        client: Any | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
    ) -> None:
        self._region = region
        self._model = model
        self._client = client
        self._credentials = {
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "aws_session_token": aws_session_token,
        }

    def _build_client(self) -> Any:
        if self._client is not None:
            return self._client
        credentials = {key: value for key, value in self._credentials.items() if value}
        return boto3.client(
            "bedrock-agent-runtime",
            region_name=self._region,
            config=Config(retries={"total_max_attempts": 1, "mode": "standard"}),
            **credentials,
        )

    async def rerank(self, request: RerankRequest) -> list[RankedDocument]:
        top_n = _validate_request(request)
        if not request.documents:
            return []
        model_arn = self._model if self._model.startswith("arn:") else (
            f"arn:aws:bedrock:{self._region}::foundation-model/{self._model}"
        )
        client = self._build_client()
        try:
            response = await asyncio.to_thread(
                client.rerank,
                queries=[{"type": "TEXT", "textQuery": {"text": request.query}}],
                sources=[
                    {
                        "type": "INLINE",
                        "inlineDocumentSource": {
                            "type": "TEXT",
                            "textDocument": {"text": document},
                        },
                    }
                    for document in request.documents
                ],
                rerankingConfiguration={
                    "type": "BEDROCK_RERANKING_MODEL",
                    "bedrockRerankingConfiguration": {
                        "modelConfiguration": {"modelArn": model_arn},
                        "numberOfResults": top_n,
                    },
                },
            )
        except Exception as exc:
            raise _normalize_aws_error(exc) from exc

        try:
            results = [
                RankedDocument(
                    index=int(item["index"]),
                    rank=rank,
                    relevance_score=(
                        float(item["relevanceScore"])
                        if item.get("relevanceScore") is not None
                        else None
                    ),
                )
                for rank, item in enumerate(response["results"], start=1)
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise TerminalRerankerError("AWS reranker response is invalid", backend=_BACKEND) from exc
        if any(result.index < 0 or result.index >= len(request.documents) for result in results):
            raise TerminalRerankerError("AWS reranker returned an invalid document index", backend=_BACKEND)
        return results


def _normalize_aws_error(exc: Exception) -> Exception:
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", "Unknown"))
        error_type = TransientRerankerError if code in _TRANSIENT_CODES else TerminalRerankerError
        return error_type("AWS reranker request failed", backend=_BACKEND, error_code=code)
    if isinstance(exc, BotoCoreError):
        return TransientRerankerError("AWS reranker transport failed", backend=_BACKEND)
    return TerminalRerankerError("AWS reranker failed", backend=_BACKEND)


def _validate_request(request: RerankRequest) -> int:
    if not request.query.strip():
        raise TerminalRerankerError("rerank query must not be empty", backend=_BACKEND)
    if any(not document.strip() for document in request.documents):
        raise TerminalRerankerError("rerank documents must not be empty", backend=_BACKEND)
    top_n = len(request.documents) if request.top_n is None else request.top_n
    if top_n < 0 or top_n > len(request.documents):
        raise TerminalRerankerError("top_n is outside the document range", backend=_BACKEND)
    return top_n
