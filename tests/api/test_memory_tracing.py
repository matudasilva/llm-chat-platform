"""ORQ-37 H3/AC3 -- the memory spans, declared since Gate A and never emitted.

`app/core/observability/schema.py` has declared `MEMORY_SPAN_NAMES`
(`memory.assemble`, `memory.rank`) and seven `memory.*` attributes since the
schema was written. Independent validation found **zero call sites**: AC3
requires those two spans, as children of the request span, and nothing ever
opened them.

Design decisions pinned here, both taken deliberately:

* `memory.rank` is opened ONLY when ranking actually happens. AC3 defines
  expected spans as "the stage spans **actually entered**", with the
  conditional `rag.evaluate` as its precedent; an empty out-of-window corpus
  means no ranking occurred.
* **No `memory.outcome` attribute.** It is declared and permitted, but the
  route can override the outcome after these spans have closed
  (`budget_starved`, `current_message_oversized`), so writing it here would
  create a second source of truth that can diverge from the metrics row --
  the stale-telemetry class that H1, N2 and R1 all were. The authoritative
  value stays `rag_request_metrics.memory_outcome`.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api import deps
from app.core.domain.conversation_history import HistoryMessage
from app.core.observability import schema, tracing
from app.http import pipeline_metrics

pytestmark = pytest.mark.asyncio


# --- tracer double, same nesting model as test_tracing_pipeline_stages.py --


class _Span:
    def __init__(self, name: str, parent: "_Span | None") -> None:
        self.name = name
        self.parent = parent
        self.children: list[_Span] = []
        self.attributes: dict[str, object] = {}
        self.exception: BaseException | None = None
        # Independent re-validation found the gap this closes: omitting the
        # close of `memory.rank` left all nine tests green, because nothing
        # recorded whether a span ever ended.
        self.ended = False

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _StackTracer:
    def __init__(self) -> None:
        self.stack: list[_Span] = []
        self.spans: list[_Span] = []
        # Closure ORDER, not just a closed flag. A span left open by the code
        # still gets closed when its `@contextmanager` generator is garbage
        # collected, so `ended` alone can pass by accident -- it did, when the
        # leak mutation was first tried. The order is what a leak actually
        # breaks: an inner span must close before the outer one.
        self.closed_order: list[str] = []

    def start_as_current_span(self, name):
        parent = self.stack[-1] if self.stack else None
        current = _Span(name, parent)
        if parent is not None:
            parent.children.append(current)
        self.spans.append(current)
        tracer = self

        class _CM:
            def __enter__(self):
                tracer.stack.append(current)
                return current

            def __exit__(self, exc_type, exc, tb):
                current.ended = True
                tracer.closed_order.append(current.name)
                current.exception = exc
                tracer.stack.pop()
                return False

        return _CM()

    def names(self) -> list[str]:
        return [s.name for s in self.spans]

    def by_name(self, name: str) -> _Span:
        matches = [s for s in self.spans if s.name == name]
        assert len(matches) == 1, f"expected exactly one {name}, got {len(matches)}: {self.names()}"
        return matches[0]


@pytest.fixture
def tracer():
    double = _StackTracer()
    tracing.configure_for_testing(double)
    tracing.reset_rejected_attribute_keys()
    yield double
    tracing.configure_for_testing(None)
    tracing.reset_rejected_attribute_keys()


@pytest.fixture
def collector():
    instance, token = pipeline_metrics.init_collector(
        request_instance_id=str(uuid.uuid4()), correlation_id=None
    )
    try:
        yield instance
    finally:
        pipeline_metrics.reset_collector(token)


def _install(monkeypatch, history):
    class _Adapter:
        def __init__(self, queries, *, max_rows=None) -> None:
            pass

        async def fetch_ordered(self, conversation_id, tenant_id):
            return history

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(deps, "get_history_sessionmaker", lambda request: object())
    monkeypatch.setattr(deps, "short_lived_history_session", lambda sm: _CM())
    monkeypatch.setattr(deps, "SqlConversationHistoryAdapter", _Adapter)
    monkeypatch.setattr(deps, "ConversationQueryService", lambda db: object())
    monkeypatch.setattr(deps, "get_tenant_id", lambda: "acme")
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 20, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_chars", 20000, raising=False)
    monkeypatch.setattr(
        deps.settings, "chat_prompt_max_added_context_chars", 12000, raising=False
    )


def _turns(*pairs):
    return [
        HistoryMessage(sequence=i, role=role, content=content)
        for i, (role, content) in enumerate(pairs, start=1)
    ]


async def _call(message="the plan"):
    return await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=uuid.uuid4(), message=message),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )


def _under_request_span(tracer, name: str) -> _Span:
    """Open a request span the way `RequestContextMiddleware` does, so the
    child relationship AC3 requires is the one actually asserted."""
    return tracer.by_name(name)


# --- AC3: the two spans exist, under the request span ---------------------


async def test_assemble_span_is_emitted_under_the_request_span(
    tracer, collector, monkeypatch
) -> None:
    _install(monkeypatch, _turns(("user", "u1"), ("assistant", "a1")))
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)

    with tracing.span(schema.REQUEST_SPAN):
        await _call()

    assemble = tracer.by_name("memory.assemble")
    assert assemble.parent is not None
    assert assemble.parent.name == schema.REQUEST_SPAN


async def test_rank_span_is_emitted_in_mode_b_under_the_request_span(
    tracer, collector, monkeypatch
) -> None:
    # Four turns with max_messages=2 leaves an out-of-window corpus to rank.
    _install(
        monkeypatch,
        _turns(
            ("user", "the launch plan"),
            ("assistant", "launch is scheduled"),
            ("user", "anything else"),
            ("assistant", "no"),
        ),
    )
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 2, raising=False)
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)

    with tracing.span(schema.REQUEST_SPAN):
        await _call("launch plan")

    rank = tracer.by_name("memory.rank")
    assert rank.parent is not None
    assert rank.parent.name == schema.REQUEST_SPAN


async def test_no_rank_span_when_the_corpus_is_empty(tracer, collector, monkeypatch) -> None:
    """AC3 counts the spans ACTUALLY ENTERED. An empty out-of-window corpus
    means no ranking happened, so no `memory.rank` -- the same rule
    `rag.evaluate` follows."""
    _install(monkeypatch, _turns(("user", "u1"), ("assistant", "a1")))
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)

    with tracing.span(schema.REQUEST_SPAN):
        await _call()

    assert "memory.assemble" in tracer.names()
    assert "memory.rank" not in tracer.names()


# --- attributes -----------------------------------------------------------


async def test_assemble_span_attributes(tracer, collector, monkeypatch) -> None:
    _install(monkeypatch, _turns(("user", "u1"), ("assistant", "a1")))
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)

    with tracing.span(schema.REQUEST_SPAN):
        await _call()

    attributes = tracer.by_name("memory.assemble").attributes
    assert attributes["memory.mode"] == "A"
    assert attributes["memory.window_turn_count"] == 1  # turns, not messages
    assert attributes["memory.history_truncated"] is False
    assert attributes["memory.history_row_cap_reached"] is False


async def test_rank_span_attributes(tracer, collector, monkeypatch) -> None:
    _install(
        monkeypatch,
        _turns(
            ("user", "the launch plan"),
            ("assistant", "launch is scheduled"),
            ("user", "anything else"),
            ("assistant", "no"),
        ),
    )
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 2, raising=False)
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)

    with tracing.span(schema.REQUEST_SPAN):
        result = await _call("launch plan")

    attributes = tracer.by_name("memory.rank").attributes
    assert attributes["memory.corpus_turn_count"] >= 1
    assert attributes["memory.selected_count"] == len(result.retrieved_events)
    assert tracer.by_name("memory.assemble").attributes["memory.mode"] == "B"


async def test_no_outcome_attribute_is_written(tracer, collector, monkeypatch) -> None:
    """Deliberate omission: the route can still override the outcome after
    these spans close, so writing it here would be a second, divergent source
    of truth for the same fact."""
    _install(monkeypatch, _turns(("user", "u1"), ("assistant", "a1")))
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)

    with tracing.span(schema.REQUEST_SPAN):
        await _call()

    assert "memory.outcome" not in tracer.by_name("memory.assemble").attributes


async def test_every_attribute_emitted_is_allow_listed(tracer, collector, monkeypatch) -> None:
    """AC4 regression guard: the keys these spans write must already be in
    `schema.py`, which declared them before anything emitted them."""
    _install(
        monkeypatch,
        _turns(
            ("user", "the launch plan"),
            ("assistant", "launch is scheduled"),
            ("user", "anything else"),
            ("assistant", "no"),
        ),
    )
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 2, raising=False)
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)

    with tracing.span(schema.REQUEST_SPAN):
        await _call("launch plan")

    for name in ("memory.assemble", "memory.rank"):
        for key in tracer.by_name(name).attributes:
            assert key in schema.ALLOWED_ATTRIBUTE_KEYS, key


# --- AC2: instrumentation must not change behaviour -----------------------


async def test_result_is_identical_with_tracing_off(collector, monkeypatch) -> None:
    _install(monkeypatch, _turns(("user", "u1"), ("assistant", "a1")))
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)

    tracing.configure_for_testing(None)
    without = await _call()

    double = _StackTracer()
    tracing.configure_for_testing(double)
    try:
        with tracing.span(schema.REQUEST_SPAN):
            with_tracing = await _call()
    finally:
        tracing.configure_for_testing(None)

    assert [m.content for m in without.messages] == [m.content for m in with_tracing.messages]
    assert without.truncated == with_tracing.truncated
    assert without.retrieved_events == with_tracing.retrieved_events


async def test_a_raising_tracer_leaves_the_result_intact(collector, monkeypatch) -> None:
    """AC2's rule for the pipeline stages, applied to these two spans: a
    tracer that throws must not be able to change what the dependency
    returns."""
    _install(monkeypatch, _turns(("user", "u1"), ("assistant", "a1")))
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)

    tracing.configure_for_testing(None)
    baseline = await _call()

    class _Exploding:
        def start_as_current_span(self, name):
            raise RuntimeError("tracer down")

    tracing.configure_for_testing(_Exploding())
    try:
        result = await _call()
    finally:
        tracing.configure_for_testing(None)

    assert [m.content for m in result.messages] == [m.content for m in baseline.messages]
    assert result.truncated == baseline.truncated


# --- closure: a span that is opened must be closed ------------------------


async def test_both_spans_are_closed_and_the_stack_unwinds(
    tracer, collector, monkeypatch
) -> None:
    """Independent re-validation of `11372f9` found this gap: omitting the
    close of `memory.rank` left all nine tests green, because nothing asserted
    that a span ever ended. A span left open leaks the current context into
    everything that follows it in the request."""
    _install(
        monkeypatch,
        _turns(
            ("user", "the launch plan"),
            ("assistant", "launch is scheduled"),
            ("user", "anything else"),
            ("assistant", "no"),
        ),
    )
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 2, raising=False)
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)

    with tracing.span(schema.REQUEST_SPAN):
        await _call("launch plan")

    assert tracer.by_name("memory.assemble").ended is True
    assert tracer.by_name("memory.rank").ended is True
    # Nothing left current: every span opened in this request has unwound.
    assert tracer.stack == []
    # Structure, stated exactly. The two memory spans are SIBLINGS, not
    # nested: `memory.assemble` closes after the first pass at the hard cap,
    # and the Mode B block that opens `memory.rank` runs after that. Both
    # close before the REQUEST span containing them.
    #
    # **This does NOT detect a leaked span, and saying so matters.** An
    # earlier version of this comment claimed it did. Measured instead of
    # assumed: with `memory.rank` opened via `__enter__()` and never exited,
    # this assertion still passes, because CPython finalizes the
    # `@contextmanager` generator by refcount as soon as the local leaves
    # scope -- which happens before the request span closes. The test that
    # actually catches that mutation is
    # `test_a_ranking_failure_closes_rank_with_its_exception`: a span the
    # code never exits cannot record the exception that passed through it.
    assert tracer.closed_order == ["memory.assemble", "memory.rank", "request"], (
        tracer.closed_order
    )


async def test_assemble_closes_even_when_the_read_degrades(
    tracer, collector, monkeypatch
) -> None:
    """The failure paths must not leak an open span either."""
    _install(monkeypatch, _turns(("user", "u1"), ("assistant", "a1")))
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)

    def _unconfigured(request):
        from app.infra.db.session import OperationalDatabaseNotConfigured

        raise OperationalDatabaseNotConfigured("not configured")

    monkeypatch.setattr(deps, "get_history_sessionmaker", _unconfigured)

    with tracing.span(schema.REQUEST_SPAN):
        result = await _call()

    assert result.is_empty
    assert tracer.by_name("memory.assemble").ended is True
    assert tracer.stack == []


async def test_a_ranking_failure_closes_rank_with_its_exception(
    tracer, collector, monkeypatch
) -> None:
    """The commit claims a ranking failure closes `memory.rank` with its
    exception BEFORE H9's boundary degrades. Re-validation verified that in
    HEAD; nothing pinned it."""
    _install(
        monkeypatch,
        _turns(
            ("user", "the launch plan"),
            ("assistant", "launch is scheduled"),
            ("user", "anything else"),
            ("assistant", "no"),
        ),
    )
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 2, raising=False)
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)

    boom = RuntimeError("ranking exploded")

    def _explode(events, query):
        raise boom

    monkeypatch.setattr(deps, "rank_events", _explode)

    with tracing.span(schema.REQUEST_SPAN):
        result = await _call("launch plan")

    rank = tracer.by_name("memory.rank")
    assert rank.ended is True
    assert rank.exception is boom, "the span must see the failure, not a degraded no-op"
    assert tracer.stack == []
    # And H9's boundary still degraded: window kept, evidence dropped.
    assert result.messages != ()
    assert result.retrieved_events == ()
    assert collector.snapshot()["memory_outcome"] == "error"
