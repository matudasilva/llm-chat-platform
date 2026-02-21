import json
import pytest
import httpx

from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.domain.provider import ProviderInput
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

    p = OpenAIProvider(OpenAIProviderConfig(api_key="k", model="gpt-4o-mini", timeout_s=0.01), http_client=client)

    provider_in = ProviderInput(request_id=None, messages=[type("M", (), {"role": "user", "content": "hi"})()])

    with pytest.raises(ProviderError) as e:
        await p.generate(provider_in)

    assert e.value.kind == ProviderErrorKind.timeout

    await client.aclose()