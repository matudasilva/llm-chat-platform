"""ORQ-37 T14 — the per-request metrics write site (AC18, AC25, AC9/AC34/AC11
metrics halves).

`_write_rag_request_metrics` and its wiring into both `/chat` paths. AC18's
p95/cost comparison thresholds need a live Gate B2 corpus (the same shape as
AC7) and are not attempted here; this covers the structural half: exactly one
row per non-cancelled outcome, best-effort under disconnect, and identity
sourced from the server-generated collector, never chat.py's own request_id
local.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.api.routes.chat as chat_routes
from app.core.domain.chat_memory import ChatMemoryContext
from app.core.domain.chat_service import ChatServiceStreamSession, StreamChatResult
from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.errors import ProviderExecutionError, ProviderTimeoutError
from app.core.domain.provider import ProviderResult
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.domain.types import ChatMessage
from app.api import deps
from app.core.domain.bm25_ranking import BM25_TOP_K
from app.core.domain.conversation_history import HistoryMessage
from app.http import pipeline_metrics, request_context
from app.infra.db.base import Base
from app.models.rag_request_metrics import RagRequestMetrics
from app.schemas.chat import ChatRequest

pytestmark = pytest.mark.asyncio

TENANT = "acme"


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Session:
    """A no-op /chat write session; a real conversation is unowned so the
    non-streaming/streaming not-found branches fire naturally."""

    def __init__(self, conversation=None) -> None:
        self.objects: list[object] = []
        self._conversation = conversation

    def begin(self):
        return _Transaction()

    def add(self, obj) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        return self._conversation

    async def rollback(self) -> None:
        return None


class _Owned:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id


class _ChatService:
    def __init__(self, *, content="answer", raise_exc=None) -> None:
        self.content = content
        self.raise_exc = raise_exc

    async def run(self, *, request_id, messages, provider_metadata=None):
        if self.raise_exc is not None:
            raise self.raise_exc
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=ChatMessage(role="assistant", content=self.content),
            provider_result=ProviderResult(
                content=self.content,
                provider="stub",
                model_version="stub-v1",
                prompt_version="v1",
                input_tokens=3,
                output_tokens=5,
                total_tokens=8,
            ),
        )

    async def stream_chat(self, *, request_id, messages, provider_metadata=None):
        if self.raise_exc is not None:
            raise self.raise_exc

        async def chunks() -> AsyncIterator[str]:
            yield self.content

        async def final() -> StreamChatResult:
            return StreamChatResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content=self.content),
                provider_result=None,
            )

        return ChatServiceStreamSession(chunks=chunks(), get_final_result=final)


@pytest.fixture
async def metrics_engine():
    """A real, seeded sqlite engine standing in for the operational session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all, tables=[RagRequestMetrics.__table__]
        )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def metrics_on(monkeypatch, metrics_engine):
    """Enables the flag and wires the seam to the real sqlite engine above."""
    from app.infra.db.session import short_lived_history_session

    monkeypatch.setattr(chat_routes.settings, "rag_request_metrics_enabled", True)
    sessionmaker = async_sessionmaker(metrics_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(chat_routes, "get_history_sessionmaker", lambda request: sessionmaker)
    return sessionmaker


@pytest.fixture
def collector():
    instance, token = pipeline_metrics.init_collector(
        # A real uuid4-shaped value, not an all-digit string: SQLite assigns
        # NUMERIC affinity to a column typed "UUID" (a name it doesn't
        # recognize), and an all-decimal-digit string gets silently coerced
        # into a float. Every real uuid4 contains at least one a-f hex
        # letter, so this never occurs against actual client-supplied ids;
        # it is purely a hermetic-test-data pitfall, not a production defect.
        request_instance_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4())
    )
    try:
        yield instance
    finally:
        pipeline_metrics.reset_collector(token)


async def _rows(sessionmaker) -> list[RagRequestMetrics]:
    async with sessionmaker() as session:
        from sqlalchemy import select

        result = await session.execute(select(RagRequestMetrics))
        return list(result.scalars().all())


# --- inert by default -------------------------------------------------------


async def test_disabled_by_default_writes_nothing(collector) -> None:
    await chat_routes._write_rag_request_metrics(
        None,
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )  # must not raise even with request=None


async def test_no_collector_is_a_no_op(monkeypatch, metrics_on) -> None:
    # metrics_on enables the flag but no collector fixture is requested here.
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )  # must not raise


async def test_none_request_is_a_no_op_even_when_enabled(metrics_on, collector) -> None:
    await chat_routes._write_rag_request_metrics(
        None,
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )
    assert await _rows(metrics_on) == []


# --- identity: server-side, from the collector, never chat.py's own request_id


async def test_identity_comes_from_the_collector_not_a_local_variable(
    metrics_on, collector
) -> None:
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=42,
    )
    rows = await _rows(metrics_on)
    assert len(rows) == 1
    assert str(rows[0].request_instance_id) == collector.request_instance_id
    assert str(rows[0].request_id) == collector.correlation_id


async def test_two_requests_replaying_the_same_header_each_get_their_own_row(
    metrics_on,
) -> None:
    # AC25: request_instance_id is the uniqueness column; request_id (the
    # replayable client header) is not.
    same_correlation = str(uuid.uuid4())  # see the `collector` fixture note above
    for _ in range(2):
        instance, token = pipeline_metrics.init_collector(
            request_instance_id=str(uuid.uuid4()), correlation_id=same_correlation
        )
        try:
            await chat_routes._write_rag_request_metrics(
                object(),
                tenant_id=TENANT,
                generation_outcome="ok",
                provider_result=None,
                memory_context=ChatMemoryContext(),
                total_latency_ms=1,
            )
        finally:
            pipeline_metrics.reset_collector(token)
    rows = await _rows(metrics_on)
    assert len(rows) == 2
    assert len({r.request_instance_id for r in rows}) == 2
    assert all(str(r.request_id) == same_correlation for r in rows)


async def test_memory_outcome_comes_from_the_collector(metrics_on, collector) -> None:
    pipeline_metrics.record(memory_outcome="conversation_not_found")
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].memory_outcome == "conversation_not_found"


async def test_history_flags_come_from_the_memory_context(metrics_on, collector) -> None:
    context = ChatMemoryContext(truncated=True, history_row_cap_reached=True)
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=context,
        total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].history_truncated is True
    assert rows[0].history_row_cap_reached is True


@pytest.mark.parametrize("count", [1, 3, BM25_TOP_K], ids=["one", "three", "top_k"])
async def test_ebm25_selected_count_comes_from_the_collector(
    metrics_on, collector, count
) -> None:
    """H7/Class 1: the count had a producer and the writer dropped it.

    `_record_ebm25_selected_count` (`deps.py`) has written this field since
    T18, and H9 and N-2 both hardened it -- but the writer never read it back
    out of the snapshot, so every row persisted NULL. This is the one column
    of H7's ten that needs no new producer at all.

    Parametrized up to `BM25_TOP_K`, which is 5: a writer capping the value at
    3 would otherwise pass, and 4 and 5 are reachable selections in production.
    """
    pipeline_metrics.record(ebm25_selected_count=count)
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].ebm25_selected_count == count


async def test_a_selected_count_of_zero_is_persisted_as_zero_not_null(
    metrics_on, collector
) -> None:
    """Zero is a MEASUREMENT, and must not be confused with "never ran".

    Both of Mode B's inert states record 0 deliberately (§Diseño 8). If the
    writer used a falsy test rather than a None test, "ranked and selected
    nothing" would persist identically to "Mode B never ran", which is the
    distinction the column exists to make.
    """
    pipeline_metrics.record(ebm25_selected_count=0)
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].ebm25_selected_count == 0


async def test_an_unrecorded_selected_count_stays_null(metrics_on, collector) -> None:
    """Mode A never records the field, and NULL is the correct row value.

    The collector drops `None` values, so an absent key and a recorded `None`
    are the same thing here.
    """
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].ebm25_selected_count is None


async def test_tokens_come_from_the_provider_result(metrics_on, collector) -> None:
    provider_result = ProviderResult(
        content="x", provider="stub", model_version="v1", prompt_version="v1",
        input_tokens=10, output_tokens=20,
    )
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="ok",
        provider_result=provider_result,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].input_tokens == 10
    assert rows[0].output_tokens == 20


async def test_mode_reflects_ebm25_enabled_false(monkeypatch, metrics_on, collector) -> None:
    monkeypatch.setattr(chat_routes.settings, "ebm25_enabled", False, raising=False)
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok", provider_result=None,
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].mode == "A"


async def test_mode_reflects_ebm25_enabled_true(monkeypatch, metrics_on, collector) -> None:
    monkeypatch.setattr(chat_routes.settings, "ebm25_enabled", True, raising=False)
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok", provider_result=None,
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].mode == "B"


async def test_mode_is_b_even_when_mode_b_selected_no_evidence(
    monkeypatch, metrics_on, collector
) -> None:
    """`mode` marks the active configuration, not whether Mode B's ranking
    actually selected evidence -- that finer distinction is
    `memory_outcome`/`ebm25_selected_count`'s job, not `mode`'s. A
    `no_out_of_window_corpus`/`budget_starved` request is still mode "B"."""
    monkeypatch.setattr(chat_routes.settings, "ebm25_enabled", True, raising=False)
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok", provider_result=None,
        memory_context=ChatMemoryContext(),  # no retrieved_events -- nothing selected
        total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].mode == "B"


async def test_mode_is_consistent_between_the_shared_write_site(
    monkeypatch, metrics_on
) -> None:
    """Both /chat paths (streaming and non-streaming) call the SAME
    `_write_rag_request_metrics` -- a single call site, not two independent
    hardcodes. Calling it twice with different `ebm25_enabled` values, each
    under its own collector identity (AC25: `request_instance_id` is the
    uniqueness column), proves it reads the flag fresh each time rather than
    caching a stale value."""
    for enabled in (False, True):
        monkeypatch.setattr(chat_routes.settings, "ebm25_enabled", enabled, raising=False)
        instance, token = pipeline_metrics.init_collector(
            request_instance_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4())
        )
        try:
            await chat_routes._write_rag_request_metrics(
                object(), tenant_id=TENANT, generation_outcome="ok", provider_result=None,
                memory_context=ChatMemoryContext(), total_latency_ms=1,
            )
        finally:
            pipeline_metrics.reset_collector(token)
    rows = await _rows(metrics_on)
    modes = sorted(row.mode for row in rows)
    assert modes == ["A", "B"]


# --- best-effort: a forced write failure never propagates -------------------


async def test_a_forced_failure_never_propagates(monkeypatch, metrics_on, collector) -> None:
    def _boom(request):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(chat_routes, "get_history_sessionmaker", _boom)
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok", provider_result=None,
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )  # must not raise


async def test_a_missing_request_instance_id_is_a_no_op(metrics_on) -> None:
    instance, token = pipeline_metrics.init_collector(request_instance_id="")
    try:
        await chat_routes._write_rag_request_metrics(
            object(), tenant_id=TENANT, generation_outcome="ok", provider_result=None,
            memory_context=ChatMemoryContext(), total_latency_ms=1,
        )
    finally:
        pipeline_metrics.reset_collector(token)
    assert await _rows(metrics_on) == []


# --- end to end through /chat: each terminal outcome yields the right row --


@pytest.fixture
def request_context_for(monkeypatch):
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", False)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: _NullCache())


class _NullCache:
    async def get(self, **kwargs):
        return None

    async def set(self, **kwargs):
        return None

    def log_bypass(self, **kwargs):
        return None


async def test_mode_b_persists_the_count_the_real_dependency_produced(
    monkeypatch, metrics_on, collector, request_context_for
) -> None:
    """H7/Class 1, producer -> writer, with Mode B actually ON.

    Independent re-validation of `af39174` found a mutation that survived every
    test in this file AND all 273 in `tests/api/`: persisting the count only
    when `ebm25_enabled` is FALSE, writing NULL in Mode B. That deletes exactly
    the production path the fix exists for.

    The hole was that the other three tests inject into the collector by hand
    with the flag off by default, and the Mode B tests elsewhere never look at
    the persisted row. Nothing joined the real producer to the real writer.

    So this one runs `get_chat_memory_context` for real with `ebm25_enabled`
    true, lets IT record the count, and then asserts the row the route wrote.
    The expected value is deliberately NOT 3 -- the positive case above uses 3,
    and a writer that hardcoded it would have passed both.
    """
    monkeypatch.setattr(deps.settings, "ebm25_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_enabled", True, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_messages", 2, raising=False)
    monkeypatch.setattr(deps.settings, "conversation_history_max_chars", 20000, raising=False)
    monkeypatch.setattr(deps, "get_tenant_id", lambda: TENANT)

    history = [
        HistoryMessage(sequence=1, role="user", content="the plan for launch"),
        HistoryMessage(sequence=2, role="assistant", content="launch is scheduled"),
        HistoryMessage(sequence=3, role="user", content="anything else"),
        HistoryMessage(sequence=4, role="assistant", content="no"),
    ]

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

    conversation_id = uuid.uuid4()
    memory_context = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=conversation_id, message="launch plan"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )
    # The producer really did select one out-of-window turn: the value under
    # test comes from Mode B, not from the test.
    assert len(memory_context.retrieved_events) == 1

    await chat_routes.chat(
        ChatRequest(message="launch plan"),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(),
        memory_context=memory_context,
    )

    rows = await _rows(metrics_on)
    assert [r.mode for r in rows] == ["B"]
    assert [r.ebm25_selected_count for r in rows] == [1]


async def test_non_streaming_success_yields_ok(metrics_on, collector, request_context_for) -> None:
    await chat_routes.chat(
        ChatRequest(message="hello"),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(),
    )
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["ok"]


async def test_non_streaming_not_found_yields_not_found(
    metrics_on, collector, request_context_for
) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await chat_routes.chat(
            ChatRequest(message="hello", conversation_id=uuid.uuid4()),
            request=object(),
            db=_Session(conversation=None),
            chat_service=_ChatService(),
        )
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["not_found"]


async def test_non_streaming_timeout_yields_timeout(
    metrics_on, collector, request_context_for
) -> None:
    await chat_routes.chat(
        ChatRequest(message="hello"),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(raise_exc=ProviderTimeoutError("slow")),
    )
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["timeout"]


async def test_non_streaming_provider_execution_error_yields_error(
    metrics_on, collector, request_context_for
) -> None:
    await chat_routes.chat(
        ChatRequest(message="hello"),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(raise_exc=ProviderExecutionError("boom")),
    )
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["error"]


async def test_non_streaming_unhandled_error_yields_error(
    metrics_on, collector, request_context_for
) -> None:
    await chat_routes.chat(
        ChatRequest(message="hello"),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(raise_exc=ValueError("unexpected")),
    )
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["error"]


async def _consume_stream(response) -> list[tuple[str, str]]:
    events, current = [], None
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else str(chunk)
        for line in text.splitlines():
            if line.startswith("event: "):
                current = line.removeprefix("event: ")
            elif line.startswith("data: ") and current is not None:
                events.append((current, line.removeprefix("data: ")))
                current = None
    return events


async def test_streaming_success_yields_ok(metrics_on, collector, request_context_for) -> None:
    response = await chat_routes.chat(
        ChatRequest(message="hello", stream=True),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(),
    )
    await _consume_stream(response)
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["ok"]


async def test_streaming_not_found_yields_not_found(
    metrics_on, collector, request_context_for
) -> None:
    response = await chat_routes.chat(
        ChatRequest(message="hello", conversation_id=uuid.uuid4(), stream=True),
        request=object(),
        db=_Session(conversation=None),
        chat_service=_ChatService(),
    )
    events = await _consume_stream(response)
    assert any(name == "error" for name, _ in events)
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["not_found"]


async def test_streaming_provider_error_yields_error(
    metrics_on, collector, request_context_for
) -> None:
    response = await chat_routes.chat(
        ChatRequest(message="hello", stream=True),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(
            raise_exc=ProviderError(kind=ProviderErrorKind.upstream, message="down")
        ),
    )
    await _consume_stream(response)
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["error"]


async def test_streaming_unhandled_error_yields_error(
    metrics_on, collector, request_context_for
) -> None:
    response = await chat_routes.chat(
        ChatRequest(message="hello", stream=True),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(raise_exc=ValueError("unexpected")),
    )
    await _consume_stream(response)
    rows = await _rows(metrics_on)
    assert [r.generation_outcome for r in rows] == ["error"]


async def test_streaming_disconnect_does_not_raise_and_is_best_effort(
    metrics_on, collector, request_context_for
) -> None:
    """Outcome 8: the generator is finalized mid-flight (client disconnect).

    Never raises, and zero-or-one row is acceptable -- this is the weaker
    contract AC18 states explicitly. Closing the generator drives the same
    `GeneratorExit` path Starlette drives on a real disconnect.
    """
    response = await chat_routes.chat(
        ChatRequest(message="hello", stream=True),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(),
    )
    agen = response.body_iterator
    await agen.__anext__()  # consume exactly one chunk, mid-stream
    await agen.aclose()  # forces GeneratorExit into event_generator's finally
    rows = await _rows(metrics_on)
    assert len(rows) in (0, 1)
    if rows:
        assert rows[0].generation_outcome in ("cancelled", "ok")


async def test_a_forced_write_failure_leaves_the_business_transaction_unchanged(
    monkeypatch, metrics_on, collector, request_context_for
) -> None:
    """AC18: a forced failure at the write site must not touch the response."""

    async def _boom(*args, **kwargs):
        raise RuntimeError("metrics write exploded")

    monkeypatch.setattr(chat_routes, "_write_rag_request_metrics", _boom)
    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(content="unaffected answer"),
    )
    assert response.assistant_content == "unaffected answer"
    assert response.status == chat_routes.ChatStatus.success


async def test_a_forced_slow_write_is_bounded_by_the_timeout(
    monkeypatch, metrics_on, collector, request_context_for
) -> None:
    """AC18: a forced slow write must not extend /chat's own latency unbounded."""
    import asyncio

    monkeypatch.setattr(chat_routes.settings, "rag_request_metrics_timeout_s", 0.01)

    async def _slow(*args, **kwargs):
        await asyncio.sleep(2)

    monkeypatch.setattr(chat_routes, "_write_rag_request_metrics", _slow)

    started = asyncio.get_event_loop().time()
    response = await chat_routes.chat(
        ChatRequest(message="hello"),
        request=object(),
        db=_Session(),
        chat_service=_ChatService(),
    )
    elapsed = asyncio.get_event_loop().time() - started
    assert response.status == chat_routes.ChatStatus.success
    assert elapsed < 1.0, "the slow write must not have been awaited to completion"


# --- AC32: a hostile header through the REAL route, at the metrics row ------
#
# H10 recorded that the adversarial-header tests "use a dummy downstream
# responder, not the complete route/metrics path". `test_telemetry_identity.py`
# drives a dummy responder and `test_request_id_hostile_header.py` covers the
# minting; neither reaches a persisted row. These do.
#
# The other half of that bullet -- "legacy UUID parsing outside try blocks
# remains" -- was discharged by N-1 and is not re-tested here.


@pytest.mark.parametrize(
    "hostile",
    ["not-a-uuid", "", "ü" * 8, "'; DROP TABLE rag_request_metrics; --", "x" * 4096],
    ids=["garbage", "empty", "unicode", "sqlish", "oversized"],
)
async def test_a_hostile_request_id_still_yields_exactly_one_well_formed_row(
    metrics_on, request_context_for, hostile
) -> None:
    """The row is written, and its identity columns are UUIDs or NULL.

    `request_instance_id` is server-minted and NOT NULL; `request_id` carries
    the client's value and is nullable, so a header that is not a UUID must
    land as NULL rather than as the raw string or a 500.
    """
    instance_id = str(uuid.uuid4())
    instance, token = pipeline_metrics.init_collector(
        request_instance_id=instance_id, correlation_id=None
    )
    try:
        tokens = request_context.set_request_context(hostile, hostile)
        try:
            await chat_routes.chat(
                ChatRequest(message="hello"),
                request=object(),
                db=_Session(),
                chat_service=_ChatService(),
            )
        finally:
            request_context.reset_request_context(*tokens)
    finally:
        pipeline_metrics.reset_collector(token)

    rows = await _rows(metrics_on)
    assert len(rows) == 1
    assert str(rows[0].request_instance_id) == instance_id
    assert rows[0].request_id is None
    assert rows[0].generation_outcome == "ok"

    # "no such content in ANY column", swept rather than spot-checked.
    # Checking chosen columns let a mutation copying the header into
    # `memory_outcome` pass all five of these cases.
    if hostile:
        persisted = {
            column.name: getattr(rows[0], column.name)
            for column in RagRequestMetrics.__table__.columns
        }
        for name, value in persisted.items():
            assert hostile not in str(value), (
                f"the hostile request id reached column {name!r}: {value!r}"
            )


# --- ORQ-37: estimated_cost_usd, from the frozen snapshot ------------------


def _priced_result(provider: str, model: str, *, inp: int, out: int) -> ProviderResult:
    return ProviderResult(
        content="x", provider=provider, model_version=model,
        prompt_version="v1", input_tokens=inp, output_tokens=out,
    )


async def test_estimated_cost_comes_from_the_frozen_snapshot(
    metrics_on, collector
) -> None:
    """gpt-4.1-mini at 0.40/1.60 per 1M: 1000 in + 500 out = 0.0012."""
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok",
        provider_result=_priced_result("openai", "gpt-4.1-mini", inp=1000, out=500),
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].estimated_cost_usd == pytest.approx(0.0012)


async def test_estimated_cost_prices_bedrock_from_its_own_row(
    metrics_on, collector
) -> None:
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok",
        provider_result=_priced_result(
            "bedrock", "nvidia.nemotron-nano-12b-v2", inp=1000, out=500
        ),
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].estimated_cost_usd == pytest.approx(0.000175)


async def test_an_unpriced_model_persists_null_not_zero(metrics_on, collector) -> None:
    """NULL says "no price for this pair". A zero here would read as a measured
    cost of nothing, which is the contamination the column stayed empty to
    avoid until the snapshot existed."""
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok",
        provider_result=_priced_result("openai", "gpt-4o-mini", inp=1000, out=500),
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].estimated_cost_usd is None


async def test_a_genuine_zero_cost_persists_as_zero_not_null(
    metrics_on, collector
) -> None:
    """The stub provider is priced, at nothing. Distinguishable from unpriced.

    A falsy test in the writer would collapse this into the NULL above -- the
    same defect shape as `ebm25_selected_count`, which is why both directions
    are pinned rather than just the positive case.
    """
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok",
        provider_result=_priced_result("stub", None, inp=1000, out=500),
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].estimated_cost_usd == 0.0
    assert rows[0].estimated_cost_usd is not None


async def test_no_provider_result_leaves_cost_null(metrics_on, collector) -> None:
    """A request that never reached the provider has no cost to report."""
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="error",
        provider_result=None, memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].estimated_cost_usd is None


# --- AC24 literally: three independent outcome fields in one row -----------


async def test_retrieval_outcome_is_persisted_from_the_collector(
    metrics_on, collector
) -> None:
    pipeline_metrics.record(retrieval_outcome="ok")
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok", provider_result=None,
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].retrieval_outcome == "ok"


async def test_an_unrecorded_retrieval_outcome_stays_null(metrics_on, collector) -> None:
    await chat_routes._write_rag_request_metrics(
        object(), tenant_id=TENANT, generation_outcome="ok", provider_result=None,
        memory_context=ChatMemoryContext(), total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert rows[0].retrieval_outcome is None


async def test_retrieval_succeeds_while_generation_fails_yields_distinct_fields(
    metrics_on, collector
) -> None:
    """AC24's own fixture, asserted on the raw row.

    The criterion's whole point is independence: retrieval can succeed in the
    same request whose generation fails, and memory can report a third thing
    again. One shared value would make the three columns one column.
    """
    pipeline_metrics.record(retrieval_outcome="ok", memory_outcome="empty")
    await chat_routes._write_rag_request_metrics(
        object(),
        tenant_id=TENANT,
        generation_outcome="error",
        provider_result=None,
        memory_context=ChatMemoryContext(),
        total_latency_ms=1,
    )
    rows = await _rows(metrics_on)
    assert len(rows) == 1
    row = rows[0]
    assert row.retrieval_outcome == "ok"
    assert row.generation_outcome == "error"
    assert row.memory_outcome == "empty"
    # Independent, not merely present: no two of them agree here.
    assert len({row.retrieval_outcome, row.generation_outcome, row.memory_outcome}) == 3
