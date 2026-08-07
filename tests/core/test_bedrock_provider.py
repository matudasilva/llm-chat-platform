from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.domain.provider import ProviderInput, ProviderStreamSession
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.domain.chat_service import ChatService
from app.core.domain.errors import ProviderExecutionError
from app.core.domain.types import ChatMessage
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
async def test_bedrock_provider_stream_returns_session_and_final_metadata(caplog) -> None:
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

    caplog.set_level("INFO")
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
    complete_record = next(
        record for record in caplog.records if getattr(record, "event", None) == "provider.stream.complete"
    )
    assert complete_record.provider == "bedrock"
    assert complete_record.stream is True


@pytest.mark.asyncio
async def test_bedrock_provider_maps_generate_and_stream_errors(caplog) -> None:
    generate_client = _FakeBedrockClient(
        converse_responses=[
            _FakeBedrockException("AccessDeniedException", "forbidden", 403),
        ]
    )
    generate_provider = BedrockProvider(_provider(), runtime_client=generate_client)

    caplog.set_level("INFO")
    with pytest.raises(ProviderError) as generate_exc:
        await generate_provider.generate(_provider_input())

    assert generate_exc.value.kind == ProviderErrorKind.auth
    assert generate_exc.value.error_code == "AccessDeniedException"
    generate_error_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "provider.error" and getattr(record, "stream", False) is False
    )
    assert generate_error_record.error_kind == "auth"
    assert generate_error_record.failure_kind == "auth"

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
    stream_error_record = next(
        record for record in caplog.records if getattr(record, "event", None) == "provider.stream.error"
    )
    assert stream_error_record.error_kind == "rate_limit"
    assert stream_error_record.failure_kind == "rate_limit"


@pytest.mark.asyncio
async def test_bedrock_error_message_cannot_leak_rag_content_through_chat_service(caplog) -> None:
    sentinel = "tenant-corpus-secret-do-not-log"
    client = _FakeBedrockClient(
        converse_responses=[
            _FakeBedrockException("ValidationException", sentinel, 400),
        ]
    )
    provider = BedrockProvider(_provider(), runtime_client=client)
    service = ChatService(provider, timeout_s=1.0)
    metadata = {
        "rag": {
            "schema_version": "rag-generation-v1",
            "sources": [
                {
                    "citation": "S1",
                    "document_id": str(uuid4()),
                    "chunk_id": str(uuid4()),
                    "rank": 1,
                    "truncated": False,
                    "content": sentinel,
                }
            ],
        }
    }

    caplog.set_level("INFO")
    with pytest.raises(ProviderExecutionError) as exc_info:
        await service.run(
            request_id=uuid4(),
            messages=[ChatMessage(role="user", content="question")],
            provider_metadata=metadata,
        )

    assert str(exc_info.value) == "provider request failed"
    for record in caplog.records:
        assert sentinel not in record.getMessage()
        assert all(sentinel not in str(value) for value in vars(record).values())


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
