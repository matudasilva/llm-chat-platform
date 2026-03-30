# tests/core/test_openai_provider_logging.py

import uuid

import httpx
import pytest

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig


def _mk_input() -> ProviderInput:
    class _Msg:
        def __init__(self, role: str, content: str) -> None:
            self.role = role
            self.content = content

    return ProviderInput(
        request_id=str(uuid.uuid4()),
        messages=[_Msg("user", "hi")],
    )


@pytest.mark.asyncio
async def test_provider_logs_retry_and_response(caplog):
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
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

        caplog.set_level("INFO")
        out = await p.generate(_mk_input())

    assert out.content == "ok"
    assert calls["n"] == 2

    # Supports either message-based logs or structured extra["event"] logs.
    messages = [r.message for r in caplog.records]
    events = [getattr(r, "event", None) for r in caplog.records]

    assert any(("provider.retry" in (m or "")) for m in messages) or any(e == "provider.retry" for e in events)
    assert any(("provider.response" in (m or "")) for m in messages) or any(e == "provider.response" for e in events)
    total_record = next(record for record in caplog.records if getattr(record, "event", None) == "provider.total")
    assert total_record.attempts_used == 2
    assert total_record.final_provider == "openai"
    assert total_record.fallback_used is False


@pytest.mark.asyncio
async def test_provider_logs_error_on_auth(caplog):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "nope"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.openai.com") as client:
        cfg = OpenAIProviderConfig(
            api_key="x",
            model="gpt-test",
            timeout_s=1.0,
            max_attempts=1,
            backoff_base_ms=0,
            backoff_max_ms=0,
        )
        p = OpenAIProvider(cfg, http_client=client)

        caplog.set_level("INFO")
        with pytest.raises(ProviderError) as e:
            await p.generate(_mk_input())

    assert e.value.kind == ProviderErrorKind.auth

    messages = [r.message for r in caplog.records]
    events = [getattr(r, "event", None) for r in caplog.records]

    assert any(("provider.error" in (m or "")) for m in messages) or any(e == "provider.error" for e in events)
    error_record = next(record for record in caplog.records if getattr(record, "event", None) == "provider.error")
    assert error_record.error_kind == "auth"
    assert error_record.failure_kind == "auth"
