"""ORQ-37 H5/AC11 -- the metrics write must not overlap an incomplete `__aexit__`.

AC11 does not accept lexical placement in a `finally` as evidence of
ordering. Its own words: on the streaming path the generator can be finalized
while suspended at the in-transaction `yield` of `chat.py:331`, inside
`async with db.begin():`, "where `__aexit__` is entered but its rollback need
not complete, so the shielded write must not overlap an incomplete
`__aexit__`".

Independent validation reproduced that control-flow counterexample and
reported the required test as absent: the committed disconnect test closes at
the FIRST TOKEN, before persistence is ever reached, so it never visits the
in-transaction yield at all.

These tests drive the real route. The only instrumented part is the session
double's transaction, which is what the counterexample is about.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest

import app.api.routes.chat as chat_routes
from app.core.domain.chat_memory import ChatMemoryContext
from app.core.domain.chat_service import ChatServiceStreamSession, StreamChatResult
from app.core.domain.types import ChatMessage
from app.schemas.chat import ChatRequest


FOREIGN_CONVERSATION = uuid.uuid4()


class _InterruptedTransaction:
    """`__aexit__` is entered and then cancelled before the release completes.

    This is the state AC11 names: entered, incomplete. The owning session
    keeps reporting `in_transaction() is True`, exactly as a real session
    whose rollback never finished would.
    """

    def __init__(self, session: "_Session") -> None:
        self._session = session

    async def __aenter__(self):
        self._session.active = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Entered... and interrupted before `self._session.active = False`.
        if self._session.interrupt_release:
            raise asyncio.CancelledError()
        self._session.active = False
        return False


class _Session:
    def __init__(self, *, interrupt_release: bool) -> None:
        self.active = False
        self.interrupt_release = interrupt_release
        self.objects: list[object] = []

    def begin(self):
        return _InterruptedTransaction(self)

    def in_transaction(self) -> bool:
        return self.active

    def add(self, obj) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        # Unowned: drives the route to the in-transaction not-found yield.
        return None


class _StreamingService:
    async def stream_chat(self, *, request_id, messages, provider_metadata=None):
        async def chunks() -> AsyncIterator[str]:
            yield "token"

        async def final() -> StreamChatResult:
            return StreamChatResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content="token"),
                provider_result=None,
            )

        return ChatServiceStreamSession(chunks=chunks(), get_final_result=final)


class _Cache:
    async def get(self, **kwargs):
        return None

    async def set(self, **kwargs):
        return None

    def log_bypass(self, *, reason):
        return None


@pytest.fixture
def writes(monkeypatch):
    """Count metrics writes without needing a database."""
    calls: list[dict] = []

    async def _fake_write(request, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat_routes, "_write_rag_request_metrics", _fake_write)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: _Cache())
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", False)
    return calls


async def _drive_to_the_in_transaction_yield(session) -> object:
    """Consume the stream up to and including the in-transaction not-found
    frame, leaving the generator suspended exactly there."""
    response = await chat_routes.chat(
        ChatRequest(message="q", conversation_id=FOREIGN_CONVERSATION, stream=True),
        db=session,
        chat_service=_StreamingService(),
        memory_context=ChatMemoryContext(),
    )
    iterator = response.body_iterator.__aiter__()
    seen: list[str] = []
    async for raw in iterator:
        chunk = raw.decode() if isinstance(raw, bytes) else str(raw)
        seen.append(chunk)
        if "not_found" in chunk:
            break
    assert any("not_found" in chunk for chunk in seen), seen
    return iterator


@pytest.mark.asyncio
async def test_no_metrics_write_while_the_release_is_incomplete(writes) -> None:
    """The AC11 counterexample. Without the guard the shielded write runs
    while `__aexit__` is still unwinding, which is what AC11 forbids."""
    session = _Session(interrupt_release=True)
    iterator = await _drive_to_the_in_transaction_yield(session)

    # Finalize at the in-transaction yield: `__aexit__` is entered and
    # cancelled before it clears the flag. Whether `aclose()` itself surfaces
    # that cancellation is an implementation detail of generator finalization
    # and not what AC11 is about, so it is tolerated either way.
    try:
        await iterator.aclose()
    except BaseException:
        pass

    assert session.in_transaction() is True, "the fixture must leave the release incomplete"
    assert writes == [], "the write overlapped an incomplete __aexit__"


@pytest.mark.asyncio
async def test_the_write_still_happens_when_the_release_completes(writes) -> None:
    """The mirror, and the reason the test above is not vacuous: the same
    route, the same in-transaction yield, a release that completes normally.
    Outcome `not_found` is one of the seven non-cancelled outcomes and must
    still produce its row."""
    session = _Session(interrupt_release=False)
    response = await chat_routes.chat(
        ChatRequest(message="q", conversation_id=FOREIGN_CONVERSATION, stream=True),
        db=session,
        chat_service=_StreamingService(),
        memory_context=ChatMemoryContext(),
    )
    async for _ in response.body_iterator:
        pass

    assert session.in_transaction() is False
    assert len(writes) == 1
    assert writes[0]["generation_outcome"] == "not_found"


def test_the_guard_is_tolerant_of_doubles_without_transaction_state() -> None:
    """Ten test files define `begin()`-only session doubles. A double with no
    transaction state has nothing to overlap, so the guard must not turn them
    into skipped writes."""

    class _NoTransactionState:
        pass

    assert chat_routes._business_transaction_released(_NoTransactionState()) is True


def test_the_guard_reports_an_open_transaction() -> None:
    class _Open:
        def in_transaction(self):
            return True

    assert chat_routes._business_transaction_released(_Open()) is False


@pytest.mark.asyncio
async def test_the_observable_behaves_on_a_real_async_session() -> None:
    """The guard is only as good as `in_transaction()` on the REAL class.

    Every other test here uses a transaction double, which is what makes the
    counterexample expressible at all -- but a double could just as easily
    encode an assumption about SQLAlchemy that is false, and this ORQ has
    already shipped tests that passed for the wrong reason. This pins the
    observable against a real `AsyncSession`:

    * open transaction  -> not released (the guard fires)
    * after commit      -> released (normal outcomes still write)
    * after rollback    -> released (error outcomes still write)

    The last two are the regression that would matter most: a guard that
    reported "not released" after a normal commit would silently stop writing
    the rows AC18 requires for all seven non-cancelled outcomes.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as db:
            assert chat_routes._business_transaction_released(db) is True

            async with db.begin():
                assert chat_routes._business_transaction_released(db) is False
            assert chat_routes._business_transaction_released(db) is True

            with pytest.raises(RuntimeError):
                async with db.begin():
                    raise RuntimeError("boom")
            assert chat_routes._business_transaction_released(db) is True
    finally:
        await engine.dispose()
