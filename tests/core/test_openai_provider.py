import json
import pytest
import httpx

from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.domain.provider import ProviderInput, ProviderStreamSession
from uuid import uuid4

@pytest.mark.asyncio
async def test_openai_provider_success_extracts_output_text_and_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/responses"

        body = json.loads(request.content.decode("utf-8"))
        assert "model" in body
        assert "input" in body

        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "hello"}],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="https://api.openai.com", transport=transport)

    p = OpenAIProvider(
        OpenAIProviderConfig(api_key="k", model="gpt-4o-mini", timeout_s=1.0),
        http_client=client,
    )

    provider_in = ProviderInput(request_id=uuid4(), messages=[type("M", (), {"role": "user", "content": "hi"})()])
    out = await p.generate(provider_in)

    assert out.provider == "openai"
    assert out.model_version == "gpt-4o-mini"
    assert out.content == "hello"
    assert out.input_tokens == 10
    assert out.output_tokens == 5
    assert out.total_tokens == 15
    assert isinstance(out.latency_ms, int) and out.latency_ms >= 0

    await client.aclose()


@pytest.mark.asyncio
async def test_openai_provider_auth_401_maps_to_provider_error_auth():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "nope"}})

    client = httpx.AsyncClient(base_url="https://api.openai.com", transport=httpx.MockTransport(handler))

    p = OpenAIProvider(OpenAIProviderConfig(api_key="k", model="gpt-4o-mini", timeout_s=1.0), http_client=client)

    provider_in = ProviderInput(request_id=None, messages=[type("M", (), {"role": "user", "content": "hi"})()])

    with pytest.raises(ProviderError) as e:
        await p.generate(provider_in)

    assert e.value.kind == ProviderErrorKind.auth

    await client.aclose()


@pytest.mark.asyncio
async def test_openai_provider_rate_limit_429_maps_to_provider_error_rate_limit():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    client = httpx.AsyncClient(base_url="https://api.openai.com", transport=httpx.MockTransport(handler))

    p = OpenAIProvider(OpenAIProviderConfig(api_key="k", model="gpt-4o-mini", timeout_s=1.0), http_client=client)

    provider_in = ProviderInput(request_id=None, messages=[type("M", (), {"role": "user", "content": "hi"})()])

    with pytest.raises(ProviderError) as e:
        await p.generate(provider_in)

    assert e.value.kind == ProviderErrorKind.rate_limit

    await client.aclose()


@pytest.mark.asyncio
async def test_openai_provider_upstream_5xx_maps_to_provider_error_upstream():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "bad gateway"}})

    client = httpx.AsyncClient(base_url="https://api.openai.com", transport=httpx.MockTransport(handler))

    p = OpenAIProvider(OpenAIProviderConfig(api_key="k", model="gpt-4o-mini", timeout_s=1.0), http_client=client)

    provider_in = ProviderInput(request_id=None, messages=[type("M", (), {"role": "user", "content": "hi"})()])

    with pytest.raises(ProviderError) as e:
        await p.generate(provider_in)

    assert e.value.kind == ProviderErrorKind.upstream

    await client.aclose()


@pytest.mark.asyncio
async def test_openai_provider_timeout_maps_to_provider_error_timeout():
    class TimeoutTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout")

    client = httpx.AsyncClient(base_url="https://api.openai.com", transport=TimeoutTransport())

    p = OpenAIProvider(
        OpenAIProviderConfig(
            api_key="k",
            model="gpt-4o-mini",
            timeout_s=1.0,
            max_attempts=1,
            backoff_base_ms=0,
            backoff_max_ms=0,
        ),
        http_client=client,
    )

    provider_in = ProviderInput(request_id=None, messages=[type("M", (), {"role": "user", "content": "hi"})()])

    with pytest.raises(ProviderError) as e:
        await p.generate(provider_in)

    assert e.value.kind == ProviderErrorKind.timeout

    await client.aclose()


class _MockStream(httpx.AsyncByteStream):
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aiter__(self):
        for line in self._lines:
            yield line.encode("utf-8")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_openai_provider_stream_returns_session_and_final_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/responses"

        body = json.loads(request.content.decode("utf-8"))
        assert body["stream"] is True

        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_MockStream(
                [
                    'event: response.output_text.delta\n',
                    'data: {"type":"response.output_text.delta","delta":"hel"}\n',
                    "\n",
                    'event: response.output_text.delta\n',
                    'data: {"type":"response.output_text.delta","delta":"lo"}\n',
                    "\n",
                    'event: response.completed\n',
                    'data: {"type":"response.completed","response":{"model":"gpt-4o-mini-2024-07-18","prompt_version":"pv-27b","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"hello"}]}],"usage":{"input_tokens":10,"output_tokens":5}}}\n',
                    "\n",
                    "data: [DONE]\n",
                    "\n",
                ]
            ),
        )

    client = httpx.AsyncClient(
        base_url="https://api.openai.com",
        transport=httpx.MockTransport(handler),
    )

    p = OpenAIProvider(
        OpenAIProviderConfig(api_key="k", model="gpt-4o-mini", timeout_s=1.0),
        http_client=client,
    )

    provider_in = ProviderInput(request_id=uuid4(), messages=[type("M", (), {"role": "user", "content": "hi"})()])
    session = await p.stream(provider_in)

    assert isinstance(session, ProviderStreamSession)

    chunks = []
    async for chunk in session.chunks:
        chunks.append(chunk)

    final_result = await session.get_final_result()

    assert chunks == ["hel", "lo"]
    assert final_result.content == "hello"
    assert final_result.provider_result.content == "hello"
    assert final_result.provider_result.model_version == "gpt-4o-mini-2024-07-18"
    assert final_result.provider_result.prompt_version == "pv-27b"
    assert final_result.provider_result.input_tokens == 10
    assert final_result.provider_result.output_tokens == 5
    assert final_result.provider_result.total_tokens == 15
    assert isinstance(final_result.provider_result.latency_ms, int)
    assert final_result.provider_result.latency_ms >= 0

    await client.aclose()


@pytest.mark.asyncio
async def test_openai_provider_stream_accepts_eventless_completed_payload():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_MockStream(
                [
                    'data: {"type":"response.output_text.delta","delta":"hi"}\n',
                    "\n",
                    'data: {"type":"response.completed","response":{"model":"gpt-4.1-mini-2025-01-01","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"hi"}]}]}}\n',
                    "\n",
                    "data: [DONE]\n",
                    "\n",
                ]
            ),
        )

    client = httpx.AsyncClient(
        base_url="https://api.openai.com",
        transport=httpx.MockTransport(handler),
    )

    p = OpenAIProvider(
        OpenAIProviderConfig(api_key="k", model="gpt-4.1-mini", timeout_s=1.0),
        http_client=client,
    )

    session = await p.stream(
        ProviderInput(request_id=uuid4(), messages=[type("M", (), {"role": "user", "content": "hi"})()])
    )

    chunks = []
    async for chunk in session.chunks:
        chunks.append(chunk)

    final_result = await session.get_final_result()

    assert chunks == ["hi"]
    assert final_result.content == "hi"
    assert final_result.provider_result.model_version == "gpt-4.1-mini-2025-01-01"

    await client.aclose()


@pytest.mark.asyncio
async def test_openai_provider_stream_maps_sse_error_payload():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_MockStream(
                [
                    'event: error\n',
                    'data: {"type":"error","error":{"message":"rate limited","type":"rate_limit_error","code":"rate_limit_exceeded"}}\n',
                    "\n",
                ]
            ),
        )

    client = httpx.AsyncClient(
        base_url="https://api.openai.com",
        transport=httpx.MockTransport(handler),
    )

    p = OpenAIProvider(
        OpenAIProviderConfig(api_key="k", model="gpt-4.1-mini", timeout_s=1.0),
        http_client=client,
    )

    session = await p.stream(
        ProviderInput(request_id=uuid4(), messages=[type("M", (), {"role": "user", "content": "hi"})()])
    )

    with pytest.raises(ProviderError) as exc:
        async for _ in session.chunks:
            pass
        await session.get_final_result()

    assert exc.value.kind == ProviderErrorKind.rate_limit
    assert exc.value.error_code == "rate_limit_exceeded"

    await client.aclose()
    # Finalize nested httpx async generators before pytest closes this test's loop.
    import asyncio
    await asyncio.get_running_loop().shutdown_asyncgens()


@pytest.mark.asyncio
async def test_openai_provider_stream_normalizes_transport_errors():
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadError("boom")
            yield b""

        async def aclose(self) -> None:
            return None

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=BrokenStream(),
        )

    client = httpx.AsyncClient(
        base_url="https://api.openai.com",
        transport=httpx.MockTransport(handler),
    )

    p = OpenAIProvider(
        OpenAIProviderConfig(api_key="k", model="gpt-4o-mini", timeout_s=1.0),
        http_client=client,
    )

    session = await p.stream(
        ProviderInput(request_id=uuid4(), messages=[type("M", (), {"role": "user", "content": "hi"})()])
    )

    with pytest.raises(ProviderError) as exc:
        async for _ in session.chunks:
            pass
        await session.get_final_result()

    assert exc.value.kind == ProviderErrorKind.upstream

    await client.aclose()

class _OwnedResponse:
    status_code = 200

    def __init__(self, fragment=False):
        import asyncio
        self.fragment = fragment
        self.started = asyncio.Event()

    async def aiter_lines(self):
        if self.fragment:
            yield 'data: {"type":"response.output_text.delta","delta":"hello"}'
            yield ''
        self.started.set()
        import asyncio
        await asyncio.Event().wait()


class _OwnedContext:
    def __init__(self, *, fragment=False, block_enter=False, block_close=False):
        import asyncio
        self.response = _OwnedResponse(fragment)
        self.entered = asyncio.Event()
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()
        if not block_close:
            self.allow_close.set()
        self.block_enter = block_enter
        self.closes = 0

    async def __aenter__(self):
        import asyncio
        self.entered.set()
        if self.block_enter:
            await asyncio.Event().wait()
        return self.response

    async def __aexit__(self, *args):
        self.closes += 1
        self.close_started.set()
        await self.allow_close.wait()


class _OwnedClient:
    def __init__(self, context):
        self.context = context
        self.closed = False

    def stream(self, *args, **kwargs):
        return self.context

    async def aclose(self):
        self.closed = True


def _owned_provider(context):
    client = _OwnedClient(context)
    provider = OpenAIProvider(
        OpenAIProviderConfig(api_key="k", model="gpt-4o-mini", timeout_s=1.0),
        http_client=client,
    )
    input = ProviderInput(request_id=uuid4(), messages=[type("M", (), {"role": "user", "content": "hi"})()])
    return provider, client, input


@pytest.mark.asyncio
@pytest.mark.parametrize("fragment", [False, True])
async def test_openai_stream_close_owns_response_and_wakes_waiters(fragment):
    import asyncio
    context = _OwnedContext(fragment=fragment)
    provider, client, input = _owned_provider(context)
    session = await provider.stream(input)
    if fragment:
        assert await anext(session.chunks) == "hello"
        await context.response.started.wait()
    waiter = asyncio.create_task(session.get_final_result())
    pull = asyncio.create_task(anext(session.chunks))
    await asyncio.sleep(0)
    await asyncio.gather(session.chunks.aclose(), session.chunks.aclose())
    with pytest.raises(StopAsyncIteration):
        await pull
    with pytest.raises(StopAsyncIteration):
        await anext(session.chunks)
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert context.closes == 1
    assert not client.closed


@pytest.mark.asyncio
async def test_openai_stream_cancel_during_acquisition_closes_context():
    import asyncio
    context = _OwnedContext(block_enter=True)
    provider, client, input = _owned_provider(context)
    acquisition = asyncio.create_task(provider.stream(input))
    await context.entered.wait()
    acquisition.cancel()
    with pytest.raises(asyncio.CancelledError):
        await acquisition
    await context.close_started.wait()
    assert context.closes == 1
    assert not client.closed


@pytest.mark.asyncio
async def test_openai_stream_stalled_cleanup_and_isolated_final_waiters():
    import asyncio
    context = _OwnedContext(block_close=True)
    provider, client, input = _owned_provider(context)
    session = await provider.stream(input)
    await context.response.started.wait()
    first = asyncio.create_task(session.get_final_result())
    second = asyncio.create_task(session.get_final_result())
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    close = asyncio.create_task(session.chunks.aclose())
    await context.close_started.wait()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(second, 1)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(session.get_final_result(), 1)
    assert not close.done()
    context.allow_close.set()
    await close
    assert context.closes == 1
    assert not client.closed

@pytest.mark.asyncio
async def test_openai_resilience_waits_for_cleanup_before_eof():
    import asyncio
    from app.core.providers.resilient_provider import ResilientProvider

    class CompleteResponse(_OwnedResponse):
        async def aiter_lines(self):
            yield 'data: {"type":"response.output_text.delta","delta":"hello"}'
            yield ''
            yield 'data: {"type":"response.completed","response":{"model":"gpt-4o-mini","output":[]}}'
            yield ''

    context = _OwnedContext(block_close=True)
    context.response = CompleteResponse()
    primary, client, input = _owned_provider(context)
    provider = ResilientProvider(primary, primary)
    session = await provider.stream(input)
    assert session is not None
    assert await anext(session.chunks) == "hello"
    await context.close_started.wait()
    pending_end = asyncio.create_task(anext(session.chunks))
    await asyncio.sleep(0)
    assert not pending_end.done()
    context.allow_close.set()
    with pytest.raises(StopAsyncIteration):
        await pending_end
    final = await session.get_final_result()
    assert final.content == "hello"
    assert context.closes == 1
    assert not client.closed
