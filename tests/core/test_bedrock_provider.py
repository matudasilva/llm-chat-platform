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


@pytest.mark.asyncio
async def test_inline_close_before_pull_releases_stream_and_final_waiter() -> None:
    import asyncio

    class EventStream:
        closed = 0
        def __iter__(self):
            return iter([])
        def close(self):
            self.closed += 1

    stream = EventStream()
    client = _FakeBedrockClient(converse_stream_response={"stream": stream})
    provider = BedrockProvider(_provider(), runtime_client=client)
    session = await provider.stream(_provider_input())
    waiter = asyncio.create_task(session.get_final_result())
    await asyncio.gather(session.chunks.aclose(), session.chunks.aclose())
    with pytest.raises(ProviderError, match="incomplete"):
        await waiter
    with pytest.raises(StopAsyncIteration):
        await anext(session.chunks)
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_worker_acquisition_cancellation_closes_late_response_and_client() -> None:
    import asyncio
    import threading

    entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
    class Stream:
        def close(self):
            cleaned.set()
    class Client:
        closed = False
        def converse_stream(self, **kwargs):
            entered.set()
            release.wait()
            return {"stream": Stream()}
        def close(self):
            self.closed = True

    client = Client()
    provider = BedrockProvider(_provider())
    provider._build_client = lambda: client
    task = asyncio.create_task(provider.stream(_provider_input()))
    await asyncio.to_thread(entered.wait)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await asyncio.wait_for(asyncio.to_thread(cleaned.wait), 1)
    for _ in range(100):
        if client.closed:
            break
        await asyncio.sleep(0.001)
    assert client.closed


@pytest.mark.asyncio
async def test_worker_close_before_first_pull_cancels_final_waiter_and_closes_resources() -> None:
    import asyncio
    import threading

    started, release = threading.Event(), threading.Event()
    class Stream:
        closed = False
        def __iter__(self):
            started.set()
            release.wait()
            return iter([])
        def close(self):
            self.closed = True
            release.set()
    class Client:
        closed = False
        def __init__(self):
            self.stream = Stream()
        def converse_stream(self, **kwargs):
            return {"stream": self.stream}
        def close(self):
            self.closed = True
    client = Client()
    provider = BedrockProvider(_provider())
    provider._build_client = lambda: client
    session = await provider.stream(_provider_input())
    waiter = asyncio.create_task(session.get_final_result())
    await session.chunks.aclose()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert client.stream.closed and client.closed


@pytest.mark.asyncio
async def test_inline_close_after_fragment_releases_stream_and_keeps_shared_client() -> None:
    import asyncio

    class Stream:
        closed = 0
        def __iter__(self):
            return iter([{"contentBlockDelta": {"delta": {"text": "one"}}}, {"contentBlockDelta": {"delta": {"text": "two"}}}])
        def close(self):
            self.closed += 1
    class Client(_FakeBedrockClient):
        closed = False
        def close(self):
            self.closed = True
    stream = Stream()
    client = Client(converse_stream_response={"stream": stream})
    session = await BedrockProvider(_provider(), runtime_client=client).stream(_provider_input())
    assert await anext(session.chunks) == "one"
    one = asyncio.create_task(session.get_final_result())
    two = asyncio.create_task(session.get_final_result())
    await asyncio.sleep(0)
    one.cancel()
    with pytest.raises(asyncio.CancelledError):
        await one
    await session.chunks.aclose()
    with pytest.raises(ProviderError, match="incomplete"):
        await two
    assert stream.closed == 1 and not client.closed


@pytest.mark.asyncio
async def test_worker_normal_completion_preserves_final_result_and_closes_resources() -> None:
    class Stream:
        closed = False
        def __iter__(self):
            return iter([{"contentBlockDelta": {"delta": {"text": "ok"}}}])
        def close(self):
            self.closed = True
    class Client:
        closed = False
        def __init__(self):
            self.stream = Stream()
        def converse_stream(self, **kwargs):
            return {"stream": self.stream}
        def close(self):
            self.closed = True
    client = Client()
    provider = BedrockProvider(_provider())
    provider._build_client = lambda: client
    session = await provider.stream(_provider_input())
    assert [part async for part in session.chunks] == ["ok"]
    assert (await session.get_final_result()).content == "ok"
    assert client.stream.closed and client.closed


@pytest.mark.asyncio
async def test_worker_final_waiter_terminates_while_stream_close_stalls() -> None:
    import asyncio
    import threading

    cleanup_started, release = threading.Event(), threading.Event()
    class Stream:
        def __iter__(self):
            release.wait()
            return iter([])
        def close(self):
            cleanup_started.set()
            release.wait()
    class Client:
        def converse_stream(self, **kwargs):
            return {"stream": Stream()}
        def close(self):
            pass
    provider = BedrockProvider(_provider())
    provider._build_client = lambda: Client()
    session = await provider.stream(_provider_input())
    waiter = asyncio.create_task(session.get_final_result())
    closer = asyncio.create_task(session.chunks.aclose())
    await asyncio.wait_for(asyncio.to_thread(cleanup_started.wait), 1)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, 1)
    assert not closer.done()
    release.set()
    await closer


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_worker_client_close_failure_preserves_result_or_provider_error(failure) -> None:
    class Client:
        def converse_stream(self, **kwargs):
            events = ([{"throttlingException": {"message": "private"}}] if failure else
                      [{"contentBlockDelta": {"delta": {"text": "ok"}}}])
            return {"stream": events}
        def close(self):
            raise RuntimeError("client close failed")

    provider = BedrockProvider(_provider())
    provider._build_client = lambda: Client()
    session = await provider.stream(_provider_input())
    chunks = [part async for part in session.chunks]
    if failure:
        assert chunks == []
        with pytest.raises(ProviderError) as exc:
            await session.get_final_result()
        assert exc.value.kind == ProviderErrorKind.rate_limit
    else:
        assert chunks == ["ok"]
        assert (await session.get_final_result()).content == "ok"
