"""ORQ-37 T18 — AC16's remaining clauses: the flag toggle and the frozen B1 baseline.

Runs the REAL `get_chat_memory_context` dependency (not a hand-built
`ChatMemoryContext`) through the REAL route, toggling only `ebm25_enabled`,
so the diff is over what actually reaches `ProviderInput` -- not over a
context object a test constructed by hand.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

import app.api.routes.chat as chat_routes
from app.api import deps
from app.core.domain.chat_service import ChatServiceStreamSession, StreamChatResult
from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.conversation_history import HistoryMessage
from app.core.domain.provider import ProviderResult
from app.core.domain.types import ChatMessage
from app.schemas.chat import ChatRequest

pytestmark = pytest.mark.asyncio

TENANT = "acme"
CONVERSATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Session:
    def __init__(self, tenant_id: str = TENANT) -> None:
        self.objects: list[object] = []
        self._tenant_id = tenant_id

    def begin(self):
        return _Transaction()

    def add(self, obj) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        from types import SimpleNamespace

        return SimpleNamespace(tenant_id=self._tenant_id)


class _CapturingChatService:
    def __init__(self) -> None:
        self.run_messages: list[ChatMessage] | None = None
        self.run_metadata: dict | None = None

    async def run(self, *, request_id, messages, provider_metadata=None):
        self.run_messages = list(messages)
        self.run_metadata = provider_metadata
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=ChatMessage(role="assistant", content="answer"),
            provider_result=ProviderResult(
                content="answer", provider="stub", model_version="v1", prompt_version="v1",
            ),
        )

    async def stream_chat(self, *, request_id, messages, provider_metadata=None):
        self.run_messages = list(messages)
        self.run_metadata = provider_metadata

        async def chunks() -> AsyncIterator[str]:
            yield "answer"

        async def final() -> StreamChatResult:
            return StreamChatResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content="answer"),
                provider_result=None,
            )

        return ChatServiceStreamSession(chunks=chunks(), get_final_result=final)


class _NullCache:
    async def get(self, **kwargs):
        return None

    async def set(self, **kwargs):
        return None

    def log_bypass(self, **kwargs):
        return None


def _messages(*pairs):
    return [
        HistoryMessage(sequence=index, role=role, content=content)
        for index, (role, content) in enumerate(pairs, start=1)
    ]


def _install_history(monkeypatch, messages):
    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            return messages

    class _HistorySession:
        pass

    class _CM:
        async def __aenter__(self):
            return _HistorySession()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(deps, "get_history_sessionmaker", lambda request: object())
    monkeypatch.setattr(deps, "short_lived_history_session", lambda sm: _CM())
    monkeypatch.setattr(deps, "SqlConversationHistoryAdapter", _Adapter)
    monkeypatch.setattr(deps, "ConversationQueryService", lambda db: object())
    monkeypatch.setattr(deps, "get_tenant_id", lambda: TENANT)


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", False)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: _NullCache())
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", True)
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(chat_routes, "get_tenant_id", lambda: TENANT)


async def _run(monkeypatch, *, ebm25: bool, messages, question: str = "fox") -> _CapturingChatService:
    from types import SimpleNamespace

    from app.api.deps import get_chat_memory_context

    monkeypatch.setattr(deps.settings, "ebm25_enabled", ebm25, raising=False)
    _install_history(monkeypatch, messages)

    payload = ChatRequest(message=question, conversation_id=CONVERSATION_ID)
    # `Depends(get_chat_memory_context)` only resolves through FastAPI's own
    # request cycle; a direct call to `chat_routes.chat(...)` bypasses that
    # entirely and chat.py's own fail-closed reset (chat.py:85) then resets
    # memory_context to empty. Calling the dependency explicitly here, and
    # passing its result through, is what actually exercises T18's wiring.
    memory_context = await get_chat_memory_context(
        payload, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    )

    service = _CapturingChatService()
    await chat_routes.chat(
        payload,
        request=object(),
        db=_Session(),
        chat_service=service,
        memory_context=memory_context,
    )
    return service


FIXTURE = _messages(
    ("system", "off-window fox trivia"),
    ("user", "u1"), ("assistant", "a1"),
)


# --- the toggle changes ONLY the memory metadata key ------------------------


async def test_toggling_only_ebm25_enabled_changes_only_the_memory_key(monkeypatch) -> None:
    off = await _run(monkeypatch, ebm25=False, messages=FIXTURE)
    on = await _run(monkeypatch, ebm25=True, messages=FIXTURE)

    # The messages list -- provider, current message, recent-window turns --
    # is untouched by the flag; only `metadata["memory"]` may differ.
    assert off.run_messages == on.run_messages
    assert (off.run_metadata or {}).get("rag") == (on.run_metadata or {}).get("rag")
    assert (off.run_metadata or {}).get("memory") is None
    assert (on.run_metadata or {}).get("memory") is not None


async def test_flag_off_prompt_is_byte_identical_to_the_b1_baseline(monkeypatch) -> None:
    """The materialized window (T10), turn-snapped and well-formedness-filtered,
    IS the B1 baseline (§Diseño 8). With the flag off this must be exactly what
    Gate B1 already shipped -- no memory envelope, no change to the window."""
    off = await _run(monkeypatch, ebm25=False, messages=FIXTURE)
    # No memory envelope: the off-window "system" row never reaches the model
    # in ANY form when the flag is off.
    assert off.run_metadata is None or "memory" not in off.run_metadata
    assert [(m.role, m.content) for m in off.run_messages] == [
        ("user", "u1"),
        ("assistant", "a1"),
        ("user", "fox"),
    ]


async def test_flag_on_assembled_set_differs_from_mode_a(monkeypatch) -> None:
    off = await _run(monkeypatch, ebm25=False, messages=FIXTURE)
    on = await _run(monkeypatch, ebm25=True, messages=FIXTURE)
    assert off.run_metadata != on.run_metadata
