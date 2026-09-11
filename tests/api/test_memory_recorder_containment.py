"""ORQ-37 N-2 -- a failing telemetry sink must not reach the business path.

N-2, from the H9 re-validation: `_record_ebm25_selected_count` was called from
three sites INSIDE Mode B's degradation boundary and once more from the
boundary's own `except` handler (`deps.py:289`). A recorder that failed
persistently therefore escaped the dependency, violating the §Diseño 7 contract
that this function never raises -- the same shape as N-1's 500. With a
single-shot failure the handler recorded `error`/0 over a selection that had
actually succeeded, and `_record_memory_outcome` was called from outside every
boundary at all.

Two things these tests are NOT:

* They are not a reproduction of a production failure. The guard that contains
  ordinary sink errors is on the collector METHOD
  (`PipelineMetricsCollector.record`, `pipeline_metrics.py:47-52`); the
  module-level `pipeline_metrics.record` has none of its own and simply
  delegates to it. Containment therefore holds for the shipped wiring, which
  installs that class -- so N-2 is a latent defect of the boundary, reachable
  only by substituting the sink. That substitution is the seam used below, and
  nothing more is claimed for it.
* They do not pin "no telemetry is ever lost", nor the converse. A write that
  raises BEFORE storing its value is lost, and
  `test_a_telemetry_failure_does_not_downgrade_a_successful_selection` asserts
  that loss rather than papering over it. A sink that stores and then raises
  keeps what it stored: these guards suppress the exception, they do not
  revert a write.

What they do pin is the separation: a telemetry failure changes telemetry, and
it changes nothing else. Valid evidence is never discarded to report a metrics
fault, and no outcome is rewritten to `error` because its own recording threw.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.api import deps
from app.core.domain.conversation_history import HistoryMessage
from app.http import pipeline_metrics


class _HostileCollector:
    """A sink that raises on selected keys, standing in for the real collector.

    Substituted into `_collector_var` directly rather than through
    `init_collector`, which only builds the real class. Accepting the private
    name here is deliberate: the ContextVar *is* the seam the production code
    reads through, so this exercises the same lookup a request does.
    """

    __slots__ = ("_fields", "_fail_keys", "_once", "_raises", "calls",
                 "request_instance_id", "correlation_id")

    def __init__(
        self,
        *,
        fail_keys: set[str],
        once: bool = False,
        raises: type[BaseException] = RuntimeError,
    ) -> None:
        self._fields: dict[str, object] = {}
        self._fail_keys = fail_keys
        self._once = once
        self._raises = raises
        self.calls: list[dict[str, object]] = []
        self.request_instance_id = str(uuid.uuid4())
        self.correlation_id = None

    def record(self, **fields: object) -> None:
        self.calls.append(dict(fields))
        if self._fail_keys & set(fields):
            if self._once:
                self._fail_keys = set()
            raise self._raises("metrics sink down")
        self._fields.update(fields)

    def snapshot(self) -> dict[str, object]:
        return dict(self._fields)


def _install_collector(collector: _HostileCollector):
    return pipeline_metrics._collector_var.set(collector)


def _install_history(monkeypatch, history) -> None:
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


@pytest.fixture
def mode_b_on(monkeypatch):
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 2, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_chars", 20000, raising=False)
    monkeypatch.setattr(
        deps.settings, "chat_prompt_max_added_context_chars", 12000, raising=False
    )
    monkeypatch.setattr(deps, "get_tenant_id", lambda: "acme")
    return None


def _request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def _payload(message: str):
    return SimpleNamespace(conversation_id=uuid.uuid4(), message=message)


_SELECTABLE_HISTORY = [
    HistoryMessage(sequence=1, role="user", content="the plan for launch"),
    HistoryMessage(sequence=2, role="assistant", content="launch is scheduled"),
    HistoryMessage(sequence=3, role="user", content="anything else"),
    HistoryMessage(sequence=4, role="assistant", content="no"),
]

_PUNCTUATION_HISTORY = [
    HistoryMessage(sequence=1, role="user", content="!!!"),
    HistoryMessage(sequence=2, role="assistant", content="???"),
    HistoryMessage(sequence=3, role="user", content="what is the plan"),
    HistoryMessage(sequence=4, role="assistant", content="the plan is ready"),
]


# --- Claim 1: a failing recorder must not escape the dependency ------------


@pytest.mark.asyncio
async def test_a_failing_recorder_does_not_escape_the_dependency(
    mode_b_on, monkeypatch
) -> None:
    """Everything raises. The dependency must still return a usable context.

    Before the fix this propagated out of `get_chat_memory_context`, which the
    route has no handler for: a 500 caused purely by telemetry.
    """
    collector = _HostileCollector(fail_keys={"ebm25_selected_count", "memory_outcome"})
    token = _install_collector(collector)
    try:
        _install_history(monkeypatch, _SELECTABLE_HISTORY)

        result = await deps.get_chat_memory_context(_payload("launch plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)

    # The window is intact and the selection survived: telemetry failing is not
    # a reason to hand the model less context.
    assert [m.content for m in result.messages] == ["anything else", "no"]
    assert len(result.retrieved_events) == 1
    # Nothing landed. This says only that -- an empty snapshot is not evidence
    # about how many writes were attempted, which `calls` below is.
    assert collector.snapshot() == {}
    assert [set(c) for c in collector.calls] == [
        {"ebm25_selected_count"},
        {"memory_outcome"},
    ]


@pytest.mark.asyncio
async def test_a_persistently_failing_recorder_inside_a_real_degradation_does_not_escape(
    mode_b_on, monkeypatch
) -> None:
    """`deps.py:289` -- the recorder call that is itself unprotected.

    A punctuation-only corpus makes `rank_events` raise for real (H9), so the
    boundary's handler runs. The handler's own `_record_ebm25_selected_count(0)`
    then raises inside the `except`, and an exception raised there has nothing
    left to catch it: a degradation the boundary had successfully absorbed
    turned back into a 500 on its way out.

    Note the ordering this history produces: ranking fails BEFORE any recorder
    call in the `try`, so the single attempt below is the handler's. The
    literal double call needs a selection to succeed first, and is pinned in
    `test_a_telemetry_failure_does_not_downgrade_a_successful_selection`.
    """
    collector = _HostileCollector(fail_keys={"ebm25_selected_count"})
    token = _install_collector(collector)
    try:
        _install_history(monkeypatch, _PUNCTUATION_HISTORY)

        result = await deps.get_chat_memory_context(_payload("plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)

    # The genuine H9 degradation still happened, and is still reported.
    assert [m.content for m in result.messages] == ["what is the plan", "the plan is ready"]
    assert result.retrieved_events == ()
    assert collector.snapshot()["memory_outcome"] == "error"
    # The handler still attempts its write, and still loses it.
    assert [c for c in collector.calls if "ebm25_selected_count" in c] == [
        {"ebm25_selected_count": 0},
    ]


@pytest.mark.asyncio
async def test_a_failing_outcome_recorder_does_not_escape_the_dependency(
    mode_b_on, monkeypatch
) -> None:
    """`_record_memory_outcome` sat outside every boundary, on both modes.

    Mode A, so the Mode B block is skipped entirely and the only recorder call
    is the unconditional one at the end of the function.
    """
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)
    collector = _HostileCollector(fail_keys={"memory_outcome"})
    token = _install_collector(collector)
    try:
        _install_history(monkeypatch, _SELECTABLE_HISTORY)

        result = await deps.get_chat_memory_context(_payload("launch plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)

    assert [m.content for m in result.messages] == ["anything else", "no"]
    assert result.retrieved_events == ()
    assert collector.snapshot() == {}


# --- Claim 2: a telemetry failure changes telemetry and nothing else ------


@pytest.mark.asyncio
async def test_a_telemetry_failure_does_not_downgrade_a_successful_selection(
    mode_b_on, monkeypatch
) -> None:
    """The selection succeeded; only recording it failed.

    Before the fix the handler reported `error` with `selected_count=0` over a
    context that was carrying the evidence -- telemetry describing a failure
    that did not occur. The evidence is kept, per the authorised reading of
    Claim 2: valid evidence is not discarded to report a metrics fault.

    The count itself is genuinely lost, and asserted as lost. Swallowing a
    failed write does not recover its value.
    """
    collector = _HostileCollector(fail_keys={"ebm25_selected_count"}, once=True)
    token = _install_collector(collector)
    try:
        _install_history(monkeypatch, _SELECTABLE_HISTORY)

        result = await deps.get_chat_memory_context(_payload("launch plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)

    assert len(result.retrieved_events) == 1
    assert collector.snapshot()["memory_outcome"] == "ok"
    assert "ebm25_selected_count" not in collector.snapshot()
    # This is the literal double call of N-2: before the fix the failing write
    # at `deps.py:280` dropped into the handler, which called the same helper
    # again at `:289` -- two attempts, the second contradicting the first with
    # a zero. Now the handler never runs, so there is exactly one.
    assert [c for c in collector.calls if "ebm25_selected_count" in c] == [
        {"ebm25_selected_count": 1},
    ]


@pytest.mark.asyncio
async def test_a_telemetry_failure_does_not_mask_an_empty_corpus(
    mode_b_on, monkeypatch
) -> None:
    """§Diseño 8's first inert state must survive its own recorder failing."""
    collector = _HostileCollector(fail_keys={"ebm25_selected_count"}, once=True)
    token = _install_collector(collector)
    try:
        # One turn only: the window covers the whole conversation, so there is
        # no out-of-window corpus to retrieve from.
        _install_history(
            monkeypatch,
            [
                HistoryMessage(sequence=1, role="user", content="anything else"),
                HistoryMessage(sequence=2, role="assistant", content="no"),
            ],
        )

        result = await deps.get_chat_memory_context(_payload("launch plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)

    assert result.retrieved_events == ()
    assert collector.snapshot()["memory_outcome"] == "no_out_of_window_corpus"


@pytest.mark.asyncio
async def test_a_telemetry_failure_does_not_mask_budget_starvation(
    mode_b_on, monkeypatch
) -> None:
    """§Diseño 8's second inert state, likewise.

    The cap is set so the window fits WITHOUT truncation -- otherwise R1's
    `packed.truncated` branch would record `budget_starved` on its own and the
    test would pass for the wrong reason -- but leaves too little room for any
    ranked event.
    """
    monkeypatch.setattr(
        deps.settings, "chat_prompt_max_added_context_chars", 20, raising=False
    )
    collector = _HostileCollector(fail_keys={"ebm25_selected_count"}, once=True)
    token = _install_collector(collector)
    try:
        _install_history(monkeypatch, _SELECTABLE_HISTORY)

        result = await deps.get_chat_memory_context(_payload("launch plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)

    # R1's branch reports `budget_starved` too, so the outcome alone would not
    # tell the two apart. What separates them is `packed.truncated`, which
    # `pack_recent_window` sets only when it actually drops or shortens a turn:
    # the window here arrives whole and under the cap, so that flag is False
    # and the outcome below can only be Mode B's.
    #
    # `result.truncated` is NOT that flag -- it is True because history exists
    # outside the window at all, which is the precondition for this test.
    assert [m.content for m in result.messages] == ["anything else", "no"]
    assert sum(len(m.content) for m in result.messages) <= 20
    assert result.retrieved_events == ()
    assert collector.snapshot()["memory_outcome"] == "budget_starved"


# --- The line the guard must NOT cross ------------------------------------
#
# `except Exception` is the whole point: it contains an ordinary telemetry
# fault and stops there. `CancelledError` derives from `BaseException` (since
# Python 3.8), so the guard as written already lets it through -- but nothing
# in the fix *states* that, and independent re-validation found that widening
# both guards to `except BaseException` left all seven earlier tests green.
#
# That is precisely the H5 trap: `dbc374d` fixed cancellation propagation
# through the transaction-release guard, and an `except BaseException: pass`
# sitting in a test hid the fix for a full round. These two tests pin the
# boundary so the same widening cannot pass unnoticed here.
#
# `KeyboardInterrupt` and `SystemExit` follow from the same hierarchy and are
# not tested separately: one `BaseException` that must survive is enough to
# kill the widening mutation, and cancellation is the one the request path
# actually depends on.


@pytest.mark.asyncio
async def test_a_cancelled_request_is_not_swallowed_by_the_count_guard(
    mode_b_on, monkeypatch
) -> None:
    """A cancellation arriving through the sink must reach the caller."""
    collector = _HostileCollector(
        fail_keys={"ebm25_selected_count"}, raises=asyncio.CancelledError
    )
    token = _install_collector(collector)
    try:
        _install_history(monkeypatch, _SELECTABLE_HISTORY)

        with pytest.raises(asyncio.CancelledError):
            await deps.get_chat_memory_context(_payload("launch plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)


@pytest.mark.asyncio
async def test_a_cancelled_request_is_not_swallowed_by_the_outcome_guard(
    mode_b_on, monkeypatch
) -> None:
    """The same, for the writer whose calls sit outside every boundary.

    Mode A, so the only recorder call is the unconditional one at the end.
    """
    monkeypatch.setattr(deps.settings, "ebm25_enabled", False, raising=False)
    collector = _HostileCollector(
        fail_keys={"memory_outcome"}, raises=asyncio.CancelledError
    )
    token = _install_collector(collector)
    try:
        _install_history(monkeypatch, _SELECTABLE_HISTORY)

        with pytest.raises(asyncio.CancelledError):
            await deps.get_chat_memory_context(_payload("launch plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)


# --- The boundary it must not weaken --------------------------------------


@pytest.mark.asyncio
async def test_a_genuine_mode_b_failure_still_degrades_with_a_healthy_sink(
    mode_b_on, monkeypatch
) -> None:
    """Regression guard: containing the recorder must not contain H9's boundary.

    A computation failure is still a failure -- it must still drop the
    evidence, keep the window and report `error`.
    """
    collector = _HostileCollector(fail_keys=set())
    token = _install_collector(collector)
    try:
        _install_history(monkeypatch, _PUNCTUATION_HISTORY)

        result = await deps.get_chat_memory_context(_payload("plan"), _request())
    finally:
        pipeline_metrics.reset_collector(token)

    assert [m.content for m in result.messages] == ["what is the plan", "the plan is ready"]
    assert result.retrieved_events == ()
    assert collector.snapshot()["memory_outcome"] == "error"
    assert collector.snapshot()["ebm25_selected_count"] == 0
