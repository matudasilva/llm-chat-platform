from __future__ import annotations

import asyncio
import codecs
import json
import math
import re
import time
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from app.core.domain.provider import ProviderInput, ProviderResult, ProviderStreamResult, ProviderStreamSession
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind, is_retryable
from app.core.domain.provider_prompt import messages_for_provider
from app.core.utils.retry import RetryPolicy, compute_backoff_ms, retry_async


@dataclass(frozen=True)
class VertexProviderConfig:
    project_id: str
    location: str
    model: str
    max_output_tokens: int
    timeout_s: float
    prompt_version: str = "v1"
    max_attempts: int = 3
    backoff_base_ms: int = 200
    backoff_max_ms: int = 2000


# Deliberately explicit: no user-supplied host or automatic location failover.
_REGIONS = frozenset({
    "us-central1", "us-east1", "us-east4", "us-east5", "us-south1", "us-west1", "us-west4",
    "northamerica-northeast1", "northamerica-northeast2", "southamerica-east1", "southamerica-west1",
    "europe-central2", "europe-north1", "europe-southwest1", "europe-west1", "europe-west2",
    "europe-west3", "europe-west4", "europe-west6", "europe-west8", "europe-west9", "europe-west12",
    "asia-east1", "asia-east2", "asia-northeast1", "asia-northeast3", "asia-south1", "asia-southeast1",
    "asia-southeast2", "australia-southeast1", "australia-southeast2", "me-central1", "me-central2",
    "me-west1", "africa-south1",
})


def _error(kind: ProviderErrorKind, *, status: int | None = None, retryable: bool = False) -> ProviderError:
    return ProviderError(kind=kind, message=f"provider {kind.value} error", provider="vertex", http_status=status, retryable=retryable)


def _status_error(status: int) -> ProviderError:
    if status in (401, 403):
        return _error(ProviderErrorKind.auth, status=status)
    if status == 429:
        return _error(ProviderErrorKind.rate_limit, status=status, retryable=True)
    if status in (500, 502, 503, 504):
        return _error(ProviderErrorKind.upstream, status=status, retryable=True)
    if 400 <= status < 500:
        return _error(ProviderErrorKind.bad_request, status=status)
    return _error(ProviderErrorKind.upstream, status=status)


def _exception(exc: Exception) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return _error(ProviderErrorKind.timeout, retryable=True)
    if isinstance(exc, httpx.RequestError):
        return _error(ProviderErrorKind.network, retryable=True)
    return _error(ProviderErrorKind.unknown)


def _payload(input: ProviderInput, cfg: VertexProviderConfig) -> dict[str, Any]:
    if input.temperature is not None or (input.max_tokens is not None and input.max_tokens <= 0):
        raise _error(ProviderErrorKind.bad_request)
    system, contents = [], []
    for msg in messages_for_provider(input):
        if msg.role == "system":
            if contents:
                raise _error(ProviderErrorKind.bad_request)
            system.append({"text": msg.content})
        elif msg.role in ("user", "assistant"):
            contents.append({"role": "user" if msg.role == "user" else "model", "parts": [{"text": msg.content}]})
        else:
            raise _error(ProviderErrorKind.bad_request)
    if not contents:
        raise _error(ProviderErrorKind.bad_request)
    result: dict[str, Any] = {"contents": contents, "generationConfig": {"maxOutputTokens": min(cfg.max_output_tokens, input.max_tokens or cfg.max_output_tokens), "candidateCount": 1}}
    if system:
        result["systemInstruction"] = {"parts": system}
    return result


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


_monotonic = time.monotonic


class _Accumulator:
    def __init__(self, cfg: VertexProviderConfig, *, started: float | None = None):
        self.cfg = cfg
        self.parts: list[str] = []
        self.finish = False
        self.usage: dict[str, Any] = {}
        self.model = cfg.model
        self.model_source = "configured"
        self.started = _monotonic() if started is None else started

    def consume(self, data: Any) -> str:
        if not isinstance(data, dict) or "error" in data:
            raise _error(ProviderErrorKind.unknown)
        feedback = data.get("promptFeedback")
        if feedback is not None and (not isinstance(feedback, dict) or feedback.get("blockReason")):
            raise _error(ProviderErrorKind.bad_request)
        usage = data.get("usageMetadata")
        if usage is not None:
            if not isinstance(usage, dict):
                raise _error(ProviderErrorKind.unknown)
            self.usage = usage
        if isinstance(data.get("modelVersion"), str) and data["modelVersion"]:
            self.model = data["modelVersion"]
            self.model_source = "provider"
        candidates = data.get("candidates", [])
        if not isinstance(candidates, list) or len(candidates) > 1:
            raise _error(ProviderErrorKind.unknown)
        if not candidates:
            if not usage and not feedback:
                raise _error(ProviderErrorKind.unknown)
            return ""
        candidate = candidates[0]
        if not isinstance(candidate, dict) or candidate.get("index", 0) != 0 or self.finish:
            raise _error(ProviderErrorKind.unknown)
        reason = candidate.get("finishReason")
        if reason is not None:
            if reason not in ("STOP", "MAX_TOKENS"):
                raise _error(ProviderErrorKind.bad_request)
            self.finish = True
        content = candidate.get("content", {})
        if not isinstance(content, dict) or not isinstance(content.get("parts", []), list):
            raise _error(ProviderErrorKind.unknown)
        visible = []
        for part in content.get("parts", []):
            if not isinstance(part, dict):
                raise _error(ProviderErrorKind.unknown)
            if part.get("thought") is True or any(k in part for k in ("functionCall", "functionResponse", "executableCode", "codeExecutionResult", "inlineData", "fileData")):
                continue
            if "text" in part:
                if not isinstance(part["text"], str):
                    raise _error(ProviderErrorKind.unknown)
                visible.append(part["text"])
        text = "".join(visible)
        self.parts.append(text)
        return text

    def result(self) -> ProviderResult:
        content = "".join(self.parts)
        if not self.finish or not content:
            raise _error(ProviderErrorKind.unknown)
        inp = _count(self.usage.get("promptTokenCount"))
        output = _count(self.usage.get("candidatesTokenCount"))
        thoughts = _count(self.usage.get("thoughtsTokenCount"))
        # A missing thoughts counter does not prove there were no billable thoughts.
        # Prefer the provider's total; output is known only when thought usage is explicit.
        output = output + thoughts if output is not None and thoughts is not None else None
        return ProviderResult(content=content, provider="vertex", model_version=self.model,
                              prompt_version=self.cfg.prompt_version, input_tokens=inp,
                              output_tokens=output, total_tokens=_count(self.usage.get("totalTokenCount")),
                              latency_ms=max(0, int((_monotonic() - self.started) * 1000)),
                              raw={"model_version_source": self.model_source})


class VertexProvider:
    def __init__(self, cfg: VertexProviderConfig, *, http_client: httpx.AsyncClient | None = None,
                 access_token_provider: Callable[[], Awaitable[str]] | None = None):
        try:
            valid_timeout = (type(cfg.timeout_s) in (int, float) and
                             math.isfinite(cfg.timeout_s) and cfg.timeout_s > 0)
        except (OverflowError, TypeError):
            valid_timeout = False
        if (not isinstance(cfg.project_id, str) or
            not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", cfg.project_id) or
            not isinstance(cfg.model, str) or
            not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", cfg.model) or
            not isinstance(cfg.location, str) or cfg.location not in _REGIONS | {"global", "us", "eu"} or
            type(cfg.max_output_tokens) is not int or cfg.max_output_tokens <= 0 or
            not valid_timeout or
            type(cfg.max_attempts) is not int or not 1 <= cfg.max_attempts <= 5 or
            type(cfg.backoff_base_ms) is not int or not 0 <= cfg.backoff_base_ms <= 60000 or
            type(cfg.backoff_max_ms) is not int or not 0 <= cfg.backoff_max_ms <= 60000 or
            cfg.backoff_max_ms < cfg.backoff_base_ms):
            raise _error(ProviderErrorKind.bad_request)
        self.cfg, self.client, self.token_provider = cfg, http_client, access_token_provider
        host = "aiplatform.googleapis.com" if cfg.location == "global" else (f"aiplatform.{cfg.location}.rep.googleapis.com" if cfg.location in ("us", "eu") else f"{cfg.location}-aiplatform.googleapis.com")
        self.url = f"https://{host}/v1/projects/{cfg.project_id}/locations/{cfg.location}/publishers/google/models/{cfg.model}"
        self.policy = RetryPolicy(cfg.max_attempts, cfg.backoff_base_ms, cfg.backoff_max_ms)

    async def _token(self) -> str:
        try:
            if self.token_provider is None:
                from app.core.providers.google_adc import GoogleAdcAccessTokenProvider
                self.token_provider = GoogleAdcAccessTokenProvider(timeout_s=self.cfg.timeout_s)
            token = await self.token_provider()
            if not isinstance(token, str) or not token:
                raise ValueError("empty token")
            return token
        except ProviderError as exc:
            raise _error(exc.kind, status=exc.http_status, retryable=exc.retryable) from None
        except Exception:
            raise _error(ProviderErrorKind.auth) from None

    async def generate(self, input: ProviderInput) -> ProviderResult:
        payload = _payload(input, self.cfg)
        # Include all attempts, authentication, request time and retry backoff.
        started = _monotonic()
        async def op(_: int) -> ProviderResult:
            try:
                token = await self._token()
                async with _client(self.client, self.cfg.timeout_s) as client:
                    response = await client.post(self.url + ":generateContent", json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=self.cfg.timeout_s)
                    if response.status_code != 200:
                        raise _status_error(response.status_code)
                    data = response.json()
                acc = _Accumulator(self.cfg, started=started)
                acc.consume(data)
                return acc.result()
            except Exception as exc:
                raise _exception(exc) from None
        return await retry_async(op, should_retry=is_retryable, policy=self.policy)

    async def stream(self, input: ProviderInput) -> ProviderStreamSession:
        iterator = _VertexStream(self, _payload(input, self.cfg))
        return ProviderStreamSession(chunks=iterator, get_final_result=iterator.final)


class _client:
    def __init__(self, client: httpx.AsyncClient | None, timeout: float):
        self.client, self.owned = client or httpx.AsyncClient(timeout=timeout), client is None
    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client
    async def __aexit__(self, *args: Any) -> None:
        if self.owned:
            await self.client.aclose()


async def _events(response: httpx.Response) -> AsyncIterator[Any]:
    lines: list[str] = []
    buffer = ""
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    try:
        async with aclosing(response.aiter_raw()) as source:
            async for chunk in source:
                buffer += decoder.decode(chunk)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.removesuffix("\r")
                    if not line:
                        if lines:
                            try:
                                yield json.loads("\n".join(lines))
                            except (ValueError, TypeError):
                                raise _error(ProviderErrorKind.unknown) from None
                            lines = []
                    elif not line.startswith(":"):
                        field, _, value = line.partition(":")
                        if field == "data":
                            lines.append(value[1:] if value.startswith(" ") else value)
            buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise _error(ProviderErrorKind.unknown) from None
    if buffer or lines:
        raise _error(ProviderErrorKind.unknown)


class _VertexStream:
    def __init__(self, provider: VertexProvider, payload: dict[str, Any]):
        self.provider, self.payload = provider, payload
        self.done = asyncio.Event()
        self.result_value: ProviderStreamResult | None = None
        self.failure: BaseException | None = None
        self.closed = False
        self.puller: asyncio.Task[Any] | None = None
        self.driver = self._run()
        self.cleanup_task: asyncio.Task[None] | None = None

    def __aiter__(self) -> _VertexStream:
        return self

    async def __anext__(self) -> str:
        if self.closed:
            raise StopAsyncIteration
        self.puller = asyncio.current_task()
        try:
            return await anext(self.driver)
        finally:
            self.puller = None

    async def _run(self) -> AsyncIterator[str]:
        p = self.provider
        emitted = False
        try:
            for attempt in range(1, p.cfg.max_attempts + 1):
                acc = _Accumulator(p.cfg)
                try:
                    token = await p._token()
                    async with _client(p.client, p.cfg.timeout_s) as client:
                        async with client.stream("POST", p.url + ":streamGenerateContent?alt=sse", json=self.payload,
                                                 headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"}, timeout=p.cfg.timeout_s) as response:
                            if response.status_code != 200:
                                raise _status_error(response.status_code)
                            if response.headers.get("content-encoding", "identity").lower() != "identity":
                                raise _error(ProviderErrorKind.unknown)
                            async with aclosing(_events(response)) as events:
                                async for data in events:
                                    text = acc.consume(data)
                                    if text:
                                        emitted = True
                                        yield text
                    result = acc.result()
                    self.result_value = ProviderStreamResult(content=result.content, provider_result=result)
                    return
                except Exception as exc:
                    error = _exception(exc)
                    if emitted or not error.retryable or attempt == p.cfg.max_attempts:
                        raise error from None
                    delay = compute_backoff_ms(attempt=attempt, base_delay_ms=p.policy.base_delay_ms, max_delay_ms=p.policy.max_delay_ms)
                    await asyncio.sleep(delay / 1000)
        except asyncio.CancelledError as exc:
            self.failure = exc
            raise
        except Exception as exc:
            self.failure = _exception(exc)
            raise self.failure from None
        finally:
            self.done.set()

    async def aclose(self) -> None:
        if self.cleanup_task is None:
            self.closed = True
            if not self.done.is_set():
                self.failure = self.failure or asyncio.CancelledError()
            self.cleanup_task = asyncio.create_task(self._cleanup())
        # The resource owner must survive cancellation of any individual closer.
        await asyncio.shield(self.cleanup_task)

    async def _cleanup(self) -> None:
        try:
            task = self.puller
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            await self.driver.aclose()
        except Exception as exc:
            if self.failure is None:
                self.failure = _exception(exc)
        finally:
            self.done.set()

    async def final(self) -> ProviderStreamResult:
        await self.done.wait()
        if self.failure is not None:
            raise self.failure
        if self.result_value is None:
            raise _error(ProviderErrorKind.unknown)
        return self.result_value
