from __future__ import annotations

import asyncio
import json
import logging
import time

from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from app.core.domain.provider import (
    ProviderInput,
    ProviderPort,
    ProviderResult,
    ProviderStreamResult,
    ProviderStreamSession,
)
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.utils.retry import RetryPolicy, retry_async


_STREAM_END = object()

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
        client = self._build_client()
        payload = self._build_payload(input)

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
            latency_ms = int((time.monotonic() - start) * 1000)
            return self._build_provider_result(data, latency_ms=latency_ms)

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

    async def stream(self, input: ProviderInput) -> ProviderStreamSession:
        logger = logging.getLogger(__name__)
        start = time.monotonic()
        request_id = getattr(input, "request_id", None)
        messages_count = len(input.messages)
        client = self._build_client()
        payload = self._build_payload(input)
        payload["stream"] = True

        stream_context = client.stream("POST", "/v1/responses", json=payload)
        response = None

        try:
            logger.info(
                "provider.request",
                extra={
                    "event": "provider.request",
                    "provider": "openai",
                    "model": self._cfg.model,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "stream": True,
                    "timeout_s": self._cfg.timeout_s,
                },
            )
            response = await stream_context.__aenter__()

            if response.status_code >= 400:
                perr = _map_http_status(response.status_code, provider="openai")
                latency_ms = int((time.monotonic() - start) * 1000)
                logger.warning(
                    "provider.error",
                    extra={
                        "event": "provider.error",
                        "provider": "openai",
                        "model": self._cfg.model,
                        "request_id": request_id,
                        "messages_count": messages_count,
                        "status_code": response.status_code,
                        "error_kind": perr.kind,
                        "latency_ms": latency_ms,
                        "stream": True,
                        "retryable": perr.kind in (
                            ProviderErrorKind.rate_limit,
                            ProviderErrorKind.upstream,
                            ProviderErrorKind.timeout,
                        ),
                    },
                )
                raise perr

            logger.info(
                "provider.response",
                extra={
                    "event": "provider.response",
                    "provider": "openai",
                    "model": self._cfg.model,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "status_code": response.status_code,
                    "stream": True,
                },
            )
        except ProviderError:
            await _close_stream_context(stream_context, self._client is None, client)
            raise
        except Exception as exc:
            await _close_stream_context(stream_context, self._client is None, client)
            if isinstance(exc, httpx.HTTPError):
                raise _map_httpx_exc(exc, provider="openai") from exc
            raise ProviderError(
                kind=ProviderErrorKind.unknown,
                message="provider unknown error",
            ) from exc

        queue: asyncio.Queue[object] = asyncio.Queue()
        state = _OpenAIStreamState(queue=queue)

        consume_task = asyncio.create_task(
            self._consume_stream(
                response=response,
                stream_context=stream_context,
                client=client,
                close_client=self._client is None,
                state=state,
                start=start,
                request_id=request_id,
                messages_count=messages_count,
            )
        )

        async def chunk_iterator() -> AsyncIterator[str]:
            while True:
                item = await queue.get()
                if item is _STREAM_END:
                    break
                yield str(item)

        async def get_final_result() -> ProviderStreamResult:
            await consume_task
            if state.error is not None:
                raise state.error
            if state.final_result is None:
                raise ProviderError(
                    kind=ProviderErrorKind.unknown,
                    message="provider stream incomplete",
                )
            return state.final_result

        return ProviderStreamSession(
            chunks=chunk_iterator(),
            get_final_result=get_final_result,
        )

    def _build_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._cfg.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self._cfg.timeout_s),
        )

    def _build_payload(self, input: ProviderInput) -> dict[str, Any]:
        return {
            "model": self._cfg.model,
            "input": [
                {
                    "role": m.role,
                    "content": [{"type": "input_text", "text": m.content}],
                }
                for m in input.messages
            ],
        }

    def _build_provider_result(self, data: dict[str, Any], *, latency_ms: int) -> ProviderResult:
        usage = data.get("usage") or {}
        input_tokens = _safe_int(usage.get("input_tokens"))
        output_tokens = _safe_int(usage.get("output_tokens"))
        total_tokens = _safe_int(usage.get("total_tokens"))

        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

        return ProviderResult(
            content=_extract_output_text(data),
            provider="openai",
            model_version=_extract_model_version(data, default=self._cfg.model),
            prompt_version=_extract_prompt_version(data),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )

    async def _consume_stream(
        self,
        *,
        response: httpx.Response,
        stream_context: Any,
        client: httpx.AsyncClient,
        close_client: bool,
        state: "_OpenAIStreamState",
        start: float,
        request_id: Any,
        messages_count: int,
    ) -> None:
        logger = logging.getLogger(__name__)
        content_parts: list[str] = []
        final_response_payload: dict[str, Any] | None = None

        try:
            async for event_name, payload in _iter_sse_events(response):
                delta = _extract_stream_delta(event_name, payload)
                if delta:
                    content_parts.append(delta)
                    await state.queue.put(delta)

                response_payload = _extract_stream_response_payload(event_name, payload)
                if response_payload is not None:
                    final_response_payload = response_payload

            latency_ms = int((time.monotonic() - start) * 1000)
            final_payload = final_response_payload or {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "".join(content_parts)}],
                    }
                ],
                "model": self._cfg.model,
            }
            provider_result = self._build_provider_result(final_payload, latency_ms=latency_ms)
            content = "".join(content_parts) or provider_result.content
            state.final_result = ProviderStreamResult(
                content=content,
                provider_result=ProviderResult(
                    content=content,
                    provider=provider_result.provider,
                    model_version=provider_result.model_version,
                    prompt_version=provider_result.prompt_version,
                    input_tokens=provider_result.input_tokens,
                    output_tokens=provider_result.output_tokens,
                    total_tokens=provider_result.total_tokens,
                    latency_ms=provider_result.latency_ms,
                    raw=provider_result.raw,
                ),
            )
            logger.info(
                "provider.stream.complete",
                extra={
                    "event": "provider.stream.complete",
                    "provider": "openai",
                    "model": state.final_result.provider_result.model_version,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "latency_ms": latency_ms,
                    "stream": True,
                    "has_usage": any(
                        value is not None
                        for value in (
                            state.final_result.provider_result.input_tokens,
                            state.final_result.provider_result.output_tokens,
                            state.final_result.provider_result.total_tokens,
                        )
                    ),
                },
            )
        except Exception as exc:
            error = exc if isinstance(exc, ProviderError) else _normalize_stream_error(exc)
            state.error = error
            logger.warning(
                "provider.stream.error",
                extra={
                    "event": "provider.stream.error",
                    "provider": "openai",
                    "model": self._cfg.model,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "latency_ms": int((time.monotonic() - start) * 1000),
                    "stream": True,
                    "error_kind": getattr(error, "kind", ProviderErrorKind.unknown),
                },
            )
        finally:
            await state.queue.put(_STREAM_END)
            await _close_stream_context(stream_context, close_client, client)


@dataclass(slots=True)
class _OpenAIStreamState:
    queue: asyncio.Queue[object]
    final_result: ProviderStreamResult | None = None
    error: ProviderError | None = None


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


async def _iter_sse_events(response: httpx.Response) -> AsyncIterator[tuple[str | None, dict[str, Any]]]:
    event_name: str | None = None
    data_lines: list[str] = []

    async for raw_line in response.aiter_lines():
        line = raw_line.strip()

        if not line:
            event = _parse_sse_event(event_name, data_lines)
            if event is not None:
                yield event
            event_name = None
            data_lines = []
            continue

        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip() or None
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())

    event = _parse_sse_event(event_name, data_lines)
    if event is not None:
        yield event


def _parse_sse_event(event_name: str | None, data_lines: list[str]) -> tuple[str | None, dict[str, Any]] | None:
    if not data_lines:
        return None

    raw_data = "\n".join(data_lines).strip()
    if not raw_data or raw_data == "[DONE]":
        return None

    payload = json.loads(raw_data)
    return event_name, payload


def _extract_stream_delta(event_name: str | None, payload: dict[str, Any]) -> str:
    event_type = event_name or payload.get("type")

    if event_type == "response.output_text.delta":
        delta = payload.get("delta")
        return delta if isinstance(delta, str) else ""

    return ""


def _extract_stream_response_payload(event_name: str | None, payload: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event_name or payload.get("type")
    if event_type == "response.completed":
        response = payload.get("response")
        return response if isinstance(response, dict) else None
    return None


def _extract_model_version(data: dict[str, Any], *, default: str) -> str:
    model = data.get("model")
    return model if isinstance(model, str) and model else default


def _extract_prompt_version(data: dict[str, Any]) -> str:
    prompt_version = data.get("prompt_version")
    if isinstance(prompt_version, str) and prompt_version:
        return prompt_version
    return "v1"


def _normalize_stream_error(exc: Exception) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, httpx.HTTPError):
        return _map_httpx_exc(exc, provider="openai")
    if isinstance(exc, json.JSONDecodeError):
        return ProviderError(
            kind=ProviderErrorKind.unknown,
            message="provider stream parse error",
        )
    return ProviderError(
        kind=ProviderErrorKind.unknown,
        message="provider unknown error",
    )


async def _close_stream_context(
    stream_context: Any,
    close_client: bool,
    client: httpx.AsyncClient,
) -> None:
    try:
        await stream_context.__aexit__(None, None, None)
    finally:
        if close_client:
            await client.aclose()
