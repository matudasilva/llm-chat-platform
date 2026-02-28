import httpx
import pytest
import uuid

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig


def _mk_input() -> ProviderInput:
    # Adjust if your ProviderInput constructor differs.
    # Assuming ProviderInput(messages=[...]) where messages have role/content.
    class _Msg:
        def __init__(self, role: str, content: str) -> None:
            self.role = role
            self.content = content

    return ProviderInput(
        request_id=str(uuid.uuid4()),
        messages=[_Msg(role="user", content="hi")],
    )

@pytest.mark.asyncio
async def test_openai_provider_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}],
                    }
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.openai.com") as client:
        cfg = OpenAIProviderConfig(
            api_key="x",
            model="gpt-test",
            timeout_s=1.0,
            max_attempts=3,
            backoff_base_ms=1,
            backoff_max_ms=2,
        )
        p = OpenAIProvider(cfg, http_client=client)
        out = await p.generate(_mk_input())

    assert out.content == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_openai_provider_does_not_retry_on_auth_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "nope"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.openai.com") as client:
        cfg = OpenAIProviderConfig(
            api_key="x",
            model="gpt-test",
            timeout_s=1.0,
            max_attempts=5,
            backoff_base_ms=1,
            backoff_max_ms=2,
        )
        p = OpenAIProvider(cfg, http_client=client)

        with pytest.raises(ProviderError) as e:
            await p.generate(_mk_input())

    assert e.value.kind == ProviderErrorKind.auth
    assert calls["n"] == 1