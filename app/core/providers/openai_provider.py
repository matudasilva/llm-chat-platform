from __future__ import annotations

import logging
import time

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.domain.provider import ProviderInput, ProviderPort, ProviderResult
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.utils.retry import RetryPolicy, retry_async

def _map_httpx_exc(exc: Exception, *, provider: str) -> ProviderError:
    """
    Map httpx/network exceptions into a normalized ProviderError.
    Must be safe for client-facing conversion (short, no sensitive payload).
    """
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(
            kind=ProviderErrorKind.timeout,
            message="provider timeout",
        )

    # Network-ish failures are treated as upstream/transient at this stage.
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.NetworkError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.RequestError,
        ),
    ):
        return ProviderError(
            kind=ProviderErrorKind.upstream,
            message="provider upstream error",
        )

    return ProviderError(
        kind=ProviderErrorKind.unknown,
        message="provider unknown error",
    )


def _map_http_status(status_code: int, *, provider: str) -> ProviderError:
    """
    Map HTTP status codes into a normalized ProviderError.
    """
    if status_code in (401, 403):
        return ProviderError(
            kind=ProviderErrorKind.auth,
            message="provider auth failed",
        )

    if status_code == 429:
        return ProviderError(
            kind=ProviderErrorKind.rate_limit,
            message="provider rate limited",
        )

    if 500 <= status_code <= 599:
        return ProviderError(
            kind=ProviderErrorKind.upstream,
            message="provider upstream error",
        )

    # Any other 4xx is treated as unknown for now (we'll refine later if needed).
    if 400 <= status_code <= 499:
        return ProviderError(
            kind=ProviderErrorKind.unknown,
            message="provider request failed",
        )

    return ProviderError(
        kind=ProviderErrorKind.unknown,
        message="provider request failed",
    )


def _should_retry(exc: Exception) -> bool:
    if not isinstance(exc, ProviderError):
        return False
    return exc.kind in (
        ProviderErrorKind.rate_limit,
        ProviderErrorKind.upstream,
        ProviderErrorKind.timeout,
    )

@dataclass(frozen=True)
class OpenAIProviderConfig:
    api_key: str
    model: str
    timeout_s: float
    max_attempts: int = 3
    backoff_base_ms: int = 200
    backoff_max_ms: int = 2000


class OpenAIProvider(ProviderPort):
    def __init__(
        self,
        config: OpenAIProviderConfig,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        base_url: str = "https://api.openai.com",
    ) -> None:
        self._cfg = config
        self._client = http_client
        self._base_url = base_url.rstrip("/")

    async def generate(self, input: ProviderInput) -> ProviderResult:
        logger = logging.getLogger(__name__)
        start = time.monotonic()
        request_id = getattr(input, "request_id", None)
        messages_count = len(input.messages)

        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._cfg.model,
            "input": [
                {
                    "role": m.role,
                    "content": [{"type": "input_text", "text": m.content}],
                }
                for m in input.messages
            ],
        }

        client = self._client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(self._cfg.timeout_s),
        )

        try:
            provider_name = "openai"
            start_total = time.monotonic()

            policy = RetryPolicy(
                max_attempts=max(1, int(self._cfg.max_attempts)),
                base_delay_ms=int(self._cfg.backoff_base_ms),
                max_delay_ms=int(self._cfg.backoff_max_ms),
            )

            async def _op(attempt: int) -> httpx.Response:
                attempt_start = time.monotonic()

                logger.info(
                    "provider.request",
                    extra={
                        "event": "provider.request",
                        "provider": provider_name,
                        "model": self._cfg.model,
                        "request_id": request_id,
                        "messages_count": messages_count,
                        "attempt": attempt,
                        "max_attempts": policy.max_attempts,
                        "timeout_s": self._cfg.timeout_s,
                    },
                )

                try:
                    r = await client.post("/v1/responses", json=payload)
                except Exception as exc:
                    perr = _map_httpx_exc(exc, provider=provider_name)
                    attempt_ms = int((time.monotonic() - attempt_start) * 1000)

                    logger.warning(
                        "provider.error",
                        extra={
                            "event": "provider.error",
                            "provider": provider_name,
                            "model": self._cfg.model,
                            "request_id": request_id,
                            "messages_count": messages_count,
                            "attempt": attempt,
                            "max_attempts": policy.max_attempts,
                            "error_kind": perr.kind,
                            "status_code": None,
                            "latency_ms": attempt_ms,
                            "retryable": perr.kind in (ProviderErrorKind.rate_limit, ProviderErrorKind.upstream, ProviderErrorKind.timeout),
                        },
                    )
                    raise perr from exc

                if r.status_code >= 400:
                    perr = _map_http_status(r.status_code, provider=provider_name)
                    attempt_ms = int((time.monotonic() - attempt_start) * 1000)

                    logger.warning(
                        "provider.error",
                        extra={
                            "event": "provider.error",
                            "provider": provider_name,
                            "model": self._cfg.model,
                            "request_id": request_id,
                            "attempt": attempt,
                            "messages_count": messages_count,
                            "max_attempts": policy.max_attempts,
                            "status_code": r.status_code,
                            "error_kind": perr.kind,
                            "latency_ms": attempt_ms,
                            "retryable": perr.kind in (
                                ProviderErrorKind.rate_limit,
                                ProviderErrorKind.upstream,
                                ProviderErrorKind.timeout,
                            ),
                        },
                    )

                    if attempt < policy.max_attempts and perr.kind in (
                        ProviderErrorKind.rate_limit,
                        ProviderErrorKind.upstream,
                        ProviderErrorKind.timeout,
                    ):
                        logger.info(
                            "provider.retry",
                            extra={
                                "event": "provider.retry",
                                "provider": provider_name,
                                "model": self._cfg.model,
                                "request_id": request_id,
                                "messages_count": messages_count,
                                "attempt": attempt,
                                "next_attempt": attempt + 1,
                                "max_attempts": policy.max_attempts,
                                "error_kind": perr.kind,
                            },
                        )

                    raise perr

                attempt_ms = int((time.monotonic() - attempt_start) * 1000)
                logger.info(
                    "provider.response",
                    extra={
                        "event": "provider.response",
                        "provider": provider_name,
                        "model": self._cfg.model,
                        "request_id": request_id,
                        "messages_count": messages_count,
                        "attempt": attempt,
                        "max_attempts": policy.max_attempts,
                        "status_code": r.status_code,
                        "latency_ms": attempt_ms,
                    },
                )

                return r


            # ✅ retry happens HERE (outside _op)
            r = await retry_async(_op, should_retry=_should_retry, policy=policy)

            total_ms = int((time.monotonic() - start_total) * 1000)
            logger.info(
                "provider.total",
                extra={
                    "event": "provider.total",
                    "provider": provider_name,
                    "model": self._cfg.model,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "max_attempts": policy.max_attempts,
                    "latency_ms": total_ms,
                },
            )

            data = r.json()
            content = _extract_output_text(data)
            usage = data.get("usage") or {}
            latency_ms = int((time.monotonic() - start) * 1000)

            return ProviderResult(
                content=content,
                provider="openai",
                model_version=self._cfg.model,
                prompt_version="v1",
                input_tokens=_safe_int(usage.get("input_tokens")),
                output_tokens=_safe_int(usage.get("output_tokens")),
                total_tokens=_safe_int(usage.get("total_tokens")),
                latency_ms=latency_ms,
            )               

        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                kind=ProviderErrorKind.unknown,
                message="provider unknown error",
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()


def _extract_output_text(data: dict[str, Any]) -> str:
    out = data.get("output") or []
    chunks: list[str] = []
    for item in out:
        if item.get("type") != "message":
            continue
        if item.get("role") != "assistant":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    text = "".join(chunks).strip()
    return text if text else "(empty response)"


def _safe_int(v: Any) -> int | None:
    try:
        return None if v is None else int(v)
    except Exception:
        return None