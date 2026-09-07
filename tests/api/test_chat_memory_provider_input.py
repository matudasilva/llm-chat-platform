"""ORQ-37 T9 — memory reaching (and NOT reaching) the provider (AC12).

The point of this file is the asymmetry between the two paths:

    non-streaming   ownership guard `chat.py:265-267`  ->  provider `:296`
    streaming       provider        `chat.py:117`      ->  ownership guard `:141-143`

On the streaming path the provider is invoked **26 lines before** ownership is
checked. A correct HTTP 200 carrying the SSE `error/not_found` frame therefore
proves nothing about whether another tenant's memory reached the model, which
is why AC12 requires a `ProviderInput` capture and requires the two paths to be
asserted separately.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

import app.api.routes.chat as chat_routes
from app.core.domain.chat_memory import ChatMemoryContext
from app.core.domain.chat_service import ChatServiceStreamSession, StreamChatResult
from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.provider import ProviderResult
from app.core.domain.types import ChatMessage
from app.schemas.chat import ChatRequest

pytestmark = pytest.mark.asyncio

FOREIGN_CONVERSATION = uuid.uuid4()


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Session:
    """Owns no conversation, so the route's guard answers not-found."""

    def __init__(self) -> None:
        self.objects: list[object] = []

    def begin(self):
        return _Transaction()

    def add(self, obj) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        return None


class _CapturingChatService:
    """Records exactly what the route handed the provider layer."""

    def __init__(self) -> None:
        self.run_messages: list[ChatMessage] | None = None
        self.stream_messages: list[ChatMessage] | None = None

    async def run(self, *, request_id, messages, provider_metadata=None):
        self.run_messages = list(messages)
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=ChatMessage(role="assistant", content="answer"),
            provider_result=ProviderResult(
                content="answer",
                provider="stub",
                model_version="stub-v1",
                prompt_version="v1",
            ),
        )

    async def stream_chat(self, *, request_id, messages, provider_metadata=None):
        self.stream_messages = list(messages)

        async def chunks() -> AsyncIterator[str]:
            yield "answer"

        async def final() -> StreamChatResult:
            return StreamChatResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content="answer"),
                provider_result=None,
            )

        return ChatServiceStreamSession(chunks=chunks(), get_final_result=final)


class _Cache:
    def __init__(self) -> None:
        self.bypasses: list[str] = []

    async def get(self, **kwargs):
        return None

    async def set(self, **kwargs):
        return None

    def log_bypass(self, *, reason):
        self.bypasses.append(reason)


async def _events(response) -> list[tuple[str, str]]:
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)
    events, current = [], None
    for line in body.splitlines():
        if line.startswith("event: "):
            current = line.removeprefix("event: ")
        elif line.startswith("data: ") and current is not None:
            events.append((current, line.removeprefix("data: ")))
            current = None
    return events


def _memory() -> ChatMemoryContext:
    return ChatMemoryContext(
        messages=(
            ChatMessage(role="user", content="OTHER TENANT SECRET"),
            ChatMessage(role="assistant", content="OTHER TENANT REPLY"),
        )
    )


@pytest.fixture
def memory_on(monkeypatch):
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", True)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: _Cache())


# --- AC12: cross-tenant, both paths asserted SEPARATELY -------------------


async def test_non_streaming_cross_tenant_returns_404_and_never_calls_provider(
    memory_on,
) -> None:
    from fastapi import HTTPException

    service = _CapturingChatService()
    with pytest.raises(HTTPException) as excinfo:
        await chat_routes.chat(
            ChatRequest(message="question", conversation_id=FOREIGN_CONVERSATION),
            db=_Session(),
            chat_service=service,
            memory_context=ChatMemoryContext(),
        )
    assert excinfo.value.status_code == 404
    # The guard precedes the provider on this path, so nothing was sent at all.
    assert service.run_messages is None


async def test_streaming_cross_tenant_returns_200_with_error_frame(memory_on) -> None:
    service = _CapturingChatService()
    response = await chat_routes.chat(
        ChatRequest(message="question", conversation_id=FOREIGN_CONVERSATION, stream=True),
        db=_Session(),
        chat_service=service,
        memory_context=ChatMemoryContext(),
    )
    assert response.status_code == 200
    events = await _events(response)
    assert any(name == "error" and "not_found" in data for name, data in events)
    # Never a 500, and never a real 404 -- that would break the SSE contract.
    assert response.status_code != 500


async def test_streaming_cross_tenant_sent_no_memory_to_the_provider(memory_on) -> None:
    """The assertion the response cannot make.

    The dependency returned empty memory (it caught `ConversationNotFoundError`
    at the port), so even though the provider ran BEFORE the guard, nothing of
    the other tenant's conversation was in the prompt.
    """
    service = _CapturingChatService()
    response = await chat_routes.chat(
        ChatRequest(message="question", conversation_id=FOREIGN_CONVERSATION, stream=True),
        db=_Session(),
        chat_service=service,
        memory_context=ChatMemoryContext(),
    )
    await _events(response)

    assert service.stream_messages is not None, "provider ran before the guard, as expected"
    assert [(m.role, m.content) for m in service.stream_messages] == [
        ("user", "question")
    ]


async def test_a_leaking_dependency_would_be_caught_on_the_streaming_path(
    memory_on,
) -> None:
    """Proves the previous test is not vacuous.

    If the dependency ever returned foreign memory instead of empty, it WOULD
    reach the provider on the streaming path -- the route guard cannot stop it.
    This is the failure mode AC12 exists to detect.
    """
    service = _CapturingChatService()
    response = await chat_routes.chat(
        ChatRequest(message="question", conversation_id=FOREIGN_CONVERSATION, stream=True),
        db=_Session(),
        chat_service=service,
        memory_context=_memory(),
    )
    await _events(response)
    contents = [m.content for m in service.stream_messages]
    assert "OTHER TENANT SECRET" in contents, (
        "the capture must be able to observe a leak, otherwise the "
        "no-leak assertion proves nothing"
    )


# --- integration into ProviderInput on both paths -------------------------


async def test_non_streaming_carries_memory_as_prior_turns(memory_on) -> None:
    service = _CapturingChatService()
    await chat_routes.chat(
        ChatRequest(message="current"),
        db=_Session(),
        chat_service=service,
        memory_context=_memory(),
    )
    assert [(m.role, m.content) for m in service.run_messages] == [
        ("user", "OTHER TENANT SECRET"),
        ("assistant", "OTHER TENANT REPLY"),
        ("user", "current"),
    ]


async def test_streaming_carries_memory_as_prior_turns(memory_on) -> None:
    service = _CapturingChatService()
    response = await chat_routes.chat(
        ChatRequest(message="current", stream=True),
        db=_Session(),
        chat_service=service,
        memory_context=_memory(),
    )
    await _events(response)
    assert [(m.role, m.content) for m in service.stream_messages] == [
        ("user", "OTHER TENANT SECRET"),
        ("assistant", "OTHER TENANT REPLY"),
        ("user", "current"),
    ]


async def test_current_message_is_always_last(memory_on) -> None:
    service = _CapturingChatService()
    await chat_routes.chat(
        ChatRequest(message="current"),
        db=_Session(),
        chat_service=service,
        memory_context=_memory(),
    )
    assert service.run_messages[-1] == ChatMessage(role="user", content="current")


# --- fail-closed ----------------------------------------------------------


async def test_flag_off_drops_memory_even_if_a_dependency_supplies_it(monkeypatch) -> None:
    # The rollout guarantee: an override cannot inject memory while the flag
    # is off. This mirrors the RAG channel's reset at chat.py:79-82.
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", False)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: _Cache())
    service = _CapturingChatService()
    await chat_routes.chat(
        ChatRequest(message="current"),
        db=_Session(),
        chat_service=service,
        memory_context=_memory(),
    )
    assert [(m.role, m.content) for m in service.run_messages] == [("user", "current")]


async def test_non_context_value_is_reset(memory_on) -> None:
    # Direct unit calls bypass FastAPI dependency resolution entirely.
    service = _CapturingChatService()
    await chat_routes.chat(
        ChatRequest(message="current"),
        db=_Session(),
        chat_service=service,
        memory_context=object(),  # type: ignore[arg-type]
    )
    assert [(m.role, m.content) for m in service.run_messages] == [("user", "current")]


async def test_default_parameter_needs_no_memory_argument(memory_on) -> None:
    # Callers that predate this ORQ must keep working unchanged.
    service = _CapturingChatService()
    await chat_routes.chat(
        ChatRequest(message="current"),
        db=_Session(),
        chat_service=service,
    )
    assert [(m.role, m.content) for m in service.run_messages] == [("user", "current")]
