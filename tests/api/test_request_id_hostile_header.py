"""ORQ-37 N-1 -- a client-controlled `X-Request-ID` must not 500 `/chat`.

`RequestContextMiddleware` puts the inbound header into `_request_id_var`
verbatim -- it decodes with `errors="replace"`, strips, and says so in its own
comment: "`request_id_s` above may be arbitrary client text". AC25 documents
that as deliberate: the header is correlation metadata, accepted as sent.

Three call sites then converted it with `uuid.UUID(rid)` **outside any
degradation boundary**:

    app/api/routes/chat.py   the route body, unconditional
    app/api/deps.py          get_chat_memory_context, before its try
    app/api/deps.py          get_chat_rag_context, before its try

So `X-Request-ID: not-a-uuid` answered 500 on every `/chat` request, on both
paths, **with both feature flags off** -- no Mode B, no history, no RAG
needed. Found by independent re-validation while refuting H9's universal
"never raises" claim, and registered as N-1 rather than fixed there.

The fix drops a malformed value and mints a fresh UUID, which is the rule
AC32 already applies to the telemetry correlation id. What it does NOT do is
sanitise the client's string: the header keeps travelling verbatim in the
context var and in the response, because that is AC25's decision and this is
not the task to revisit it.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.api.routes.chat as chat_routes
from app.api import deps
from app.http import request_context
from app.schemas.chat import ChatRequest

pytestmark = pytest.mark.asyncio

HOSTILE = "not-a-uuid"


@pytest.fixture
def hostile_header():
    tokens = request_context.set_request_context(HOSTILE, HOSTILE)
    try:
        yield HOSTILE
    finally:
        request_context.reset_request_context(*tokens)


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def begin(self):
        return _Transaction()

    def add(self, obj) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        return None


class _Cache:
    async def get(self, **kwargs):
        return None

    async def set(self, **kwargs):
        return None

    def log_bypass(self, *, reason):
        return None


@pytest.fixture
def shipped_defaults(monkeypatch):
    """Both channels off -- the shipped default, and the configuration that
    makes this a 500 on the plain endpoint rather than a Mode B edge case."""
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", False)
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", False)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: _Cache())
    return None


# --- the route must answer, not raise -------------------------------------


async def test_non_streaming_survives_a_hostile_request_id(
    hostile_header, shipped_defaults
) -> None:
    from app.core.domain.chat_types import ChatServiceResult
    from app.core.domain.provider import ProviderResult
    from app.core.domain.types import ChatMessage

    class _Service:
        async def run(self, *, request_id, messages, provider_metadata=None):
            # The derived UUID must be a real UUID, whatever the client sent.
            assert isinstance(request_id, uuid.UUID)
            return ChatServiceResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content="answer"),
                provider_result=ProviderResult(
                    content="answer", provider="stub", model_version="v1", prompt_version="v1"
                ),
            )

    response = await chat_routes.chat(
        ChatRequest(message="q"), db=_Session(), chat_service=_Service()
    )
    assert response.assistant_content == "answer"
    assert response.status.value == "success"
    # The response carries a real UUID, minted because the client's was not one.
    assert isinstance(response.request_id, uuid.UUID) or uuid.UUID(str(response.request_id))


async def test_streaming_survives_a_hostile_request_id(
    hostile_header, shipped_defaults
) -> None:
    from collections.abc import AsyncIterator

    from app.core.domain.chat_service import ChatServiceStreamSession, StreamChatResult
    from app.core.domain.types import ChatMessage

    class _Service:
        async def stream_chat(self, *, request_id, messages, provider_metadata=None):
            assert isinstance(request_id, uuid.UUID)

            async def chunks() -> AsyncIterator[str]:
                yield "token"

            async def final() -> StreamChatResult:
                return StreamChatResult(
                    request_id=request_id,
                    assistant_message=ChatMessage(role="assistant", content="token"),
                    provider_result=None,
                )

            return ChatServiceStreamSession(chunks=chunks(), get_final_result=final)

    response = await chat_routes.chat(
        ChatRequest(message="q", stream=True), db=_Session(), chat_service=_Service()
    )
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)
    assert "event: token" in body
    assert "event: done" in body


# --- the two dependencies must degrade, not raise (AC13, invariant 7) -----


async def test_memory_dependency_does_not_raise_on_a_hostile_request_id(
    hostile_header, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps, "get_tenant_id", lambda: "acme")

    # No operational sessionmaker: the read degrades. The point is that it
    # degrades rather than raising before it ever gets there.
    result = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=uuid.uuid4(), message="q"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )
    assert result.is_empty


async def test_rag_dependency_does_not_raise_on_a_hostile_request_id(
    hostile_header, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "chat_rag_augmentation_enabled", True, raising=False)

    result = await deps.get_chat_rag_context(
        SimpleNamespace(conversation_id=uuid.uuid4(), message="q"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )
    assert result.sources == ()


# --- a valid header keeps its meaning -------------------------------------


async def test_a_valid_header_still_becomes_that_exact_uuid() -> None:
    """The regression guard. Dropping malformed values must not also drop
    correlation for the well-behaved caller."""
    valid = uuid.uuid4()
    tokens = request_context.set_request_context(str(valid), str(valid))
    try:
        assert request_context.request_uuid() == valid
    finally:
        request_context.reset_request_context(*tokens)


@pytest.mark.parametrize(
    "hostile",
    ["not-a-uuid", "", "   ", "x" * 8192, "\x00\x01control", "12345", "null"],
)
async def test_hostile_values_yield_a_fresh_uuid_instead_of_raising(hostile) -> None:
    tokens = request_context.set_request_context(hostile, hostile)
    try:
        first = request_context.request_uuid()
        second = request_context.request_uuid()
    finally:
        request_context.reset_request_context(*tokens)

    assert isinstance(first, uuid.UUID)
    assert isinstance(second, uuid.UUID)
    # Minted, not derived: two calls cannot agree on a value that was never
    # a UUID, which is what distinguishes "dropped" from "coerced".
    assert first != second


async def test_the_client_string_still_travels_verbatim(hostile_header) -> None:
    """AC25's decision is untouched: this task stops deriving a UUID from
    client text, it does not sanitise the correlation the client sent."""
    assert request_context.get_request_id() == HOSTILE
