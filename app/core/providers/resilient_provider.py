from __future__ import annotations

import asyncio
import logging
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


_STREAM_END = object()
logger = logging.getLogger(__name__)


def _provider_label(provider: ProviderPort) -> str:
    for attr in ("provider_name", "provider"):
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    return type(provider).__name__.lower()


def _is_retryable_provider_error(exc: Exception) -> bool:
    if not isinstance(exc, ProviderError):
        return False
    if exc.retryable:
        return True
    return exc.kind in (
        ProviderErrorKind.rate_limit,
        ProviderErrorKind.upstream,
        ProviderErrorKind.timeout,
    )


def _failure_kind(exc: Exception | None) -> str | None:
    if exc is None:
        return None
    if isinstance(exc, ProviderError):
        return exc.kind.value
    return ProviderErrorKind.unknown.value


def _result_provider(result: ProviderResult | ProviderStreamResult, default: str) -> str:
    if isinstance(result, ProviderStreamResult):
        provider = result.provider_result.provider
    else:
        provider = result.provider
    return provider if isinstance(provider, str) and provider else default


@dataclass(slots=True)
class _ResilientStreamState:
    queue: asyncio.Queue[object]
    final_result: ProviderStreamResult | None = None
    error: Exception | None = None
    first_chunk_emitted: bool = False
    first_token_emitted: bool = False
    fallback_used: bool = False
    attempts_used: int = 1
    final_provider: str | None = None
    failure_kind: str | None = None


class ResilientProvider(ProviderPort):
    def __init__(self, primary: ProviderPort, fallback: ProviderPort) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider_name = _provider_label(primary)
        self.provider = self.provider_name
        self._fallback_name = _provider_label(fallback)

    async def generate(self, input: ProviderInput) -> ProviderResult:
        request_id = getattr(input, "request_id", None)
        try:
            result = await self._primary.generate(input)
            self._log_final(
                request_id=request_id,
                final_provider=_result_provider(result, self.provider_name),
                fallback_used=False,
                attempts_used=1,
                stream=False,
            )
            return result
        except Exception as exc:
            if not _is_retryable_provider_error(exc):
                self._log_final(
                    request_id=request_id,
                    final_provider=self.provider_name,
                    fallback_used=False,
                    attempts_used=1,
                    stream=False,
                    failure_kind=_failure_kind(exc),
                )
                raise

            self._log_fallback(
                request_id=request_id,
                failure_kind=_failure_kind(exc),
                stream=False,
            )
            try:
                result = await self._fallback.generate(input)
            except Exception as fallback_exc:
                self._log_final(
                    request_id=request_id,
                    final_provider=self._fallback_name,
                    fallback_used=True,
                    attempts_used=2,
                    stream=False,
                    failure_kind=_failure_kind(fallback_exc),
                )
                raise

            self._log_final(
                request_id=request_id,
                final_provider=_result_provider(result, self._fallback_name),
                fallback_used=True,
                attempts_used=2,
                stream=False,
            )
            return result

    async def stream(self, input: ProviderInput) -> ProviderStreamSession | None:
        primary_stream = getattr(self._primary, "stream", None)
        if not callable(primary_stream):
            return None
        request_id = getattr(input, "request_id", None)

        try:
            primary_session = await primary_stream(input)
        except Exception as exc:
            if not _is_retryable_provider_error(exc):
                self._log_final(
                    request_id=request_id,
                    final_provider=self.provider_name,
                    fallback_used=False,
                    attempts_used=1,
                    stream=True,
                    failure_kind=_failure_kind(exc),
                    first_token_emitted=False,
                )
                raise

            try:
                fallback_session = await self._start_fallback_session(input=input, exc=exc)
            except Exception as fallback_exc:
                self._log_final(
                    request_id=request_id,
                    final_provider=self._fallback_name,
                    fallback_used=True,
                    attempts_used=2,
                    stream=True,
                    failure_kind=_failure_kind(fallback_exc),
                    first_token_emitted=False,
                )
                raise

            if fallback_session is None:
                return None

            return self._build_stream_session(
                input=input,
                initial_session=fallback_session,
                state=_ResilientStreamState(
                    queue=asyncio.Queue(),
                    fallback_used=True,
                    attempts_used=2,
                ),
            )

        if primary_session is None:
            return None

        return self._build_stream_session(
            input=input,
            initial_session=primary_session,
            state=_ResilientStreamState(queue=asyncio.Queue()),
        )

    async def _start_fallback_stream(self, input: ProviderInput) -> ProviderStreamSession | None:
        fallback_stream = getattr(self._fallback, "stream", None)
        if not callable(fallback_stream):
            return None
        return await fallback_stream(input)

    async def _start_fallback_session(
        self,
        *,
        input: ProviderInput,
        exc: Exception,
    ) -> ProviderStreamSession | None:
        request_id = getattr(input, "request_id", None)
        self._log_fallback(
            request_id=request_id,
            failure_kind=_failure_kind(exc),
            stream=True,
        )
        return await self._start_fallback_stream(input)

    def _build_stream_session(
        self,
        *,
        input: ProviderInput,
        initial_session: ProviderStreamSession,
        state: _ResilientStreamState,
    ) -> ProviderStreamSession:
        driver_task = asyncio.create_task(
            self._drive_stream(input=input, session=initial_session, state=state)
        )

        async def chunk_iterator() -> AsyncIterator[str]:
            while True:
                item = await state.queue.get()
                if item is _STREAM_END:
                    break
                yield str(item)

        async def get_final_result() -> ProviderStreamResult:
            await driver_task
            if state.error is not None:
                raise state.error
            if state.final_result is None:
                raise ProviderError(
                    kind=ProviderErrorKind.unknown,
                    message="provider stream incomplete",
                    provider=self.provider_name,
                )
            return state.final_result

        return ProviderStreamSession(
            chunks=chunk_iterator(),
            get_final_result=get_final_result,
        )

    async def _drive_stream(
        self,
        *,
        input: ProviderInput,
        session: ProviderStreamSession,
        state: _ResilientStreamState,
    ) -> None:
        try:
            state.final_result = await self._consume_session(
                session=session,
                state=state,
            )
            state.final_provider = _result_provider(
                state.final_result,
                self._fallback_name if state.fallback_used else self.provider_name,
            )
        except Exception as exc:
            if (
                not state.first_chunk_emitted
                and not state.fallback_used
                and _is_retryable_provider_error(exc)
            ):
                state.fallback_used = True
                state.attempts_used = 2
                try:
                    fallback_session = await self._start_fallback_session(input=input, exc=exc)
                    if fallback_session is None:
                        raise
                    state.final_result = await self._consume_session(
                        session=fallback_session,
                        state=state,
                    )
                    state.final_provider = _result_provider(state.final_result, self._fallback_name)
                except Exception as fallback_exc:
                    state.error = fallback_exc
                    state.final_provider = self._fallback_name
                    state.failure_kind = _failure_kind(fallback_exc)
            else:
                state.error = exc
                state.final_provider = self._fallback_name if state.fallback_used else self.provider_name
                state.failure_kind = _failure_kind(exc)
        finally:
            self._log_final(
                request_id=getattr(input, "request_id", None),
                final_provider=state.final_provider or self.provider_name,
                fallback_used=state.fallback_used,
                attempts_used=state.attempts_used,
                stream=True,
                failure_kind=state.failure_kind,
                first_token_emitted=state.first_token_emitted,
            )
            await state.queue.put(_STREAM_END)

    async def _consume_session(
        self,
        *,
        session: ProviderStreamSession,
        state: _ResilientStreamState,
    ) -> ProviderStreamResult:
        async for chunk in session.chunks:
            if not state.fallback_used:
                state.first_token_emitted = True
            state.first_chunk_emitted = True
            await state.queue.put(chunk)
        return await session.get_final_result()

    def _log_fallback(
        self,
        *,
        request_id: Any,
        failure_kind: str | None,
        stream: bool,
    ) -> None:
        logger.info(
            "provider.fallback",
            extra={
                "event": "provider.fallback",
                "provider": self.provider_name,
                "fallback_from": self.provider_name,
                "fallback_to": self._fallback_name,
                "failure_kind": failure_kind,
                "stream": stream,
                "request_id": request_id,
            },
        )

    def _log_final(
        self,
        *,
        request_id: Any,
        final_provider: str,
        fallback_used: bool,
        attempts_used: int,
        stream: bool,
        failure_kind: str | None = None,
        first_token_emitted: bool | None = None,
    ) -> None:
        extra = {
            "event": "provider.final",
            "provider": self.provider_name,
            "final_provider": final_provider,
            "fallback_used": fallback_used,
            "attempts_used": attempts_used,
            "stream": stream,
            "request_id": request_id,
        }
        if failure_kind is not None:
            extra["failure_kind"] = failure_kind
        if stream:
            extra["first_token_emitted"] = bool(first_token_emitted)

        log_fn = logger.warning if failure_kind is not None else logger.info
        log_fn("provider.final", extra=extra)
