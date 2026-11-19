from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.core.domain.provider import (
    ProviderInput,
    ProviderResult,
    ProviderStreamResult,
    ProviderStreamSession,
)
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.providers.resilient_provider import ResilientProvider


def _provider_input() -> ProviderInput:
    @dataclass(frozen=True)
    class _Message:
        role: str
        content: str

    return ProviderInput(
        request_id=uuid4(),
        messages=[_Message(role="user", content="hi")],
    )


def _retryable_error() -> ProviderError:
    return ProviderError(
        kind=ProviderErrorKind.upstream,
        message="provider upstream error",
        provider="primary",
        retryable=True,
    )


def _non_retryable_error() -> ProviderError:
    return ProviderError(
        kind=ProviderErrorKind.auth,
        message="provider auth failed",
        provider="primary",
        retryable=False,
    )


@dataclass
class FakeStreamSession:
    chunks_to_yield: list[str] = field(default_factory=list)
    final_result: ProviderStreamResult | None = None
    chunk_error: Exception | None = None
    final_error: Exception | None = None

    @property
    def chunks(self) -> AsyncIterator[str]:
        async def _chunks() -> AsyncIterator[str]:
            for chunk in self.chunks_to_yield:
                yield chunk
            if self.chunk_error is not None:
                raise self.chunk_error

        return _chunks()

    async def get_final_result(self) -> ProviderStreamResult:
        if self.final_error is not None:
            raise self.final_error
        assert self.final_result is not None
        return self.final_result


@dataclass
class ScriptedProvider:
    provider_name: str
    generate_actions: list[object] = field(default_factory=list)
    stream_actions: list[object] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.generate_calls = 0
        self.stream_calls = 0

    async def generate(self, input: ProviderInput) -> ProviderResult:
        self.generate_calls += 1
        if not self.generate_actions:
            raise AssertionError(f"{self.provider_name} generate action missing")
        action = self.generate_actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    async def stream(self, input: ProviderInput) -> ProviderStreamSession | None:
        self.stream_calls += 1
        if not self.stream_actions:
            raise AssertionError(f"{self.provider_name} stream action missing")
        action = self.stream_actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def _provider_result(*, provider: str, content: str) -> ProviderResult:
    return ProviderResult(
        content=content,
        provider=provider,
        model_version=f"{provider}-model",
        prompt_version="v1",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        latency_ms=5,
    )


def _event_records(caplog, event: str) -> list:
    return [record for record in caplog.records if getattr(record, "event", None) == event]


@pytest.mark.asyncio
async def test_resilient_provider_logs_final_on_success_without_fallback(caplog) -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        generate_actions=[_provider_result(provider="bedrock", content="ok")],
    )
    fallback = ScriptedProvider(
        provider_name="openai",
        generate_actions=[_provider_result(provider="openai", content="unused")],
    )
    provider = ResilientProvider(primary=primary, fallback=fallback)

    caplog.set_level("INFO")
    result = await provider.generate(_provider_input())

    assert result.provider == "bedrock"
    final_record = _event_records(caplog, "provider.final")[-1]
    assert final_record.provider == "bedrock"
    assert final_record.final_provider == "bedrock"
    assert final_record.fallback_used is False
    assert final_record.attempts_used == 1
    assert final_record.stream is False


@pytest.mark.asyncio
async def test_resilient_provider_falls_back_after_retryable_failure_exhausts_retries(caplog) -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        generate_actions=[_retryable_error()],
    )
    fallback = ScriptedProvider(
        provider_name="openai",
        generate_actions=[_provider_result(provider="openai", content="fallback ok")],
    )
    provider = ResilientProvider(primary=primary, fallback=fallback)

    caplog.set_level("INFO")
    result = await provider.generate(_provider_input())

    assert result.provider == "openai"
    assert result.content == "fallback ok"
    assert primary.generate_calls == 1
    assert fallback.generate_calls == 1
    fallback_record = _event_records(caplog, "provider.fallback")[-1]
    assert fallback_record.provider == "bedrock"
    assert fallback_record.fallback_from == "bedrock"
    assert fallback_record.fallback_to == "openai"
    assert fallback_record.failure_kind == ProviderErrorKind.upstream
    final_record = _event_records(caplog, "provider.final")[-1]
    assert final_record.final_provider == "openai"
    assert final_record.fallback_used is True
    assert final_record.attempts_used == 2


@pytest.mark.asyncio
async def test_resilient_provider_does_not_fall_back_for_non_retryable_error(caplog) -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        generate_actions=[_non_retryable_error()],
    )
    fallback = ScriptedProvider(
        provider_name="openai",
        generate_actions=[_provider_result(provider="openai", content="unused")],
    )
    provider = ResilientProvider(primary=primary, fallback=fallback)

    caplog.set_level("INFO")
    with pytest.raises(ProviderError) as exc:
        await provider.generate(_provider_input())

    assert exc.value.kind == ProviderErrorKind.auth
    assert primary.generate_calls == 1
    assert fallback.generate_calls == 0
    assert _event_records(caplog, "provider.fallback") == []
    final_record = _event_records(caplog, "provider.final")[-1]
    assert final_record.final_provider == "bedrock"
    assert final_record.fallback_used is False
    assert final_record.attempts_used == 1
    assert final_record.failure_kind == ProviderErrorKind.auth


@pytest.mark.asyncio
async def test_resilient_provider_stream_falls_back_before_first_token(caplog) -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        stream_actions=[
            FakeStreamSession(final_error=_retryable_error()),
        ],
    )
    fallback_result = ProviderStreamResult(
        content="fallback stream",
        provider_result=_provider_result(provider="openai", content="fallback stream"),
    )
    fallback = ScriptedProvider(
        provider_name="openai",
        stream_actions=[
            FakeStreamSession(
                chunks_to_yield=["fallback ", "stream"],
                final_result=fallback_result,
            ),
        ],
    )
    provider = ResilientProvider(primary=primary, fallback=fallback)

    caplog.set_level("INFO")
    session = await provider.stream(_provider_input())
    assert session is not None

    chunks: list[str] = []
    async for chunk in session.chunks:
        chunks.append(chunk)
    final = await session.get_final_result()

    assert "".join(chunks) == "fallback stream"
    assert final.provider_result.provider == "openai"
    assert primary.stream_calls == 1
    assert fallback.stream_calls == 1
    fallback_record = _event_records(caplog, "provider.fallback")[-1]
    assert fallback_record.stream is True
    assert fallback_record.failure_kind == ProviderErrorKind.upstream
    final_record = _event_records(caplog, "provider.final")[-1]
    assert final_record.final_provider == "openai"
    assert final_record.fallback_used is True
    assert final_record.attempts_used == 2
    assert final_record.first_token_emitted is False


@pytest.mark.asyncio
async def test_resilient_provider_stream_does_not_fall_back_after_first_token(caplog) -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        stream_actions=[
            FakeStreamSession(
                chunks_to_yield=["hello"],
                final_error=_retryable_error(),
            ),
        ],
    )
    fallback = ScriptedProvider(
        provider_name="openai",
        stream_actions=[],
    )
    provider = ResilientProvider(primary=primary, fallback=fallback)

    caplog.set_level("INFO")
    session = await provider.stream(_provider_input())
    assert session is not None

    chunks: list[str] = []
    async for chunk in session.chunks:
        chunks.append(chunk)

    with pytest.raises(ProviderError) as exc:
        await session.get_final_result()

    assert chunks == ["hello"]
    assert exc.value.kind == ProviderErrorKind.upstream
    assert primary.stream_calls == 1
    assert fallback.stream_calls == 0
    assert _event_records(caplog, "provider.fallback") == []
    final_record = _event_records(caplog, "provider.final")[-1]
    assert final_record.final_provider == "bedrock"
    assert final_record.fallback_used is False
    assert final_record.attempts_used == 1
    assert final_record.failure_kind == ProviderErrorKind.upstream
    assert final_record.first_token_emitted is True

class _BlockingChunks:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = 0
        self.error = error

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.started.set()
        await self.release.wait()
        if self.error:
            raise self.error
        raise StopAsyncIteration

    async def aclose(self):
        self.closed += 1
        self.release.set()


def _blocking_session(chunks: _BlockingChunks) -> ProviderStreamSession:
    async def final():
        raise AssertionError("closed stream has no result")

    return ProviderStreamSession(chunks=chunks, get_final_result=final)


@pytest.mark.asyncio
async def test_stream_close_before_pull_wakes_waiters_and_is_idempotent() -> None:
    upstream = _BlockingChunks()
    provider = ResilientProvider(
        ScriptedProvider("primary", stream_actions=[_blocking_session(upstream)]),
        ScriptedProvider("fallback"),
    )
    session = await provider.stream(_provider_input())
    assert session is not None
    waiter = asyncio.create_task(session.get_final_result())
    await asyncio.sleep(0)
    pull = asyncio.create_task(anext(session.chunks))
    await asyncio.sleep(0)
    await asyncio.gather(session.chunks.aclose(), session.chunks.aclose())
    with pytest.raises(StopAsyncIteration):
        await pull
    with pytest.raises(StopAsyncIteration):
        await anext(session.chunks)
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert upstream.closed == 1


@pytest.mark.asyncio
async def test_cancel_final_waiter_does_not_cancel_driver_or_other_waiters() -> None:
    upstream = _BlockingChunks()
    provider = ResilientProvider(
        ScriptedProvider("primary", stream_actions=[_blocking_session(upstream)]),
        ScriptedProvider("fallback"),
    )
    session = await provider.stream(_provider_input())
    assert session is not None
    first = asyncio.create_task(session.get_final_result())
    second = asyncio.create_task(session.get_final_result())
    await upstream.started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    await session.chunks.aclose()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert upstream.closed == 1


@pytest.mark.asyncio
async def test_close_after_fallback_transfer_closes_both_sessions() -> None:
    primary_chunks = _BlockingChunks(error=_retryable_error())
    fallback_chunks = _BlockingChunks()
    fallback = ScriptedProvider("fallback", stream_actions=[_blocking_session(fallback_chunks)])
    provider = ResilientProvider(
        ScriptedProvider("primary", stream_actions=[_blocking_session(primary_chunks)]), fallback
    )
    session = await provider.stream(_provider_input())
    assert session is not None
    await primary_chunks.started.wait()
    primary_chunks.release.set()
    await fallback_chunks.started.wait()
    await session.chunks.aclose()
    assert primary_chunks.closed == fallback_chunks.closed == 1
    assert fallback.stream_calls == 1
    with pytest.raises(asyncio.CancelledError):
        await session.get_final_result()

@pytest.mark.asyncio
async def test_close_before_driver_starts_closes_acquired_session() -> None:
    upstream = _BlockingChunks()
    fallback = ScriptedProvider("fallback")
    provider = ResilientProvider(
        ScriptedProvider("primary", stream_actions=[_blocking_session(upstream)]), fallback
    )
    session = await provider.stream(_provider_input())
    assert session is not None
    await session.chunks.aclose()
    assert upstream.closed == 1
    assert fallback.stream_calls == 0
    with pytest.raises(asyncio.CancelledError):
        await session.get_final_result()


@pytest.mark.asyncio
async def test_close_failure_does_not_replace_cancellation() -> None:
    class RaisingChunks(_BlockingChunks):
        async def aclose(self):
            self.closed += 1
            raise RuntimeError("cleanup failed")

    upstream = RaisingChunks()
    provider = ResilientProvider(
        ScriptedProvider("primary", stream_actions=[_blocking_session(upstream)]),
        ScriptedProvider("fallback"),
    )
    session = await provider.stream(_provider_input())
    assert session is not None
    await upstream.started.wait()
    await session.chunks.aclose()
    with pytest.raises(asyncio.CancelledError):
        await session.get_final_result()
    assert upstream.closed == 1


@pytest.mark.asyncio
async def test_cancel_during_fallback_acquisition_does_not_retry() -> None:
    class AcquiringProvider(ScriptedProvider):
        async def stream(self, input):
            self.stream_calls += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    started, cancelled = asyncio.Event(), asyncio.Event()
    primary_chunks = _BlockingChunks(error=_retryable_error())
    fallback = AcquiringProvider("fallback")
    provider = ResilientProvider(
        ScriptedProvider("primary", stream_actions=[_blocking_session(primary_chunks)]), fallback
    )
    session = await provider.stream(_provider_input())
    assert session is not None
    await primary_chunks.started.wait()
    primary_chunks.release.set()
    await started.wait()
    await session.chunks.aclose()
    assert cancelled.is_set()
    assert primary_chunks.closed == 1
    assert fallback.stream_calls == 1
    with pytest.raises(asyncio.CancelledError):
        await session.get_final_result()

@pytest.mark.asyncio
async def test_stalled_upstream_close_does_not_block_final_waiters() -> None:
    class StalledCloseChunks(_BlockingChunks):
        def __init__(self):
            super().__init__()
            self.close_started = asyncio.Event()
            self.allow_close = asyncio.Event()

        async def aclose(self):
            self.closed += 1
            self.close_started.set()
            await self.allow_close.wait()

    upstream = StalledCloseChunks()
    provider = ResilientProvider(
        ScriptedProvider("primary", stream_actions=[_blocking_session(upstream)]),
        ScriptedProvider("fallback"),
    )
    session = await provider.stream(_provider_input())
    assert session is not None
    await upstream.started.wait()
    waiter = asyncio.create_task(session.get_final_result())
    close = asyncio.create_task(session.chunks.aclose())
    await upstream.close_started.wait()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, timeout=1)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(session.get_final_result(), timeout=1)
    assert not close.done()
    upstream.allow_close.set()
    await close
    assert upstream.closed == 1
