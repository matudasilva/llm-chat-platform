from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.domain.provider import ProviderInput, ProviderStreamSession
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.providers.bedrock_provider import BedrockProvider, BedrockProviderConfig


class _FakeBedrockException(Exception):
    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.response = {
            "Error": {
                "Code": code,
                "Message": message,
            },
            "ResponseMetadata": {
                "HTTPStatusCode": http_status,
            },
        }


class _FakeBedrockConnectTimeoutError(Exception):
    pass


@dataclass
class _FakeBedrockClient:
    converse_responses: list[object] | None = None
    converse_stream_response: dict | None = None

    def __post_init__(self) -> None:
        self.converse_responses = list(self.converse_responses or [])
        self.converse_calls: list[dict] = []
        self.converse_stream_calls: list[dict] = []
        self.closed = False

    def converse(self, **kwargs):
        self.converse_calls.append(kwargs)
        response = self.converse_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def converse_stream(self, **kwargs):
        self.converse_stream_calls.append(kwargs)
        if isinstance(self.converse_stream_response, Exception):
            raise self.converse_stream_response
        return self.converse_stream_response

    def close(self) -> None:
        self.closed = True


def _provider() -> BedrockProviderConfig:
    return BedrockProviderConfig(
        region="us-east-1",
        model="anthropic.claude-3-haiku-20240307-v1:0",
        prompt_version="bedrock-prompt-v1",
        timeout_s=1.0,
        max_attempts=3,
        backoff_base_ms=0,
        backoff_max_ms=0,
    )


def _provider_input() -> ProviderInput:
    return ProviderInput(
        request_id=uuid4(),
        messages=[
            SimpleNamespace(role="system", content="be concise"),
            SimpleNamespace(role="user", content="hi"),
        ],
        temperature=0.2,
        max_tokens=128,
    )


@pytest.mark.asyncio
async def test_bedrock_provider_generate_normalizes_content_usage_and_payload() -> None:
    client = _FakeBedrockClient(
        converse_responses=[
            {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "hello from bedrock"}],
                    }
                },
                "usage": {
                    "inputTokens": 11,
                    "outputTokens": 7,
                    "totalTokens": 18,
                },
                "metrics": {
                    "latencyMs": 19,
                },
            }
        ]
    )
    provider = BedrockProvider(_provider(), runtime_client=client)

    out = await provider.generate(_provider_input())

    assert out.provider == "bedrock"
    assert out.model_version == "anthropic.claude-3-haiku-20240307-v1:0"
    assert out.prompt_version == "bedrock-prompt-v1"
    assert out.content == "hello from bedrock"
    assert out.input_tokens == 11
    assert out.output_tokens == 7
    assert out.total_tokens == 18
    assert out.latency_ms == 19
    assert client.converse_calls[0]["system"] == [{"text": "be concise"}]
    assert client.converse_calls[0]["messages"] == [
        {
            "role": "user",
            "content": [{"text": "hi"}],
        }
    ]
    assert client.converse_calls[0]["inferenceConfig"] == {
        "temperature": 0.2,
        "maxTokens": 128,
    }


@pytest.mark.asyncio
async def test_bedrock_provider_stream_returns_session_and_final_metadata() -> None:
    client = _FakeBedrockClient(
        converse_stream_response={
            "stream": [
                {"messageStart": {"role": "assistant"}},
                {"contentBlockDelta": {"delta": {"text": "hel"}}},
                {"contentBlockDelta": {"delta": {"text": "lo"}}},
                {"messageStop": {"stopReason": "end_turn"}},
                {
                    "metadata": {
                        "usage": {
                            "inputTokens": 11,
                            "outputTokens": 7,
                            "totalTokens": 18,
                        },
                        "metrics": {
                            "latencyMs": 33,
                        },
                    }
                },
            ]
        }
    )
    provider = BedrockProvider(_provider(), runtime_client=client)

    session = await provider.stream(_provider_input())

    assert isinstance(session, ProviderStreamSession)

    chunks: list[str] = []
    async for chunk in session.chunks:
        chunks.append(chunk)

    final_result = await session.get_final_result()

    assert chunks == ["hel", "lo"]
    assert final_result.content == "hello"
    assert final_result.provider_result.provider == "bedrock"
    assert final_result.provider_result.model_version == "anthropic.claude-3-haiku-20240307-v1:0"
    assert final_result.provider_result.prompt_version == "bedrock-prompt-v1"
    assert final_result.provider_result.input_tokens == 11
    assert final_result.provider_result.output_tokens == 7
    assert final_result.provider_result.total_tokens == 18
    assert final_result.provider_result.latency_ms == 33


@pytest.mark.asyncio
async def test_bedrock_provider_maps_generate_and_stream_errors() -> None:
    generate_client = _FakeBedrockClient(
        converse_responses=[
            _FakeBedrockException("AccessDeniedException", "forbidden", 403),
        ]
    )
    generate_provider = BedrockProvider(_provider(), runtime_client=generate_client)

    with pytest.raises(ProviderError) as generate_exc:
        await generate_provider.generate(_provider_input())

    assert generate_exc.value.kind == ProviderErrorKind.auth
    assert generate_exc.value.error_code == "AccessDeniedException"

    stream_client = _FakeBedrockClient(
        converse_stream_response={
            "stream": [
                {"throttlingException": {"message": "slow down"}},
            ]
        }
    )
    stream_provider = BedrockProvider(_provider(), runtime_client=stream_client)
    session = await stream_provider.stream(_provider_input())

    with pytest.raises(ProviderError) as stream_exc:
        async for _ in session.chunks:
            pass
        await session.get_final_result()

    assert stream_exc.value.kind == ProviderErrorKind.rate_limit
    assert stream_exc.value.error_code == "throttlingException"


@pytest.mark.asyncio
async def test_bedrock_provider_normalizes_stream_startup_timeout_for_runtime_client() -> None:
    client = _FakeBedrockClient(
        converse_stream_response=_FakeBedrockConnectTimeoutError("timed out"),
    )
    provider = BedrockProvider(_provider(), runtime_client=client)

    with pytest.raises(ProviderError) as exc:
        await provider.stream(_provider_input())

    assert exc.value.kind == ProviderErrorKind.timeout
    assert exc.value.retryable is True
