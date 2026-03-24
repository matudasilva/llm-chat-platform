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
