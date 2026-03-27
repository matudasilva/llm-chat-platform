from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from fastapi.responses import StreamingResponse

from app.api.routes.chat import chat
from app.core.domain.chat_service import ChatService
from app.core.domain.provider import (
    ProviderInput,
    ProviderPort,
    ProviderResult,
    ProviderStreamResult,
    ProviderStreamSession,
)
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.providers.resilient_provider import ResilientProvider
from app.schemas.chat import ChatRequest


def _retryable_error() -> ProviderError:
    return ProviderError(
        kind=ProviderErrorKind.upstream,
        message="provider upstream error",
        provider="bedrock",
        retryable=True,
    )


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


@dataclass
class FakeStreamSession:
    chunks_to_yield: list[str] = field(default_factory=list)
    final_result: ProviderStreamResult | None = None
    final_error: Exception | None = None

    @property
    def chunks(self) -> AsyncIterator[str]:
        async def _chunks() -> AsyncIterator[str]:
            for chunk in self.chunks_to_yield:
                yield chunk

        return _chunks()

    async def get_final_result(self) -> ProviderStreamResult:
        if self.final_error is not None:
            raise self.final_error
        assert self.final_result is not None
        return self.final_result


@dataclass
class ScriptedProvider(ProviderPort):
    provider_name: str
    generate_actions: list[object] = field(default_factory=list)
    stream_actions: list[object] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.generate_calls = 0
        self.stream_calls = 0

    async def generate(self, input: ProviderInput) -> ProviderResult:
        self.generate_calls += 1
        if not self.generate_actions:
            return _provider_result(provider=self.provider_name, content=f"{self.provider_name} generate")
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


class FakeAsyncSession:
    def __init__(self) -> None:
        self.items: list[object] = []

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def add(self, obj: object) -> None:
        self.items.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        return None


def _build_stream_result(*, provider: str, content: str) -> ProviderStreamResult:
    return ProviderStreamResult(
        content=content,
        provider_result=_provider_result(provider=provider, content=content),
    )


async def _collect_sse_events(response: StreamingResponse) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    body_parts: list[str] = []

    assert response.media_type == "text/event-stream"

    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            body_parts.append(chunk.decode())
        else:
            body_parts.append(str(chunk))

    current_event: str | None = None
    for line in "".join(body_parts).splitlines():
        if not line:
            continue
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ").strip()
            continue
        if line.startswith("data: ") and current_event is not None:
            raw_data = line.removeprefix("data: ").strip()
            if current_event == "token":
                events.append((current_event, raw_data))
            else:
                events.append((current_event, json.loads(raw_data)))

    return events


@pytest.mark.asyncio
async def test_chat_streaming_succeeds_without_fallback() -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        stream_actions=[
            FakeStreamSession(
                chunks_to_yield=["hel", "lo"],
                final_result=_build_stream_result(provider="bedrock", content="hello"),
            )
        ],
    )
    fallback = ScriptedProvider(provider_name="openai")
    chat_service = ChatService(
        provider=ResilientProvider(primary=primary, fallback=fallback),
        timeout_s=1.0,
    )
    response = await chat(
        ChatRequest(message="hello", stream=True),
        db=FakeAsyncSession(),
        chat_service=chat_service,
    )
    events = await _collect_sse_events(response)

    assert [event for event, _ in events] == ["token", "token", "done"]
    assert "".join(payload for event, payload in events if event == "token") == "hello"
    done_payload = next(payload for event, payload in events if event == "done")
    assert "conversation_id" in done_payload
    assert "request_id" in done_payload
    assert primary.stream_calls == 1
    assert fallback.stream_calls == 0


@pytest.mark.asyncio
async def test_chat_streaming_falls_back_before_first_token() -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        stream_actions=[
            FakeStreamSession(final_error=_retryable_error()),
        ],
    )
    fallback = ScriptedProvider(
        provider_name="openai",
        stream_actions=[
            FakeStreamSession(
                chunks_to_yield=["fall", "back"],
                final_result=_build_stream_result(provider="openai", content="fallback"),
            )
        ],
    )
    chat_service = ChatService(
        provider=ResilientProvider(primary=primary, fallback=fallback),
        timeout_s=1.0,
    )
    response = await chat(
        ChatRequest(message="hello", stream=True),
        db=FakeAsyncSession(),
        chat_service=chat_service,
    )
    events = await _collect_sse_events(response)

    assert [event for event, _ in events] == ["token", "token", "done"]
    assert "".join(payload for event, payload in events if event == "token") == "fallback"
    assert primary.stream_calls == 1
    assert fallback.stream_calls == 1


@pytest.mark.asyncio
async def test_chat_streaming_does_not_fall_back_after_first_token() -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        stream_actions=[
            FakeStreamSession(
                chunks_to_yield=["par"],
                final_error=_retryable_error(),
            )
        ],
    )
    fallback = ScriptedProvider(
        provider_name="openai",
        stream_actions=[
            FakeStreamSession(
                chunks_to_yield=["unused"],
                final_result=_build_stream_result(provider="openai", content="unused"),
            )
        ],
    )
    chat_service = ChatService(
        provider=ResilientProvider(primary=primary, fallback=fallback),
        timeout_s=1.0,
    )
    response = await chat(
        ChatRequest(message="hello", stream=True),
        db=FakeAsyncSession(),
        chat_service=chat_service,
    )
    events = await _collect_sse_events(response)

    assert [event for event, _ in events] == ["token", "error"]
    assert events[0][1] == "par"
    error_payload = events[1][1]
    assert error_payload["error_kind"] == "upstream"
    assert error_payload["retryable"] is True
    assert primary.stream_calls == 1
    assert fallback.stream_calls == 0


@pytest.mark.asyncio
async def test_chat_streaming_propagates_terminal_error_after_partial_emission() -> None:
    primary = ScriptedProvider(
        provider_name="bedrock",
        stream_actions=[
            FakeStreamSession(
                chunks_to_yield=["he", "llo"],
                final_error=_retryable_error(),
            )
        ],
    )
    fallback = ScriptedProvider(provider_name="openai")
    chat_service = ChatService(
        provider=ResilientProvider(primary=primary, fallback=fallback),
        timeout_s=1.0,
    )
    response = await chat(
        ChatRequest(message="hello", stream=True),
        db=FakeAsyncSession(),
        chat_service=chat_service,
    )
    events = await _collect_sse_events(response)

    assert [event for event, _ in events] == ["token", "token", "error"]
    assert "".join(payload for event, payload in events if event == "token") == "hello"
    error_payload = events[-1][1]
    assert error_payload["error_kind"] == "upstream"
    assert error_payload["retryable"] is True
