import uuid
import pytest

from app.core.domain.chat_service import ChatService
from app.core.domain.types import ChatMessage
from app.core.providers.stub_provider import StubProvider
from app.core.domain.errors import ProviderExecutionError
from app.core.domain.provider import ProviderResult


@pytest.mark.asyncio
async def test_chat_service_returns_assistant_message_and_provider_result() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="ok")
    service = ChatService(provider, timeout_s=1.0)


    request_id = uuid.uuid4()
    messages = [ChatMessage(role="user", content="Hola!")]

    res = await service.run(request_id=request_id, messages=messages)

    assert res.request_id == request_id
    assert res.assistant_message.role == "assistant"
    assert isinstance(res.assistant_message.content, str) and res.assistant_message.content

    pr = res.provider_result
    assert pr.provider == "stub"
    assert pr.model_version
    assert pr.prompt_version
    assert pr.content == res.assistant_message.content


@pytest.mark.asyncio
async def test_chat_service_propagates_provider_error() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="error")
    service = ChatService(provider, timeout_s=1.0)

    with pytest.raises(ProviderExecutionError, match="provider execution failed") as exc:
        await service.run(
            request_id=uuid.uuid4(),
            messages=[ChatMessage(role="user", content="boom")],
        )

    assert isinstance(exc.value.__cause__, RuntimeError)
    assert "simulated error" in str(exc.value.__cause__)


@pytest.mark.asyncio
async def test_chat_service_stream_chat_propagates_final_provider_result() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="ok")
    service = ChatService(provider, timeout_s=1.0)

    request_id = uuid.uuid4()
    messages = [ChatMessage(role="user", content="stream me")]

    session = await service.stream_chat(request_id=request_id, messages=messages)

    streamed = []
    async for chunk in session.chunks:
        streamed.append(chunk)

    result = await session.get_final_result()

    assert result.request_id == request_id
    assert result.assistant_message.role == "assistant"
    assert result.assistant_message.content == "".join(streamed).strip()
    assert result.provider_result is not None
    assert result.provider_result.provider_result.provider == "stub"
    assert result.provider_result.provider_result.input_tokens is not None
    assert result.provider_result.provider_result.output_tokens is not None
    assert result.provider_result.provider_result.total_tokens == (
        result.provider_result.provider_result.input_tokens
        + result.provider_result.provider_result.output_tokens
    )


@pytest.mark.asyncio
async def test_chat_service_stream_chat_does_not_swallow_provider_attribute_error() -> None:
    class BrokenStreamingProvider:
        async def generate(self, input):
            raise AssertionError("generate fallback must not run")

        async def stream(self, input):
            raise AttributeError("provider stream startup bug")

    service = ChatService(BrokenStreamingProvider(), timeout_s=1.0)

    with pytest.raises(AttributeError, match="startup bug"):
        await service.stream_chat(
            request_id=uuid.uuid4(),
            messages=[ChatMessage(role="user", content="stream me")],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_value", ["missing", None])
async def test_chat_service_stream_fallback_preserves_provider_metadata(stream_value) -> None:
    class GenerateOnlyProvider:
        def __init__(self) -> None:
            self.metadata = None

        async def generate(self, input):
            self.metadata = input.metadata
            return ProviderResult(
                content="fallback",
                provider="stub",
                model_version="stub-v1",
                prompt_version="v1",
            )

    provider = GenerateOnlyProvider()
    if stream_value is None:
        async def _stream(input):
            return None

        provider.stream = _stream

    metadata = {"rag": {"schema_version": "rag-generation-v1", "sources": []}}
    service = ChatService(provider, timeout_s=1.0)

    session = await service.stream_chat(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content="question")],
        provider_metadata=metadata,
    )
    chunks = [chunk async for chunk in session.chunks]

    assert chunks == ["fallback"]
    assert provider.metadata is metadata


@pytest.mark.asyncio
async def test_stream_close_owns_unstarted_provider_and_wakes_final_waiter() -> None:
    import asyncio
    from types import SimpleNamespace

    class Chunks:
        def __init__(self):
            self.closed = asyncio.Event()
            self.close_count = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            await self.closed.wait()
            raise StopAsyncIteration

        async def aclose(self):
            self.close_count += 1
            self.closed.set()

    chunks = Chunks()

    class Provider:
        async def stream(self, input):
            async def final():
                await chunks.closed.wait()
                raise asyncio.CancelledError
            return SimpleNamespace(chunks=chunks, get_final_result=final)

    session = await ChatService(Provider(), timeout_s=1).stream_chat(request_id=uuid.uuid4(), messages=[])
    waiter = asyncio.create_task(session.get_final_result())
    await asyncio.gather(session.chunks.aclose(), session.chunks.aclose())
    with pytest.raises(asyncio.CancelledError):
        await waiter
    with pytest.raises(StopAsyncIteration):
        await anext(session.chunks)
    assert chunks.close_count == 1


@pytest.mark.asyncio
async def test_stream_close_cancels_pending_pull_and_preserves_cleanup_failure() -> None:
    import asyncio
    from types import SimpleNamespace

    started = asyncio.Event()
    closed = asyncio.Event()

    class Chunks:
        def __aiter__(self):
            return self

        async def __anext__(self):
            started.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()
            raise RuntimeError("cleanup failure")

    class Provider:
        async def stream(self, input):
            return SimpleNamespace(chunks=Chunks(), get_final_result=None)

    session = await ChatService(Provider(), timeout_s=1).stream_chat(request_id=uuid.uuid4(), messages=[])
    pull = asyncio.create_task(anext(session.chunks))
    await started.wait()
    await session.chunks.aclose()
    with pytest.raises(asyncio.CancelledError):
        await pull
    assert closed.is_set()
    with pytest.raises(StopAsyncIteration):
        await anext(session.chunks)


@pytest.mark.asyncio
async def test_cancelling_one_final_waiter_does_not_cancel_another(caplog) -> None:
    import asyncio
    import json
    import logging

    caplog.set_level(logging.INFO)
    from types import SimpleNamespace
    from app.core.domain.provider import ProviderStreamResult

    loop = asyncio.get_running_loop()
    final = loop.create_future()

    class Chunks:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            pass

    class Provider:
        async def stream(self, input):
            async def get_final():
                return await asyncio.shield(final)
            return SimpleNamespace(chunks=Chunks(), get_final_result=get_final)

    session = await ChatService(Provider(), timeout_s=1).stream_chat(request_id=uuid.uuid4(), messages=[])
    first = asyncio.create_task(session.get_final_result())
    second = asyncio.create_task(session.get_final_result())
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    result = ProviderResult(content="done", provider="stub", model_version="v1", prompt_version="v1")
    final.set_result(ProviderStreamResult(content="done", provider_result=result))
    assert (await second).assistant_message.content == "done"
    events = [json.loads(record.message) for record in caplog.records if getattr(record, "event", None) == "routing.evidence"]
    assert len(events) == 1 and events[0]["status"] == "success"
    await session.chunks.aclose()


@pytest.mark.asyncio
async def test_final_waiter_can_terminate_while_upstream_cleanup_stalls() -> None:
    import asyncio
    from types import SimpleNamespace

    closed = asyncio.Event()
    release = asyncio.Event()

    class Chunks:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            closed.set()
            await release.wait()

    class Provider:
        async def stream(self, input):
            async def final():
                await closed.wait()
                raise asyncio.CancelledError
            return SimpleNamespace(chunks=Chunks(), get_final_result=final)

    session = await ChatService(Provider(), timeout_s=1).stream_chat(request_id=uuid.uuid4(), messages=[])
    waiter = asyncio.create_task(session.get_final_result())
    closer = asyncio.create_task(session.chunks.aclose())
    await closed.wait()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, 1)
    assert not closer.done()
    release.set()
    await closer


@pytest.mark.asyncio
@pytest.mark.parametrize("early_close", [False, True])
async def test_stream_trace_context_is_shared_across_pulls_and_close(monkeypatch, early_close) -> None:
    from contextlib import contextmanager
    from contextvars import ContextVar
    from types import SimpleNamespace

    current = ContextVar("stream_trace", default=None)
    detach_errors = []

    @contextmanager
    def context_span(*args, **kwargs):
        token = current.set("active")
        try:
            yield None
        finally:
            try:
                current.reset(token)
            except ValueError as exc:
                detach_errors.append(exc)

    monkeypatch.setattr("app.core.domain.chat_service.span", context_span)

    class Provider:
        async def stream(self, input):
            async def chunks():
                assert current.get() == "active"
                yield "a"
                assert current.get() == "active"
                yield "b"
            return SimpleNamespace(chunks=chunks(), get_final_result=None)

    session = await ChatService(Provider(), timeout_s=1).stream_chat(request_id=uuid.uuid4(), messages=[])
    assert await anext(session.chunks) == "a"
    if early_close:
        await session.chunks.aclose()
    else:
        assert await anext(session.chunks) == "b"
        with pytest.raises(StopAsyncIteration):
            await anext(session.chunks)
    assert detach_errors == []
