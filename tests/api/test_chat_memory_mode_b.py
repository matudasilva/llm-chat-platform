"""ORQ-37 T18 — Mode B wiring: `ebm25_enabled`, the two inert states, and
AC16's byte-identity/toggle clauses.

Uses the same `_install_source` seam pattern as `test_chat_memory_dependency.py`:
the double replaces only the port (`fetch_ordered`), so the real assembler,
partition builder, packer, ranking and selection all run for real.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api import deps
from app.api.deps import get_chat_memory_context
from app.core.domain.chat_memory import ChatMemoryContext
from app.core.domain.conversation_history import HistoryMessage
from app.http import pipeline_metrics

pytestmark = pytest.mark.asyncio

TENANT = "acme"
CONVERSATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _Payload(SimpleNamespace):
    pass


def _payload(message: str = "question about foxes", conversation_id=CONVERSATION_ID):
    return _Payload(conversation_id=conversation_id, message=message)


def _request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


@pytest.fixture
def collector():
    instance, token = pipeline_metrics.init_collector(
        request_instance_id=str(uuid.uuid4()), correlation_id=None
    )
    try:
        yield instance
    finally:
        pipeline_metrics.reset_collector(token)


@pytest.fixture
def memory_on(monkeypatch):
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps, "get_tenant_id", lambda: TENANT)


def _install_source(monkeypatch, messages):
    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            return messages

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


def _messages(*pairs):
    return [
        HistoryMessage(sequence=index, role=role, content=content)
        for index, (role, content) in enumerate(pairs, start=1)
    ]


# --- flag off: exactly Gate B1's behaviour, unchanged -----------------------


async def test_flag_off_never_populates_retrieved_events(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)
    _install_source(
        monkeypatch,
        _messages(("system", "off-window fox trivia"), ("user", "u1"), ("assistant", "a1")),
    )
    result = await get_chat_memory_context(_payload(), _request())
    assert result.retrieved_events == ()
    assert result.provider_metadata is None


async def test_flag_off_never_records_a_mode_b_outcome(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)
    # A fixture that WOULD be an empty corpus under Mode B -- entirely inside
    # the window -- must still record the ordinary B1 outcome, not
    # `no_out_of_window_corpus`, since Mode B never runs at all.
    _install_source(monkeypatch, _messages(("user", "u1"), ("assistant", "a1")))
    await get_chat_memory_context(_payload(), _request())
    assert collector.snapshot()["memory_outcome"] == "ok"
    assert "ebm25_selected_count" not in collector.snapshot()


# --- flag on: the two inert states -------------------------------------


async def test_empty_corpus_records_no_out_of_window_corpus(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    # Every unit is well-formed and inside the window: nothing excluded.
    _install_source(monkeypatch, _messages(("user", "u1"), ("assistant", "a1")))
    result = await get_chat_memory_context(_payload(), _request())
    assert result.retrieved_events == ()
    assert collector.snapshot()["memory_outcome"] == "no_out_of_window_corpus"
    assert collector.snapshot()["ebm25_selected_count"] == 0


async def test_budget_starved_when_the_window_consumes_the_whole_cap(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 20, raising=False)
    _install_source(
        monkeypatch,
        _messages(
            ("system", "off-window evidence about foxes"),  # -> corpus
            ("user", "x" * 10), ("assistant", "y" * 10),      # -> window, fills the cap
        ),
    )
    result = await get_chat_memory_context(_payload(message="foxes"), _request())
    assert result.retrieved_events == ()
    assert collector.snapshot()["memory_outcome"] == "budget_starved"
    assert collector.snapshot()["ebm25_selected_count"] == 0
    # The window itself is untouched by the starvation -- it took its full,
    # protected share; evidence is what disappeared.
    assert sum(len(m.content) for m in result.messages) == 20


async def test_successful_selection_populates_retrieved_events(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    _install_source(
        monkeypatch,
        _messages(
            ("system", "off-window fox trivia"),
            ("user", "u1"), ("assistant", "a1"),
        ),
    )
    result = await get_chat_memory_context(_payload(message="fox"), _request())
    assert [e.content for e in result.retrieved_events] == ["off-window fox trivia"]
    assert collector.snapshot()["memory_outcome"] == "ok"  # the window's own outcome, untouched
    assert collector.snapshot()["ebm25_selected_count"] == 1


async def test_provider_metadata_is_populated_when_events_are_selected(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    _install_source(
        monkeypatch,
        _messages(("system", "off-window fox trivia"), ("user", "u1"), ("assistant", "a1")),
    )
    result = await get_chat_memory_context(_payload(message="fox"), _request())
    assert result.provider_metadata == {
        "memory": {
            "schema_version": "rag-memory-v1",
            "events": [{"event_id": 1, "content": "off-window fox trivia"}],
        }
    }


# --- AC20: gold event selected, distractor excluded -------------------------


async def test_gold_event_is_selected_and_distractor_is_not(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    # A budget that fits exactly one of the two candidates: with BM25_TOP_K=5
    # and only two corpus events, an unconstrained budget would admit both,
    # proving nothing about ranking. The tight cap is what forces a genuine
    # choice, so the distractor's absence is evidence of ranking, not of
    # having run out of room for everything.
    monkeypatch.setattr(deps.settings, "chat_prompt_max_added_context_chars", 50, raising=False)
    _install_source(
        monkeypatch,
        _messages(
            ("system", "irrelevant distractor about weather patterns"),
            ("system", "the secret password is xyzzyfox42"),  # gold: matches the query
            ("user", "u1"), ("assistant", "a1"),
        ),
    )
    result = await get_chat_memory_context(
        _payload(message="what is the secret password xyzzyfox42"), _request()
    )
    contents = [e.content for e in result.retrieved_events]
    assert "the secret password is xyzzyfox42" in contents
    assert "irrelevant distractor about weather patterns" not in contents


# --- window is protected, not squeezed --------------------------------------


async def test_window_content_is_identical_regardless_of_the_flag(
    memory_on, collector, monkeypatch
) -> None:
    messages = _messages(
        ("system", "off-window evidence"), ("user", "u1"), ("assistant", "a1")
    )

    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)
    _install_source(monkeypatch, messages)
    off = await get_chat_memory_context(_payload(), _request())

    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    _install_source(monkeypatch, messages)
    on = await get_chat_memory_context(_payload(), _request())

    assert off.messages == on.messages
    assert off.truncated == on.truncated


# --- degraded paths never attempt Mode B ------------------------------------


async def test_first_turn_records_no_mode_b_outcome(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    result = await get_chat_memory_context(_payload(conversation_id=None), _request())
    assert result.retrieved_events == ()
    assert collector.snapshot()["memory_outcome"] == "skipped_first_turn"
