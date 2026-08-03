from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Sequence

import httpx

from app.core.domain.embedding import EmbeddingPort, EmbeddingResult
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.utils.retry import RetryPolicy, retry_async

logger = logging.getLogger(__name__)


def _map_httpx_exc(exc: Exception) -> ProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(kind=ProviderErrorKind.timeout, message="embedding provider timeout", provider="openai")
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.ReadError, httpx.RemoteProtocolError, httpx.RequestError)):
        return ProviderError(kind=ProviderErrorKind.upstream, message="embedding provider upstream error", provider="openai")
    return ProviderError(kind=ProviderErrorKind.unknown, message="embedding provider unknown error", provider="openai")


def _map_http_status(status_code: int) -> ProviderError:
    if status_code == 400:
        return ProviderError(kind=ProviderErrorKind.bad_request, message="embedding request failed", provider="openai", http_status=status_code)
    if status_code in (401, 403):
        return ProviderError(kind=ProviderErrorKind.auth, message="embedding auth failed", provider="openai", http_status=status_code)
    if status_code == 429:
        return ProviderError(kind=ProviderErrorKind.rate_limit, message="embedding provider rate limited", provider="openai", http_status=status_code, retryable=True)
    if 500 <= status_code <= 599:
        return ProviderError(kind=ProviderErrorKind.upstream, message="embedding provider upstream error", provider="openai", http_status=status_code, retryable=True)
    return ProviderError(kind=ProviderErrorKind.unknown, message="embedding request failed", provider="openai", http_status=status_code)


def _should_retry(exc: Exception) -> bool:
    return isinstance(exc, ProviderError) and exc.kind in (
        ProviderErrorKind.rate_limit,
        ProviderErrorKind.upstream,
        ProviderErrorKind.timeout,
    )


@dataclass(frozen=True)
class OpenAIEmbeddingConfig:
    api_key: str
    # ADR-006 §1: corpus-level constant, not per tenant.
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    timeout_s: float = 30.0
    max_attempts: int = 3
    backoff_base_ms: int = 200
    backoff_max_ms: int = 2000


class OpenAIEmbeddingProvider(EmbeddingPort):
    def __init__(
        self,
        config: OpenAIEmbeddingConfig,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        base_url: str = "https://api.openai.com",
    ) -> None:
        self._cfg = config
        self._client = http_client
        self._base_url = base_url.rstrip("/")

    def _build_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._cfg.timeout_s,
            headers={"Authorization": f"Bearer {self._cfg.api_key}"},
        )

    async def embed_one(self, text: str) -> Sequence[float]:
        result = await self.embed_many([text])
        return result.vectors[0]

    async def embed_many(self, texts: Sequence[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], model=self._cfg.model, dimensions=self._cfg.dimensions)

        client = self._build_client()
        payload = {
            "model": self._cfg.model,
            "input": list(texts),
            "dimensions": self._cfg.dimensions,
        }
        policy = RetryPolicy(
            max_attempts=max(1, int(self._cfg.max_attempts)),
            base_delay_ms=int(self._cfg.backoff_base_ms),
            max_delay_ms=int(self._cfg.backoff_max_ms),
        )

        async def _op(attempt: int) -> httpx.Response:
            start = time.monotonic()
            try:
                response = await client.post("/v1/embeddings", json=payload)
            except Exception as exc:
                perr = _map_httpx_exc(exc)
                logger.warning(
                    "embedding.error",
                    extra={
                        "event": "embedding.error",
                        "provider": "openai",
                        "model": self._cfg.model,
                        "attempt": attempt,
                        "error_kind": perr.kind,
                        "latency_ms": int((time.monotonic() - start) * 1000),
                    },
                )
                raise perr from exc
            if response.status_code >= 400:
                perr = _map_http_status(response.status_code)
                logger.warning(
                    "embedding.error",
                    extra={
                        "event": "embedding.error",
                        "provider": "openai",
                        "model": self._cfg.model,
                        "attempt": attempt,
                        "status_code": response.status_code,
                        "error_kind": perr.kind,
                        "latency_ms": int((time.monotonic() - start) * 1000),
                    },
                )
                raise perr
            return response

        try:
            response = await retry_async(_op, should_retry=_should_retry, policy=policy)
        finally:
            if self._client is None:
                await client.aclose()

        body = response.json()
        vectors = [item["embedding"] for item in body["data"]]
        return EmbeddingResult(vectors=vectors, model=self._cfg.model, dimensions=self._cfg.dimensions)
