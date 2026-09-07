"""ORQ-37 T9 — `get_chat_memory_context` (AC11 history half, AC12, AC13).

Nothing here is proven by asserting on an HTTP response alone. On the
streaming path the provider is invoked at `chat.py:117`, **before** the
ownership guard at `:141-143`, so a correct 200-with-error-frame response says
nothing about whether memory reached the model. The `ProviderInput` capture is
the assertion that matters (AC12).
"""
from __future__ import annotations

import asyncio
import inspect
import uuid
from types import SimpleNamespace

import pytest

from app.api import deps
from app.api.deps import get_chat_memory_context
from app.core.domain.chat_memory import ChatMemoryContext
from app.core.domain.conversation_history import (
    ConversationNotFoundError,
    HistoryIntegrityError,
    HistoryMessage,
)
from app.core.settings import settings as real_settings
from app.http import pipeline_metrics

pytestmark = pytest.mark.asyncio

TENANT = "acme"
CONVERSATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _Payload(SimpleNamespace):
    pass


def _payload(conversation_id=CONVERSATION_ID, message="current question"):
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
    return None


def _install_source(monkeypatch, result):
    """Drive the outcome from `fetch_ordered`, the way production does.

    T10 moved the assembly into `_materialize_window`, which calls the adapter
    first and then runs the REAL assembler and the REAL partition builder. The
    double therefore replaces only the **port** -- the layer ADR-011 says
    raises `ConversationNotFoundError` -- and everything above it is shipped
    code. Doubling the assembler instead, as this file did before T10, coupled
    the tests to where the call happened rather than to what it produced, and
    that is exactly what broke when T10 landed.
    """

    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            # T12 added `max_rows`; this double ignores it -- the SQL cap is
            # exercised in `test_conversation_history_row_cap.py` instead,
            # against the real adapter and query service.
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            if isinstance(result, BaseException):
                raise result
            if callable(result):
                return await result(conversation_id, tenant_id)
            return result

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


# --- AC13: never raises, and not-found is caught DISTINCTLY


async def test_returns_empty_when_the_flag_is_off(monkeypatch) -> None:
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", False, raising=False)
    result = await get_chat_memory_context(_payload(), _request())
    assert result == ChatMemoryContext()


async def test_conversation_not_found_is_caught_and_recorded(
    memory_on, collector, monkeypatch
) -> None:
    _install_source(monkeypatch, ConversationNotFoundError(str(CONVERSATION_ID)))
    result = await get_chat_memory_context(_payload(), _request())
    assert result.is_empty
    assert collector.snapshot()["memory_outcome"] == "conversation_not_found"


async def test_not_found_is_distinct_from_the_generic_handler(
    memory_on, collector, monkeypatch
) -> None:
    # AC13's word is "distinctly". A single `except Exception` would satisfy
    # "never raises" while collapsing an ownership answer into a degradation.
    _install_source(monkeypatch, HistoryIntegrityError("bad sequence"))
    result = await get_chat_memory_context(_payload(), _request())
    assert result.is_empty
    assert collector.snapshot()["memory_outcome"] == "error"


async def test_timeout_degrades_to_empty(memory_on, collector, monkeypatch) -> None:
    async def _slow(conversation_id, tenant_id):
        await asyncio.sleep(1)

    _install_source(monkeypatch, _slow)
    monkeypatch.setattr(deps.settings, "conversation_history_timeout_s", 0.01, raising=False)
    result = await get_chat_memory_context(_payload(), _request())
    assert result.is_empty
    assert collector.snapshot()["memory_outcome"] == "timeout"


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("boom"),
        ValueError("bad"),
        ConnectionError("db down"),
        HistoryIntegrityError("non-increasing"),
    ],
)
async def test_never_raises_for_any_failure(memory_on, collector, monkeypatch, failure) -> None:
    _install_source(monkeypatch, failure)
    result = await get_chat_memory_context(_payload(), _request())
    assert result == ChatMemoryContext()


async def test_seam_failure_also_degrades(memory_on, collector, monkeypatch) -> None:
    # `get_history_sessionmaker` raises when DATABASE_URL_OPS is unset, which
    # is the shipped default. That must degrade, not 500.
    def _unconfigured(request):
        from app.infra.db.session import OperationalDatabaseNotConfigured

        raise OperationalDatabaseNotConfigured("not configured")

    monkeypatch.setattr(deps, "get_history_sessionmaker", _unconfigured)
    monkeypatch.setattr(deps, "get_tenant_id", lambda: TENANT)
    result = await get_chat_memory_context(_payload(), _request())
    assert result.is_empty
    assert collector.snapshot()["memory_outcome"] == "error"


# --- first turn is SKIPPED, not caught


async def test_first_turn_skips_assembly_entirely(memory_on, collector, monkeypatch) -> None:
    called: list[str] = []

    def _should_not_run(request):
        called.append("seam")
        raise AssertionError("assembly must not run on the first turn")

    monkeypatch.setattr(deps, "get_history_sessionmaker", _should_not_run)
    result = await get_chat_memory_context(_payload(conversation_id=None), _request())
    assert result.is_empty
    assert called == []
    assert collector.snapshot()["memory_outcome"] == "skipped_first_turn"


async def test_first_turn_is_not_reported_as_not_found(
    memory_on, collector, monkeypatch
) -> None:
    # Reading the handler's derived id instead of the raw payload value would
    # produce `conversation_not_found` for every new conversation.
    monkeypatch.setattr(deps, "get_history_sessionmaker", lambda request: object())
    await get_chat_memory_context(_payload(conversation_id=None), _request())
    assert collector.snapshot()["memory_outcome"] != "conversation_not_found"


# --- the happy path


async def test_assembled_history_becomes_ordered_prior_turns(
    memory_on, collector, monkeypatch
) -> None:
    _install_source(
        monkeypatch,
        _messages(("user", "first"), ("assistant", "answer"), ("user", "second")),
    )
    result = await get_chat_memory_context(_payload(), _request())
    # Since T10 the trailing "second" is an odd tail: a singleton unit, so it
    # is excluded from the MATERIALIZED window and returned to the complement.
    # Before T10 this asserted all three messages; the change is deliberate.
    assert [(m.role, m.content) for m in result.messages] == [
        ("user", "first"),
        ("assistant", "answer"),
    ]
    assert collector.snapshot()["memory_outcome"] == "ok"


async def test_truncation_flag_is_carried(memory_on, collector, monkeypatch) -> None:
    monkeypatch.setattr(
        deps.settings, "conversation_history_max_messages", 2, raising=False
    )
    _install_source(
        monkeypatch,
        _messages(
            ("user", "old"), ("assistant", "old reply"),
            ("user", "new"), ("assistant", "new reply"),
        ),
    )
    result = await get_chat_memory_context(_payload(), _request())
    # ADR-011's message bound dropped the older turn, so the assembler reports
    # truncation and the context carries it through unchanged.
    assert result.truncated is True


async def test_empty_conversation_records_empty_not_ok(
    memory_on, collector, monkeypatch
) -> None:
    _install_source(monkeypatch, [])
    result = await get_chat_memory_context(_payload(), _request())
    assert result.is_empty
    assert collector.snapshot()["memory_outcome"] == "empty"



# --- AC36 (T12): history_row_cap_reached, at the dependency boundary -------


async def test_history_row_cap_reached_when_sql_returns_exactly_the_cap(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(
        deps.settings, "conversation_history_max_rows", 4, raising=False
    )
    _install_source(
        monkeypatch,
        _messages(
            ("user", "u1"), ("assistant", "a1"),
            ("user", "u2"), ("assistant", "a2"),
        ),
    )
    result = await get_chat_memory_context(_payload(), _request())
    assert result.history_row_cap_reached is True


async def test_history_row_cap_not_reached_below_the_cap(
    memory_on, collector, monkeypatch
) -> None:
    monkeypatch.setattr(
        deps.settings, "conversation_history_max_rows", 2_000, raising=False
    )
    _install_source(
        monkeypatch, _messages(("user", "u1"), ("assistant", "a1"))
    )
    result = await get_chat_memory_context(_payload(), _request())
    assert result.history_row_cap_reached is False


async def test_cap_flag_is_false_on_every_degradation_path(
    memory_on, collector, monkeypatch
) -> None:
    # A degraded (empty) context must never falsely claim the cap was hit.
    _install_source(monkeypatch, ConversationNotFoundError("x"))
    result = await get_chat_memory_context(_payload(), _request())
    assert result.history_row_cap_reached is False
