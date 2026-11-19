from __future__ import annotations

import asyncio
import logging
import time
import queue as sync_queue
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.core.domain.provider import (
    ProviderInput,
    ProviderPort,
    ProviderResult,
    ProviderStreamResult,
    ProviderStreamSession,
)
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.domain.provider_prompt import messages_for_provider
from app.core.utils.retry import RetryPolicy, retry_async
from app.core.observability.retry_evidence import announce


_STREAM_END = object()


def _should_retry(exc: Exception) -> bool:
    return isinstance(exc, ProviderError) and exc.retryable


@dataclass(frozen=True)
class BedrockProviderConfig:
    region: str
    model: str
    timeout_s: float
    prompt_version: str = "v1"
    max_attempts: int = 3
    backoff_base_ms: int = 200
    backoff_max_ms: int = 2000
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None


class BedrockProvider(ProviderPort):
    def __init__(self, config: BedrockProviderConfig, *, runtime_client: Any | None = None) -> None:
        self._cfg = config
        self._runtime_client = runtime_client

    async def generate(self, input: ProviderInput) -> ProviderResult:
        logger = logging.getLogger(__name__)
        request_id = getattr(input, "request_id", None)
        messages_count = len(input.messages)
        client = self._build_client()
        payload = _build_payload(input=input, model=self._cfg.model)
        start = time.monotonic()

        policy = RetryPolicy(
            max_attempts=max(1, int(self._cfg.max_attempts)),
            base_delay_ms=int(self._cfg.backoff_base_ms),
            max_delay_ms=int(self._cfg.backoff_max_ms),
        )

        try:
            start_total = time.monotonic()
            attempts_used = 0

            async def _op(attempt: int) -> dict[str, Any]:
                attempt_start = time.monotonic()
                nonlocal attempts_used
                attempts_used = attempt
                logger.info(
                    "provider.request",
                    extra={
                        "event": "provider.request",
                        "provider": "bedrock",
                        "model": self._cfg.model,
                        "request_id": request_id,
                        "messages_count": messages_count,
                        "attempt": attempt,
                        "max_attempts": policy.max_attempts,
                        "timeout_s": self._cfg.timeout_s,
                    },
                )
                try:
                    response = await self._call_client(client.converse, **payload)
                except Exception as exc:
                    perr = _map_bedrock_exc(exc)
                    attempt_ms = int((time.monotonic() - attempt_start) * 1000)
                    logger.warning(
                        "provider.error",
                        extra={
                            "event": "provider.error",
                            "provider": "bedrock",
                            "model": self._cfg.model,
                            "request_id": request_id,
                            "messages_count": messages_count,
                            "attempt": attempt,
                            "max_attempts": policy.max_attempts,
                            "error_kind": perr.kind,
                            "failure_kind": perr.kind,
                            "status_code": perr.http_status,
                            "latency_ms": attempt_ms,
                            "retryable": perr.retryable,
                        },
                    )
                    if attempt < policy.max_attempts and perr.retryable:
                        announce()
                        logger.info(
                            "provider.retry",
                            extra={
                                "event": "provider.retry",
                                "provider": "bedrock",
                                "model": self._cfg.model,
                                "request_id": request_id,
                                "messages_count": messages_count,
                                "attempt": attempt,
                                "next_attempt": attempt + 1,
                                "max_attempts": policy.max_attempts,
                                "error_kind": perr.kind,
                            },
                        )
                    # Upstream messages can echo prompt content. Preserve the
                    # normalized code/status, but suppress the raw exception
                    # chain so tenant corpus text cannot reach traceback logs.
                    raise perr from None

                attempt_ms = int((time.monotonic() - attempt_start) * 1000)
                logger.info(
                    "provider.response",
                    extra={
                        "event": "provider.response",
                        "provider": "bedrock",
                        "model": self._cfg.model,
                        "request_id": request_id,
                        "messages_count": messages_count,
                        "attempt": attempt,
                        "max_attempts": policy.max_attempts,
                        "status_code": 200,
                        "latency_ms": attempt_ms,
                    },
                )
                return response

            response = await retry_async(_op, should_retry=_should_retry, policy=policy)
            logger.info(
                "provider.total",
                extra={
                    "event": "provider.total",
                    "provider": "bedrock",
                    "model": self._cfg.model,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "max_attempts": policy.max_attempts,
                    "attempts_used": attempts_used,
                    "final_provider": "bedrock",
                    "fallback_used": False,
                    "latency_ms": int((time.monotonic() - start_total) * 1000),
                },
            )

            return _build_provider_result(
                response,
                default_model=self._cfg.model,
                prompt_version=self._cfg.prompt_version,
                latency_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            await _close_client_if_needed(self._runtime_client is None, client)

    async def stream(self, input: ProviderInput) -> ProviderStreamSession:
        logger = logging.getLogger(__name__)
        request_id = getattr(input, "request_id", None)
        messages_count = len(input.messages)
        client = self._build_client()
        payload = _build_payload(input=input, model=self._cfg.model)
        start = time.monotonic()

        policy = RetryPolicy(
            max_attempts=max(1, int(self._cfg.max_attempts)),
            base_delay_ms=int(self._cfg.backoff_base_ms),
            max_delay_ms=int(self._cfg.backoff_max_ms),
        )

        if self._runtime_client is not None:
            logger.info(
                "provider.request",
                extra={
                    "event": "provider.request",
                    "provider": "bedrock",
                    "model": self._cfg.model,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "attempt": 1,
                    "max_attempts": 1,
                    "stream": True,
                    "timeout_s": self._cfg.timeout_s,
                },
            )
            try:
                response = client.converse_stream(**payload)
            except Exception as exc:
                perr = _map_bedrock_exc(exc)
                logger.warning(
                    "provider.error",
                    extra={
                        "event": "provider.error",
                        "provider": "bedrock",
                        "model": self._cfg.model,
                        "request_id": request_id,
                        "messages_count": messages_count,
                        "attempt": 1,
                        "max_attempts": 1,
                        "error_kind": perr.kind,
                        "failure_kind": perr.kind,
                        "status_code": perr.http_status,
                        "stream": True,
                        "retryable": perr.retryable,
                    },
                )
                raise perr from None
            logger.info(
                "provider.response",
                extra={
                    "event": "provider.response",
                    "provider": "bedrock",
                    "model": self._cfg.model,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "attempt": 1,
                    "max_attempts": 1,
                    "status_code": 200,
                    "stream": True,
                },
            )
            return _build_inline_stream_session(
                response=response,
                model=self._cfg.model,
                prompt_version=self._cfg.prompt_version,
                start=start,
                request_id=request_id,
                messages_count=messages_count,
            )

        acquisition_abandoned = False
        try:
            async def _op(attempt: int) -> dict[str, Any]:
                attempt_start = time.monotonic()
                logger.info(
                    "provider.request",
                    extra={
                        "event": "provider.request",
                        "provider": "bedrock",
                        "model": self._cfg.model,
                        "request_id": request_id,
                        "messages_count": messages_count,
                        "attempt": attempt,
                        "max_attempts": policy.max_attempts,
                        "stream": True,
                        "timeout_s": self._cfg.timeout_s,
                    },
                )
                try:
                    nonlocal acquisition_abandoned
                    acquisition = asyncio.create_task(asyncio.to_thread(client.converse_stream, **payload))
                    try:
                        response = await asyncio.shield(acquisition)
                    except asyncio.CancelledError:
                        acquisition_abandoned = True
                        async def cleanup_acquisition():
                            try:
                                late_response = await acquisition
                                await _close_event_stream(late_response)
                            except BaseException:
                                pass
                            finally:
                                try:
                                    await _close_client_if_needed(True, client)
                                except Exception:
                                    pass
                        task = asyncio.create_task(cleanup_acquisition())
                        task.add_done_callback(_observe_task)
                        raise
                except Exception as exc:
                    perr = _map_bedrock_exc(exc)
                    attempt_ms = int((time.monotonic() - attempt_start) * 1000)
                    logger.warning(
                        "provider.error",
                        extra={
                            "event": "provider.error",
                            "provider": "bedrock",
                            "model": self._cfg.model,
                            "request_id": request_id,
                            "messages_count": messages_count,
                            "attempt": attempt,
                            "max_attempts": policy.max_attempts,
                            "error_kind": perr.kind,
                            "failure_kind": perr.kind,
                            "status_code": perr.http_status,
                            "latency_ms": attempt_ms,
                            "stream": True,
                            "retryable": perr.retryable,
                        },
                    )
                    if attempt < policy.max_attempts and perr.retryable:
                        announce()
                        logger.info(
                            "provider.retry",
                            extra={
                                "event": "provider.retry",
                                "provider": "bedrock",
                                "model": self._cfg.model,
                                "request_id": request_id,
                                "messages_count": messages_count,
                                "attempt": attempt,
                                "next_attempt": attempt + 1,
                                "max_attempts": policy.max_attempts,
                                "error_kind": perr.kind,
                                "stream": True,
                            },
                        )
                    raise perr from None

                logger.info(
                    "provider.response",
                    extra={
                        "event": "provider.response",
                        "provider": "bedrock",
                        "model": self._cfg.model,
                        "request_id": request_id,
                        "messages_count": messages_count,
                        "attempt": attempt,
                        "max_attempts": policy.max_attempts,
                        "status_code": 200,
                        "stream": True,
                    },
                )
                return response

            response = await retry_async(_op, should_retry=_should_retry, policy=policy)
        except BaseException:
            if not acquisition_abandoned:
                try:
                    await _close_client_if_needed(True, client)
                except Exception:
                    pass
            raise

        queue: sync_queue.Queue[object] = sync_queue.Queue()
        state = _BedrockStreamState(queue=queue)
        cleanup = _BedrockCleanup(response, client)
        closed = asyncio.Event()
        consume_task = asyncio.create_task(
            self._consume_stream(
                response=response,
                cleanup=cleanup,
                state=state,
                start=start,
                request_id=request_id,
                messages_count=messages_count,
            )
        )

        async def chunk_iterator() -> AsyncIterator[str]:
            while True:
                try:
                    item = queue.get_nowait()
                except sync_queue.Empty:
                    await asyncio.sleep(0)
                    continue
                if item is _STREAM_END:
                    break
                yield str(item)

        async def get_final_result() -> ProviderStreamResult:
            close_waiter = asyncio.create_task(closed.wait())
            try:
                await asyncio.wait((consume_task, close_waiter), return_when=asyncio.FIRST_COMPLETED)
                if closed.is_set():
                    raise asyncio.CancelledError
                await asyncio.shield(consume_task)
            finally:
                close_waiter.cancel()
            if state.error is not None:
                raise state.error
            if state.final_result is None:
                raise ProviderError(
                    kind=ProviderErrorKind.unknown,
                    message="provider stream incomplete",
                    provider="bedrock",
                )
            return state.final_result

        return ProviderStreamSession(
            chunks=_OwnedBedrockChunks(chunk_iterator(), response, consume_task, on_close=closed.set, cleanup=cleanup),
            get_final_result=get_final_result,
        )

    async def _consume_stream(
        self,
        *,
        response: dict[str, Any],
        cleanup: "_BedrockCleanup",
        state: "_BedrockStreamState",
        start: float,
        request_id: Any,
        messages_count: int,
    ) -> None:
        try:
            if self._runtime_client is not None:
                _consume_stream_sync(
                    response=response,
                    state=state,
                    start=start,
                    request_id=request_id,
                    messages_count=messages_count,
                    model=self._cfg.model,
                    prompt_version=self._cfg.prompt_version,
                )
            else:
                await asyncio.to_thread(
                    _consume_stream_sync,
                    response=response,
                    state=state,
                    start=start,
                    request_id=request_id,
                    messages_count=messages_count,
                    model=self._cfg.model,
                    prompt_version=self._cfg.prompt_version,
                )
        finally:
            await cleanup.close()

    def _build_client(self) -> Any:
        if self._runtime_client is not None:
            return self._runtime_client

        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise ProviderError(
                kind=ProviderErrorKind.unknown,
                message="bedrock sdk not installed",
                provider="bedrock",
            ) from exc

        kwargs: dict[str, Any] = {
            "service_name": "bedrock-runtime",
            "region_name": self._cfg.region,
            "config": Config(
                read_timeout=self._cfg.timeout_s,
                connect_timeout=self._cfg.timeout_s,
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        }
        if self._cfg.aws_access_key_id:
            kwargs["aws_access_key_id"] = self._cfg.aws_access_key_id
        if self._cfg.aws_secret_access_key:
            kwargs["aws_secret_access_key"] = self._cfg.aws_secret_access_key
        if self._cfg.aws_session_token:
            kwargs["aws_session_token"] = self._cfg.aws_session_token
        return boto3.client(**kwargs)

    async def _call_client(self, fn: Any, **kwargs: Any) -> Any:
        if self._runtime_client is not None:
            return fn(**kwargs)
        return await asyncio.to_thread(fn, **kwargs)


@dataclass(slots=True)
class _BedrockStreamState:
    queue: sync_queue.Queue[object]
    final_result: ProviderStreamResult | None = None
    error: ProviderError | None = None


def _consume_stream_sync(
    *,
    response: dict[str, Any],
    state: "_BedrockStreamState",
    start: float,
    request_id: Any,
    messages_count: int,
    model: str,
    prompt_version: str,
) -> None:
    logger = logging.getLogger(__name__)
    content_parts: list[str] = []
    usage: dict[str, Any] | None = None
    latency_ms: int | None = None
    stream = response.get("stream")
    event_type: str | None = None

    try:
        for event in stream or []:
            stream_error = _extract_stream_error(event)
            if stream_error is not None:
                raise stream_error

            event_type = next(iter(event.keys()), None)
            delta = _extract_stream_delta(event)
            if delta:
                content_parts.append(delta)
                state.queue.put_nowait(delta)

            metadata = event.get("metadata")
            if isinstance(metadata, dict):
                maybe_usage = metadata.get("usage")
                if isinstance(maybe_usage, dict):
                    usage = maybe_usage
                metrics = metadata.get("metrics")
                if isinstance(metrics, dict):
                    latency_ms = _safe_int(metrics.get("latencyMs"))

        final_latency_ms = latency_ms if latency_ms is not None else int((time.monotonic() - start) * 1000)
        content = "".join(content_parts).strip() or "(empty response)"
        provider_result = _provider_result_from_parts(
            content=content,
            usage=usage or {},
            model_version=model,
            prompt_version=prompt_version,
            latency_ms=final_latency_ms,
        )
        _set_final_result(
            state,
            ProviderStreamResult(content=content, provider_result=provider_result),
        )
        logger.info(
            "provider.stream.complete",
            extra={
                "event": "provider.stream.complete",
                "provider": "bedrock",
                "model": provider_result.model_version,
                "request_id": request_id,
                "messages_count": messages_count,
                "latency_ms": final_latency_ms,
                "stream": True,
                "stream_event": event_type,
                "has_usage": any(
                    value is not None
                    for value in (
                        provider_result.input_tokens,
                        provider_result.output_tokens,
                        provider_result.total_tokens,
                    )
                ),
            },
        )
    except Exception as exc:
        error = exc if isinstance(exc, ProviderError) else _map_bedrock_exc(exc)
        _set_stream_error(state, error)
        logger.warning(
            "provider.stream.error",
            extra={
                "event": "provider.stream.error",
                "provider": "bedrock",
                "model": model,
                "request_id": request_id,
                "messages_count": messages_count,
                "latency_ms": int((time.monotonic() - start) * 1000),
                "stream": True,
                "error_kind": getattr(error, "kind", ProviderErrorKind.unknown),
                "failure_kind": getattr(error, "kind", ProviderErrorKind.unknown),
                "stream_event": event_type,
                "has_usage": isinstance(usage, dict),
            },
        )
    finally:
        state.queue.put_nowait(_STREAM_END)


def _set_final_result(state: _BedrockStreamState, final_result: ProviderStreamResult) -> None:
    state.final_result = final_result


def _set_stream_error(state: _BedrockStreamState, error: ProviderError) -> None:
    state.error = error


def _build_inline_stream_session(
    *,
    response: dict[str, Any],
    model: str,
    prompt_version: str,
    start: float,
    request_id: Any | None = None,
    messages_count: int | None = None,
) -> ProviderStreamSession:
    done = asyncio.Event()
    final_result: ProviderStreamResult | None = None
    stream_error: ProviderError | None = None

    async def chunk_iterator() -> AsyncIterator[str]:
        nonlocal final_result, stream_error
        logger = logging.getLogger(__name__)

        content_parts: list[str] = []
        usage: dict[str, Any] | None = None
        latency_ms: int | None = None
        event_type: str | None = None

        try:
            for event in response.get("stream") or []:
                maybe_error = _extract_stream_error(event)
                if maybe_error is not None:
                    raise maybe_error

                event_type = next(iter(event.keys()), None)
                delta = _extract_stream_delta(event)
                if delta:
                    content_parts.append(delta)
                    yield delta

                metadata = event.get("metadata")
                if isinstance(metadata, dict):
                    maybe_usage = metadata.get("usage")
                    if isinstance(maybe_usage, dict):
                        usage = maybe_usage
                    metrics = metadata.get("metrics")
                    if isinstance(metrics, dict):
                        latency_ms = _safe_int(metrics.get("latencyMs"))

            final_latency_ms = latency_ms if latency_ms is not None else int((time.monotonic() - start) * 1000)
            content = "".join(content_parts).strip() or "(empty response)"
            final_result = ProviderStreamResult(
                content=content,
                provider_result=_provider_result_from_parts(
                    content=content,
                    usage=usage or {},
                    model_version=model,
                    prompt_version=prompt_version,
                    latency_ms=final_latency_ms,
                ),
            )
            logger.info(
                "provider.stream.complete",
                extra={
                    "event": "provider.stream.complete",
                    "provider": "bedrock",
                    "model": final_result.provider_result.model_version,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "latency_ms": final_latency_ms,
                    "stream": True,
                    "stream_event": event_type,
                    "has_usage": any(
                        value is not None
                        for value in (
                            final_result.provider_result.input_tokens,
                            final_result.provider_result.output_tokens,
                            final_result.provider_result.total_tokens,
                        )
                    ),
                },
            )
        except Exception as exc:
            stream_error = exc if isinstance(exc, ProviderError) else _map_bedrock_exc(exc)
            logger.warning(
                "provider.stream.error",
                extra={
                    "event": "provider.stream.error",
                    "provider": "bedrock",
                    "model": model,
                    "request_id": request_id,
                    "messages_count": messages_count,
                    "latency_ms": int((time.monotonic() - start) * 1000),
                    "stream": True,
                    "error_kind": getattr(stream_error, "kind", ProviderErrorKind.unknown),
                    "failure_kind": getattr(stream_error, "kind", ProviderErrorKind.unknown),
                    "stream_event": event_type,
                    "has_usage": isinstance(usage, dict),
                },
            )
        finally:
            done.set()

    async def get_final_result() -> ProviderStreamResult:
        await done.wait()
        if stream_error is not None:
            raise stream_error
        if final_result is None:
            raise ProviderError(
                kind=ProviderErrorKind.unknown,
                message="provider stream incomplete",
                provider="bedrock",
            )
        return final_result

    return ProviderStreamSession(
        chunks=_OwnedBedrockChunks(chunk_iterator(), response, on_close=done.set),
        get_final_result=get_final_result,
    )


def _observe_task(task):
    try:
        task.result()
    except BaseException:
        pass


async def _close_event_stream(response):
    close = getattr(response.get("stream"), "close", None)
    if callable(close):
        try:
            await asyncio.to_thread(close)
        except Exception:
            pass


class _OwnedBedrockChunks:
    """Own the SDK event stream and any worker, including before first pull.

    Cancelling an asyncio task cannot stop an SDK call already running in a thread.
    """
    def __init__(self, iterator, response, worker=None, on_close=None, cleanup=None):
        self._iterator = iterator
        self._response = response
        self._worker = worker
        self._cleanup = cleanup
        self._on_close = on_close
        self._closed = False
        self._pull = None
        self._close_task = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._closed:
            raise StopAsyncIteration
        self._pull = asyncio.create_task(self._iterator.__anext__())
        try:
            return await self._pull
        except StopAsyncIteration:
            await self.aclose(completed=True)
            raise
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._pull = None

    async def aclose(self, *, completed=False):
        if self._close_task is None:
            self._closed = True
            if self._on_close and not completed:
                self._on_close()
            if self._worker and not completed and not self._worker.done():
                self._worker.cancel()
            self._close_task = asyncio.create_task(self._close())
            self._close_task.add_done_callback(_observe_task)
        await asyncio.shield(self._close_task)

    async def _close(self):
        if self._pull and not self._pull.done():
            self._pull.cancel()
            try:
                await self._pull
            except BaseException:
                pass
        try:
            await self._iterator.aclose()
        except BaseException:
            pass
        if self._worker:
            try:
                await self._worker
            except BaseException:
                pass
        if self._cleanup:
            await self._cleanup.close()
        else:
            await _close_event_stream(self._response)


class _BedrockCleanup:
    def __init__(self, response, client):
        self._response = response
        self._client = client
        self._task = None

    async def close(self):
        if self._task is None:
            self._task = asyncio.create_task(self._close())
            self._task.add_done_callback(_observe_task)
        await asyncio.shield(self._task)

    async def _close(self):
        try:
            await _close_event_stream(self._response)
        finally:
            try:
                await _close_client_if_needed(True, self._client)
            except Exception:
                pass


def _build_payload(*, input: ProviderInput, model: str) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system: list[dict[str, str]] = []
    for message in messages_for_provider(input):
        if message.role == "system":
            system.append({"text": message.content})
            continue
        messages.append(
            {
                "role": message.role,
                "content": [{"text": message.content}],
            }
        )

    payload: dict[str, Any] = {
        "modelId": model,
        "messages": messages,
    }
    if system:
        payload["system"] = system

    inference_config: dict[str, Any] = {}
    if input.temperature is not None:
        inference_config["temperature"] = input.temperature
    if input.max_tokens is not None:
        inference_config["maxTokens"] = input.max_tokens
    if inference_config:
        payload["inferenceConfig"] = inference_config

    return payload


def _extract_text_content(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts).strip() or "(empty response)"


def _provider_result_from_parts(
    *,
    content: str,
    usage: dict[str, Any],
    model_version: str,
    prompt_version: str,
    latency_ms: int,
) -> ProviderResult:
    input_tokens = _safe_int(usage.get("inputTokens"))
    output_tokens = _safe_int(usage.get("outputTokens"))
    total_tokens = _safe_int(usage.get("totalTokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    return ProviderResult(
        content=content,
        provider="bedrock",
        model_version=model_version,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        latency_ms=max(0, latency_ms),
    )


def _build_provider_result(
    data: dict[str, Any],
    *,
    default_model: str,
    prompt_version: str,
    latency_ms: int,
) -> ProviderResult:
    output = data.get("output") or {}
    message = output.get("message") if isinstance(output, dict) else {}
    content_blocks = message.get("content") if isinstance(message, dict) else []
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}

    effective_latency_ms = _safe_int(metrics.get("latencyMs"))
    return _provider_result_from_parts(
        content=_extract_text_content(content_blocks if isinstance(content_blocks, list) else []),
        usage=usage,
        model_version=default_model,
        prompt_version=prompt_version,
        latency_ms=effective_latency_ms if effective_latency_ms is not None else latency_ms,
    )


def _extract_stream_delta(event: dict[str, Any]) -> str:
    delta = event.get("contentBlockDelta")
    if not isinstance(delta, dict):
        return ""
    inner_delta = delta.get("delta")
    if not isinstance(inner_delta, dict):
        return ""
    text = inner_delta.get("text")
    return text if isinstance(text, str) else ""


def _extract_stream_error(event: dict[str, Any]) -> ProviderError | None:
    for key, value in event.items():
        if not key.endswith("Exception"):
            continue
        message = None
        if isinstance(value, dict):
            maybe_message = value.get("message")
            if isinstance(maybe_message, str) and maybe_message:
                message = maybe_message
        return _provider_error_from_code(code=key, message=message, http_status=None)
    return None


def _map_bedrock_exc(exc: Exception) -> ProviderError:
    response = getattr(exc, "response", None)
    error = response.get("Error") if isinstance(response, dict) else None
    metadata = response.get("ResponseMetadata") if isinstance(response, dict) else None

    code = error.get("Code") if isinstance(error, dict) and isinstance(error.get("Code"), str) else None
    message = error.get("Message") if isinstance(error, dict) and isinstance(error.get("Message"), str) else None
    http_status = _safe_int(metadata.get("HTTPStatusCode")) if isinstance(metadata, dict) else None

    if code is not None:
        return _provider_error_from_code(code=code, message=message, http_status=http_status)
    if isinstance(exc, TimeoutError):
        return _provider_error_from_code(code="TimeoutError", message=None, http_status=http_status)
    if isinstance(exc, ConnectionError):
        return ProviderError(
            kind=ProviderErrorKind.upstream,
            message="provider upstream error",
            provider="bedrock",
            http_status=http_status,
            retryable=True,
        )
    exc_name = type(exc).__name__.lower()
    if "timeout" in exc_name:
        return _provider_error_from_code(code="TimeoutError", message=None, http_status=http_status)
    if "connection" in exc_name or "endpoint" in exc_name:
        return ProviderError(
            kind=ProviderErrorKind.upstream,
            message="provider upstream error",
            provider="bedrock",
            http_status=http_status,
            retryable=True,
        )
    return ProviderError(
        kind=ProviderErrorKind.unknown,
        message="provider unknown error",
        provider="bedrock",
        http_status=http_status,
        retryable=False,
    )


def _provider_error_from_code(
    *,
    code: str,
    message: str | None,
    http_status: int | None,
) -> ProviderError:
    normalized_code = code.lower()

    if normalized_code in {
        "accesstokenexception",
        "accessdeniedexception",
        "unrecognizedclientexception",
        "securityexception",
    }:
        kind = ProviderErrorKind.auth
    elif normalized_code in {"throttlingexception", "toomanyrequestsexception"}:
        kind = ProviderErrorKind.rate_limit
    elif normalized_code in {"validationexception", "resourcenotfoundexception"}:
        kind = ProviderErrorKind.bad_request
    elif normalized_code in {"modeltimeoutexception", "timeoutexception", "timeouterror"}:
        kind = ProviderErrorKind.timeout
    elif normalized_code in {
        "internalserverexception",
        "serviceunavailableexception",
        "modelstreamerrorexception",
        "modelstreamexception",
        "modelnotreadyexception",
    }:
        kind = ProviderErrorKind.upstream
    else:
        kind = ProviderErrorKind.unknown

    retryable = kind in (
        ProviderErrorKind.rate_limit,
        ProviderErrorKind.timeout,
        ProviderErrorKind.upstream,
    )
    return ProviderError(
        kind=kind,
        # Never propagate Bedrock's free-form message: validation and model
        # errors may echo request/prompt fragments, including RAG content.
        message=_default_message(kind),
        provider="bedrock",
        http_status=http_status,
        retryable=retryable,
        error_code=code,
    )


def _default_message(kind: ProviderErrorKind) -> str:
    if kind == ProviderErrorKind.timeout:
        return "provider timeout"
    if kind == ProviderErrorKind.auth:
        return "provider auth failed"
    if kind == ProviderErrorKind.rate_limit:
        return "provider rate limited"
    if kind == ProviderErrorKind.bad_request:
        return "provider request failed"
    if kind == ProviderErrorKind.upstream:
        return "provider upstream error"
    return "provider unknown error"


def _safe_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except Exception:
        return None


async def _close_client_if_needed(close_client: bool, client: Any) -> None:
    if not close_client:
        return
    close = getattr(client, "close", None)
    if callable(close):
        await asyncio.to_thread(close)
