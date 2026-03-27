from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from app.core.domain.provider import (
    ProviderInput,
    ProviderPort,
    ProviderResult,
    ProviderStreamResult,
    ProviderStreamSession,
)
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind


_STREAM_END = object()


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


@dataclass(slots=True)
class _ResilientStreamState:
    queue: asyncio.Queue[object]
    final_result: ProviderStreamResult | None = None
    error: Exception | None = None
    first_chunk_emitted: bool = False
    fallback_used: bool = False


class ResilientProvider(ProviderPort):
    def __init__(self, primary: ProviderPort, fallback: ProviderPort) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider_name = _provider_label(primary)
        self.provider = self.provider_name

    async def generate(self, input: ProviderInput) -> ProviderResult:
        try:
            return await self._primary.generate(input)
        except Exception as exc:
            if not _is_retryable_provider_error(exc):
                raise
            return await self._fallback.generate(input)

    async def stream(self, input: ProviderInput) -> ProviderStreamSession | None:
        primary_stream = getattr(self._primary, "stream", None)
        if not callable(primary_stream):
            return None

        try:
            primary_session = await primary_stream(input)
        except Exception as exc:
            if not _is_retryable_provider_error(exc):
                raise
            return await self._start_fallback_stream(input)

        if primary_session is None:
            return None

        queue: asyncio.Queue[object] = asyncio.Queue()
        state = _ResilientStreamState(queue=queue)
        driver_task = asyncio.create_task(
            self._drive_stream(input=input, primary_session=primary_session, state=state)
        )

        async def chunk_iterator() -> AsyncIterator[str]:
            while True:
                item = await queue.get()
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

    async def _start_fallback_stream(self, input: ProviderInput) -> ProviderStreamSession | None:
        fallback_stream = getattr(self._fallback, "stream", None)
        if not callable(fallback_stream):
            return None
        return await fallback_stream(input)

    async def _drive_stream(
        self,
        *,
        input: ProviderInput,
        primary_session: ProviderStreamSession,
        state: _ResilientStreamState,
    ) -> None:
        try:
            state.final_result = await self._consume_session(
                session=primary_session,
                state=state,
            )
        except Exception as exc:
            if (
                not state.first_chunk_emitted
                and not state.fallback_used
                and _is_retryable_provider_error(exc)
            ):
                state.fallback_used = True
                try:
                    fallback_session = await self._start_fallback_stream(input)
                    if fallback_session is None:
                        raise
                    state.final_result = await self._consume_session(
                        session=fallback_session,
                        state=state,
                    )
                except Exception as fallback_exc:
                    state.error = fallback_exc
            else:
                state.error = exc
        finally:
            await state.queue.put(_STREAM_END)

    async def _consume_session(
        self,
        *,
        session: ProviderStreamSession,
        state: _ResilientStreamState,
    ) -> ProviderStreamResult:
        async for chunk in session.chunks:
            state.first_chunk_emitted = True
            await state.queue.put(chunk)
        return await session.get_final_result()
