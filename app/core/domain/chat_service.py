from __future__ import annotations

import asyncio
import contextvars
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Sequence
from uuid import UUID

from app.core.observability.tracing import set_attribute, span
from app.core.observability.routing_evidence import RoutingEvidence

from .provider_factory import ProviderResolver
from .routing.routing_types import RoutingContext
from .types import ChatMessage
from .chat_types import ChatServiceResult
from .provider import ProviderInput, ProviderPort, ProviderStreamResult
from .errors import ProviderTimeoutError, ProviderExecutionError
from .provider_errors import ProviderError, ProviderErrorKind


logger = logging.getLogger(__name__)

def _safe_exception(*args, **kwargs):
    try:
        logger.exception(*args, **kwargs)
    except Exception:
        pass

RoutingContextBuilder = Callable[..., RoutingContext]

@dataclass(frozen=True, slots=True)
class StreamChatResult:
    request_id: UUID
    assistant_message: ChatMessage
    provider_result: ProviderStreamResult | None


@dataclass(frozen=True, slots=True)
class ChatServiceStreamSession:
    chunks: AsyncIterator[str]
    get_final_result: Callable[[], Awaitable[StreamChatResult]]

async def _traced_generation_stream(
    chunks: AsyncIterator[str], provider_name: str, evidence: RoutingEvidence, request_id: UUID
) -> AsyncIterator[str]:
    """Wrap a provider stream so `rag.generate` covers the real generation.

    The span opens on the first pull (where consumption actually begins, not
    where the session was obtained), stays open for the whole stream, and closes
    on completion, error or cancellation. It yields exactly what it receives:
    no frame is added, dropped, reordered or reshaped, and no exception is
    caught -- `raise` is unconditional in every branch, so the SSE contract and
    the route's own error translation are untouched.

    `GeneratorExit` and `CancelledError` are `BaseException`, not `Exception`,
    so a client disconnect would otherwise leave the span open forever; they are
    classified and re-raised.
    """
    with span("rag.generate", **{"provider.name": provider_name}) as generate_span:
        try:
            async for chunk in chunks:
                yield chunk
        except (GeneratorExit, asyncio.CancelledError):
            set_attribute(generate_span, "rag.generation_outcome", "cancelled")
            evidence.terminal(request_id=request_id, stream=True, status="cancelled")
            raise
        except BaseException as exc:
            set_attribute(generate_span, "rag.generation_outcome", "error")
            evidence.terminal(request_id=request_id, stream=True, status="error", error=exc)
            raise
        else:
            set_attribute(generate_span, "rag.generation_outcome", "ok")


class _OwnedGenerationStream:
    """Own the provider iterator even before the traced generator starts."""

    def __init__(self, chunks, provider_name, evidence, request_id):
        self._chunks = chunks
        self._evidence = evidence
        self._request_id = request_id
        self._traced = _traced_generation_stream(chunks, provider_name, evidence, request_id)
        self._pull = None
        self._context = None
        self._close_task = None
        self._closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._closed:
            raise StopAsyncIteration
        if self._pull is not None:
            raise RuntimeError("concurrent stream pulls are not supported")
        if self._context is None:
            self._context = contextvars.copy_context()
        self._pull = asyncio.create_task(self._traced.__anext__(), context=self._context)
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
            if not completed:
                self._evidence.terminal(request_id=self._request_id, stream=True, status="cancelled")
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        pull = self._pull
        if pull is not None and not pull.done():
            pull.cancel()
            try:
                await pull
            except BaseException:
                pass
        for iterator in (self._traced, self._chunks):
            close = getattr(iterator, "aclose", None)
            if callable(close):
                try:
                    if iterator is self._traced:
                        await asyncio.create_task(close(), context=self._context)
                    else:
                        await close()
                except BaseException:
                    # Cleanup must not replace the stream outcome.
                    pass


class ChatService:
    """
    Pure orchestration service.

    Rules:
    - No DB access
    - No transactions
    - No FastAPI/HTTP semantics
    """

    def __init__(
        self,
        provider: ProviderPort | None = None,
        *,
        timeout_s: float,
        provider_resolver: ProviderResolver | None = None,
        routing_context_builder: RoutingContextBuilder | None = None,
        execution_configuration_id: str | None = None,
    ) -> None:
        if provider is None and provider_resolver is None:
            raise ValueError("provider or provider_resolver is required")
        if provider_resolver is not None and routing_context_builder is None:
            raise ValueError("routing_context_builder is required when provider_resolver is set")
        self._execution_configuration_id = execution_configuration_id
        self._provider = provider
        self._timeout_s = timeout_s
        self._provider_resolver = provider_resolver
        self._routing_context_builder = routing_context_builder

    @property
    def execution_configuration_id(self) -> str | None:
        return self._execution_configuration_id

    async def run(
        self,
        *,
        request_id: UUID,
        messages: Sequence[ChatMessage],
        provider_metadata: dict[str, Any] | None = None,
    ) -> ChatServiceResult:
        provider_in = ProviderInput(
            request_id=request_id,
            messages=messages,
            metadata=provider_metadata,
        )
        evidence = RoutingEvidence()
        try:
            provider, evidence = self._resolve_provider(provider_in=provider_in, stream=False, evidence=evidence)
        except asyncio.CancelledError:
            evidence.terminal(request_id=request_id, stream=False, status="cancelled")
            raise
        except Exception as exc:
            evidence.terminal(request_id=request_id, stream=False, status="error", error=exc)
            raise

        # `rag.generate` is emitted here because this is the provider-agnostic
        # generation boundary: instrumenting inside the OpenAI/Bedrock adapters
        # would duplicate the span per provider and couple observability to a
        # provider, which invariant 2 and the "no provider-specific logic in
        # domain services" rule both forbid. Every classification below is a
        # normalized outcome, never a provider message.
        with span(
            "rag.generate", **{"provider.name": type(provider).__name__}
        ) as generate_span:
            try:
                evidence.attempted = True
                provider_out = await asyncio.wait_for(
                    provider.generate(provider_in),
                    timeout=self._timeout_s,
                )
            except asyncio.CancelledError:
                evidence.terminal(request_id=request_id, stream=False, status="cancelled")
                raise
            except asyncio.TimeoutError as e:
                evidence.terminal(request_id=request_id, stream=False, status="timeout")
                # Internal diagnostics: full stacktrace in logs, sanitized error outward.
                set_attribute(generate_span, "rag.generation_outcome", "timeout")
                _safe_exception(
                    "provider_timeout request_id=%s provider=%s messages_count=%d timeout_s=%.3f",
                    str(request_id),
                    type(provider).__name__,
                    len(messages),
                    float(self._timeout_s),
                )
                raise ProviderTimeoutError("provider timeout") from e

            except ProviderError as e:
                evidence.terminal(request_id=request_id, stream=False, status="error", error=e)
                # Provider already normalized the failure; keep outward message safe and short.
                set_attribute(
                    generate_span,
                    "rag.generation_outcome",
                    "timeout" if e.kind == ProviderErrorKind.timeout else "provider_error",
                )
                _safe_exception(
                    "provider_error request_id=%s provider=%s kind=%s messages_count=%d",
                    str(request_id),
                    type(provider).__name__,
                    getattr(e.kind, "value", str(e.kind)),
                    len(messages),
                )
                if e.kind == ProviderErrorKind.timeout:
                    raise ProviderTimeoutError("provider timeout") from e
                raise ProviderExecutionError(str(e)) from e

            except Exception as e:
                evidence.terminal(request_id=request_id, stream=False, status="error", error=e)
                # Keep provider internals out of the boundary. Details belong in logs.
                set_attribute(generate_span, "rag.generation_outcome", "error")
                _safe_exception(
                    "provider_execution_error request_id=%s provider=%s messages_count=%d",
                    str(request_id),
                    type(provider).__name__,
                    len(messages),
                )
                raise ProviderExecutionError("provider execution failed") from e

            set_attribute(generate_span, "rag.generation_outcome", "ok")

        evidence.terminal(request_id=request_id, stream=False, status="success", result=provider_out)
        assistant = ChatMessage(role="assistant", content=provider_out.content)

        return ChatServiceResult(
            request_id=request_id,
            assistant_message=assistant,
            provider_result=provider_out,
        )

    async def stream_chat(
        self,
        *,
        request_id: UUID,
        messages: Sequence[ChatMessage],
        provider_metadata: dict[str, Any] | None = None,
    ) -> ChatServiceStreamSession:
        provider_in = ProviderInput(
            request_id=request_id,
            messages=messages,
            metadata=provider_metadata,
        )
        evidence = RoutingEvidence()
        try:
            provider, evidence = self._resolve_provider(provider_in=provider_in, stream=True, evidence=evidence)
        except asyncio.CancelledError:
            evidence.terminal(request_id=request_id, stream=True, status="cancelled")
            raise
        except Exception as exc:
            evidence.terminal(request_id=request_id, stream=True, status="error", error=exc)
            raise

        stream_fn = getattr(provider, "stream", None)
        if not callable(stream_fn):
            result = await self.run(
                request_id=request_id,
                messages=messages,
                provider_metadata=provider_metadata,
            )

            async def fallback_chunks() -> AsyncIterator[str]:
                yield result.assistant_message.content

            async def fallback_final_result() -> StreamChatResult:
                return StreamChatResult(
                    request_id=request_id,
                    assistant_message=result.assistant_message,
                    provider_result=None,
                )

            return ChatServiceStreamSession(
                chunks=fallback_chunks(),
                get_final_result=fallback_final_result,
            )

        try:
            evidence.attempted = True
            provider_session = await stream_fn(provider_in)
        except asyncio.CancelledError:
            evidence.terminal(request_id=request_id, stream=True, status="cancelled")
            raise
        except Exception as exc:
            evidence.terminal(request_id=request_id, stream=True, status="error", error=exc)
            raise

        if provider_session is None:
            result = await self.run(
                request_id=request_id,
                messages=messages,
                provider_metadata=provider_metadata,
            )

            async def fallback_chunks() -> AsyncIterator[str]:
                yield result.assistant_message.content

            async def fallback_final_result() -> StreamChatResult:
                return StreamChatResult(
                    request_id=request_id,
                    assistant_message=result.assistant_message,
                    provider_result=None,
                )

            return ChatServiceStreamSession(
                chunks=fallback_chunks(),
                get_final_result=fallback_final_result,
            )

        async def final_result() -> StreamChatResult:
            try:
                provider_stream_result = await provider_session.get_final_result()
            except asyncio.CancelledError:
                # A caller may cancel only its own waiter; stream ownership and
                # terminal cancellation are handled by the iterator proxy.
                raise
            except Exception as exc:
                evidence.terminal(request_id=request_id, stream=True, status="error", error=exc)
                raise
            evidence.terminal(request_id=request_id, stream=True, status="success", result=provider_stream_result.provider_result)
            assistant = ChatMessage(
                role="assistant",
                content=provider_stream_result.content,
            )
            return StreamChatResult(
                request_id=request_id,
                assistant_message=assistant,
                provider_result=provider_stream_result,
            )

        # Only the real streaming path is wrapped here. Both fallback paths above
        # delegate to run(), which already emits its own `rag.generate`; wrapping
        # them again would double-count a single generation.
        return ChatServiceStreamSession(
            chunks=_OwnedGenerationStream(
                provider_session.chunks, type(provider).__name__, evidence, request_id
            ),
            get_final_result=final_result,
        )

    def _resolve_provider(
        self,
        *,
        provider_in: ProviderInput,
        stream: bool,
        evidence: RoutingEvidence,
    ) -> tuple[ProviderPort, RoutingEvidence]:
        if self._provider_resolver is None:
            assert self._provider is not None
            return self._provider, evidence

        assert self._routing_context_builder is not None
        context = self._routing_context_builder(
            provider_input=provider_in,
            stream=stream,
        )
        resolved = self._provider_resolver(context)
        evidence = resolved.evidence or evidence
        evidence.decision = resolved.decision
        return resolved.provider, evidence
