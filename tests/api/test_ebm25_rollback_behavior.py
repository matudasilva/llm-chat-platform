"""ORQ-37 T19 — Mode A resumes cleanly after Mode B, no residual state (AC21).

The "no data removed" half of AC21 for the LIVE path: nothing Mode B touches
needs cleanup when the flag flips off, because nothing outside this one
request's own `ChatMemoryContext` was ever written to. This runs Mode B first
(as if it had been live), then flips the flag off on the SAME conversation
fixture, and asserts the second call is indistinguishable from a Mode A run
that had never seen the flag on -- proving statelessness, not just a
byte-identical prompt in isolation (T18 already covers that).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api import deps
from app.api.deps import get_chat_memory_context
from app.core.domain.conversation_history import HistoryMessage
from app.http import pipeline_metrics

pytestmark = pytest.mark.asyncio

TENANT = "acme"
CONVERSATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

FIXTURE = [
    HistoryMessage(sequence=1, role="system", content="off-window fox trivia"),
    HistoryMessage(sequence=2, role="user", content="u1"),
    HistoryMessage(sequence=3, role="assistant", content="a1"),
]


class _Payload(SimpleNamespace):
    pass


def _payload(message: str = "fox") -> _Payload:
    return _Payload(conversation_id=CONVERSATION_ID, message=message)


def _request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def _install_source(monkeypatch):
    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            return FIXTURE

    class _Session:
        pass

    class _CM:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(deps, "get_history_sessionmaker", lambda request: object())
    monkeypatch.setattr(deps, "short_lived_history_session", lambda sm: _CM())
    monkeypatch.setattr(deps, "SqlConversationHistoryAdapter", _Adapter)
    monkeypatch.setattr(deps, "ConversationQueryService", lambda db: object())
    monkeypatch.setattr(deps, "get_tenant_id", lambda: TENANT)


@pytest.fixture(autouse=True)
def _memory_on(monkeypatch):
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)


async def test_mode_a_resumes_cleanly_after_a_mode_b_request() -> None:
    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    try:
        # 1) Mode B is live: evidence is selected.
        monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
        _install_source(monkeypatch)
        instance, token = pipeline_metrics.init_collector(request_instance_id=str(uuid.uuid4()))
        try:
            on = await get_chat_memory_context(_payload(), _request())
        finally:
            pipeline_metrics.reset_collector(token)
        assert on.retrieved_events, "the fixture must produce Mode B evidence, or this proves nothing"

        # 2) Rollback: flip the flag off. No migration, no data removal -- the
        # SAME conversation, re-read from scratch.
        monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)
        _install_source(monkeypatch)
        instance2, token2 = pipeline_metrics.init_collector(request_instance_id=str(uuid.uuid4()))
        try:
            off = await get_chat_memory_context(_payload(), _request())
        finally:
            pipeline_metrics.reset_collector(token2)
    finally:
        monkeypatch.undo()

    assert off.retrieved_events == ()
    assert off.provider_metadata is None
    # The window itself is identical to what Mode B's own request carried --
    # rollback did not corrupt or alter the recent-window term either.
    assert off.messages == on.messages


async def test_a_fresh_mode_a_only_run_matches_the_post_rollback_one(monkeypatch) -> None:
    """Control: a request that never saw Mode B must look identical to the
    post-rollback one -- otherwise "clean" rollback would be unverifiable."""
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)
    _install_source(monkeypatch)
    instance, token = pipeline_metrics.init_collector(request_instance_id=str(uuid.uuid4()))
    try:
        never_on = await get_chat_memory_context(_payload(), _request())
    finally:
        pipeline_metrics.reset_collector(token)

    assert never_on.retrieved_events == ()
    assert never_on.provider_metadata is None
    assert [(m.role, m.content) for m in never_on.messages] == [("user", "u1"), ("assistant", "a1")]
