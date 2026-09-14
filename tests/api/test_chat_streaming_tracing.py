"""ORQ-37 T2 — responses are identical with tracing on, off, broken and hung (AC2).

Route-level counterpart to the chunk-level assertions in
`tests/core/test_tracing_pipeline_stages.py`. `/chat` is not modified by this
test or by T2; it is driven exactly as `tests/api/test_chat_streaming.py`
drives it, and the raw response body is compared after normalizing the
request-scoped UUID fields, which differ per request by design.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.api.routes.chat import chat
from app.core.domain.chat_service import ChatService
from app.core.domain.provider import (
    ProviderInput,
    ProviderResult,
    ProviderStreamResult,
)
from app.core.observability import tracing
from app.schemas.chat import ChatRequest

_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_TOKENS = ["hel", "lo", " ", "mundo"]


class _FakeSession:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    @property
    def chunks(self) -> AsyncIterator[str]:
        async def _gen():
            for token in self._tokens:
                yield token

        return _gen()

    async def get_final_result(self) -> ProviderStreamResult:
        content = "".join(self._tokens)
        return ProviderStreamResult(
            content=content,
            provider_result=ProviderResult(
                content=content,
                provider="stub",
                model_version="stub-model",
                prompt_version="v1",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                latency_ms=5,
            ),
        )


class _StreamingProvider:
    async def generate(self, input: ProviderInput) -> ProviderResult:
        content = "".join(_TOKENS)
        return ProviderResult(
            content=content, provider="stub", model_version="stub-model", prompt_version="v1"
        )

    async def stream(self, input: ProviderInput):
        return _FakeSession(list(_TOKENS))


class _FakeAsyncSession:
    """Minimal async-session double: the route's persistence is not under test."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, *args, **kwargs):
        return None

    def begin(self):
        session = self

        class _Tx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        return _Tx()


class _RaisingTracer:
    def start_as_current_span(self, name):
        raise RuntimeError("tracer is broken")


class _NoopSpan:
    def set_attribute(self, key, value):
        return None


class _WorkingTracer:
    def start_as_current_span(self, name):
        class _CM:
            def __enter__(self):
                return _NoopSpan()

            def __exit__(self, *exc):
                return False

        return _CM()


class _RaisingOnExitTracer:
    """Raises where a real exporter fails: on span END, not on span start.

    `_RaisingTracer` fails at `start_as_current_span`, which the seam handles
    by yielding `None` and skipping the span entirely -- a different code path
    from a span that opens normally and then blows up on close. Mutating the
    seam's `span_end` handler to let that exception propagate passed every test
    in this file until this double existed, so AC2's "raising on every span"
    was only covered at one end.

    `exits` counts entries, not the raise itself -- deleting the `raise` and
    keeping the counter left the tests green. Each test therefore asserts that
    the seam actually LOGGED `tracing.span_end_failed`, which only happens when
    an exception reached its handler.
    """

    def __init__(self) -> None:
        self.exits = 0

    def start_as_current_span(self, name):
        tracer = self

        class _CM:
            def __enter__(self):
                return _NoopSpan()

            def __exit__(self, *exc):
                tracer.exits += 1
                raise RuntimeError("exporter failed on span end")

        return _CM()


class _SlowTracer:
    """AC2's second condition: an exporter that blocks past its export timeout.

    The seam has no timeout of its own -- it calls the tracer and the tracer
    decides how long a span takes -- so the faithful double is one that blocks
    on span END, where a hung exporter's flush would sit. The property under
    test is that an arbitrarily slow span lifecycle changes the response not at
    all; the delay is kept small only so the suite stays fast.

    **What the instrumentation proves, stated narrowly.** `blocked` counts
    ENTRIES into this double, not its effects: independent re-validation showed
    that deleting the `sleep` while keeping the counter left all three tests
    green. The counter alone was exactly the vacuous guard it claimed to
    prevent. Each test therefore also asserts ELAPSED TIME, which `sleep`
    guarantees as a lower bound and which no counter can fake.

    **Declared limit.** This does not reproduce OTel's export timeout. It
    blocks in the request thread; production exports through a batch processor
    whose configured timeout is 10_000 ms, which this never approaches. What is
    demonstrated is that a span lifecycle taking arbitrarily long does not
    change the response -- not that a real hung exporter was exercised.
    """

    def __init__(self, delay_s: float = 0.02) -> None:
        self.delay_s = delay_s
        self.blocked = 0

    def start_as_current_span(self, name):
        tracer = self

        class _CM:
            def __enter__(self):
                return _NoopSpan()

            def __exit__(self, *exc):
                tracer.blocked += 1
                time.sleep(tracer.delay_s)
                return False

        return _CM()


_SEAM_LOGGER = "app.observability.tracing"


async def _timed(awaitable):
    """Elapsed wall time around a driver, in seconds."""
    start = time.perf_counter()
    result = await awaitable
    return time.perf_counter() - start, result


def _assert_really_blocked(tracer, elapsed: float) -> None:
    """`sleep` guarantees a LOWER bound; a counter guarantees nothing.

    Re-validation deleted the sleep, kept the counter, and every test stayed
    green. Elapsed time is what cannot be faked by incrementing an integer.
    """
    assert tracer.blocked > 0, "the slow double never entered its span exit"
    assert elapsed >= tracer.delay_s, (
        f"the slow double did not block: {elapsed:.4f}s elapsed for "
        f"{tracer.blocked} span(s) of {tracer.delay_s}s each"
    )


def _assert_span_end_was_handled(caplog) -> None:
    """The seam only logs this when an exception reached its `span_end` handler."""
    assert any(
        record.getMessage() == "tracing.span_end_failed" for record in caplog.records
    ), "the seam never handled a failing span end; the double may not have raised"


async def _raw_sse_body() -> tuple[str, int]:
    response = await chat(
        ChatRequest(message="hello", stream=True),
        db=_FakeAsyncSession(),
        chat_service=ChatService(provider=_StreamingProvider(), timeout_s=1.0),
    )
    parts: list[str] = []
    async for chunk in response.body_iterator:
        parts.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    # AC2 requires "identical status", not only an identical body. Returned
    # alongside it because a mutation flipping the streaming status to 503
    # under tracing passed every body-only comparison here.
    return _UUID.sub("<uuid>", "".join(parts)), response.status_code


@pytest.mark.asyncio
async def test_sse_body_and_status_are_identical_under_every_tracer(caplog):
    """AC2 over the streaming path: body AND status, four tracer conditions."""
    tracing.configure_for_testing(None)
    try:
        disabled = await _raw_sse_body()

        tracing.configure_for_testing(_WorkingTracer())
        enabled = await _raw_sse_body()

        tracing.configure_for_testing(_RaisingTracer())
        broken = await _raw_sse_body()

        exit_tracer = _RaisingOnExitTracer()
        tracing.configure_for_testing(exit_tracer)
        with caplog.at_level(logging.DEBUG, logger=_SEAM_LOGGER):
            broken_on_exit = await _raw_sse_body()
        _assert_span_end_was_handled(caplog)

        # AC2's second condition: a hung exporter, not just a raising tracer.
        slow_tracer = _SlowTracer()
        tracing.configure_for_testing(slow_tracer)
        elapsed, slow = await _timed(_raw_sse_body())
    finally:
        tracing.configure_for_testing(None)

    assert enabled == disabled
    assert broken == disabled
    assert broken_on_exit == disabled
    assert slow == disabled
    _assert_really_blocked(slow_tracer, elapsed)
    assert exit_tracer.exits > 0, "the raising-on-exit double never closed a span"
    body, status = disabled
    # The body is real, so equality is not equality of two empty strings.
    assert "event: token" in body and "event: done" in body
    assert body.count("event: token") == len(_TOKENS)
    assert status == 200


# --- AC2's remaining halves: non-streaming /chat and /retrieval -------------


async def _non_streaming_body() -> str:
    response = await chat(
        ChatRequest(message="hello", stream=False),
        db=_FakeAsyncSession(),
        chat_service=ChatService(provider=_StreamingProvider(), timeout_s=1.0),
    )
    return _UUID.sub("<uuid>", response.model_dump_json())


@pytest.mark.asyncio
async def test_non_streaming_chat_is_identical_with_tracing_disabled_and_enabled(caplog):
    tracing.configure_for_testing(None)
    try:
        disabled = await _non_streaming_body()

        tracing.configure_for_testing(_WorkingTracer())
        enabled = await _non_streaming_body()

        tracing.configure_for_testing(_RaisingTracer())
        broken = await _non_streaming_body()

        exit_tracer = _RaisingOnExitTracer()
        tracing.configure_for_testing(exit_tracer)
        with caplog.at_level(logging.DEBUG, logger=_SEAM_LOGGER):
            broken_on_exit = await _non_streaming_body()
        _assert_span_end_was_handled(caplog)

        # AC2's second condition: a hung exporter, not just a raising tracer.
        slow_tracer = _SlowTracer()
        tracing.configure_for_testing(slow_tracer)
        elapsed, slow = await _timed(_non_streaming_body())
    finally:
        tracing.configure_for_testing(None)

    assert enabled == disabled
    assert broken == disabled
    assert broken_on_exit == disabled
    assert slow == disabled
    _assert_really_blocked(slow_tracer, elapsed)
    assert exit_tracer.exits > 0, "the raising-on-exit double never closed a span"
    assert "hello mundo" in disabled  # a real body, not two empty strings


@pytest.mark.asyncio
async def test_retrieval_is_identical_with_tracing_disabled_and_enabled(monkeypatch, caplog):
    """`/rag/retrieve` runs the same four stages `/chat` augments with, so it is
    the second surface AC2 names. Driven at the handler with a real pipeline
    over fake ports; the route's own dependencies are what a live corpus would
    provide, and they are not what this criterion is about."""
    import uuid as _uuid

    from app.api.routes.retrieval import retrieve
    from app.core.domain.reranker import RankedDocument
    from app.core.domain.retrieval_pipeline import RetrievalPipeline
    from app.http.middleware.tenant import tenant_scope
    from app.schemas.retrieval import RetrieveRequest
    from tests.core.test_tracing_pipeline_stages import (
        _FakeEmbedding,
        _FakeProvider,
        _FakeReranker,
        _FakeVectorStore,
        _chunk,
    )

    def _pipeline() -> RetrievalPipeline:
        return RetrievalPipeline(
            provider=_FakeProvider(rewritten="rewritten query"),
            embedding=_FakeEmbedding(),
            vector_store=_FakeVectorStore([_chunk(i) for i in range(3)]),
            reranker=_FakeReranker(results=[RankedDocument(index=0, rank=1)]),
            min_reranked_results=5,
        )

    async def _body() -> str:
        with tenant_scope("tenant-a"):
            response = await retrieve(
                RetrieveRequest(query="why capabilities first?"),
                _enabled=None,
                pipeline=_pipeline(),
            )
        return _UUID.sub("<uuid>", response.model_dump_json())

    tracing.configure_for_testing(None)
    try:
        disabled = await _body()

        tracing.configure_for_testing(_WorkingTracer())
        enabled = await _body()

        tracing.configure_for_testing(_RaisingTracer())
        broken = await _body()

        exit_tracer = _RaisingOnExitTracer()
        tracing.configure_for_testing(exit_tracer)
        with caplog.at_level(logging.DEBUG, logger=_SEAM_LOGGER):
            broken_on_exit = await _body()
        _assert_span_end_was_handled(caplog)

        # AC2's second condition: a hung exporter, not just a raising tracer.
        slow_tracer = _SlowTracer()
        tracing.configure_for_testing(slow_tracer)
        elapsed, slow = await _timed(_body())
    finally:
        tracing.configure_for_testing(None)

    assert enabled == disabled
    assert broken == disabled
    assert broken_on_exit == disabled
    assert slow == disabled
    _assert_really_blocked(slow_tracer, elapsed)
    assert exit_tracer.exits > 0, "the raising-on-exit double never closed a span"
    assert "rewritten query" in disabled


# --- AC2's "identical status" on the two handler-level paths ---------------


@pytest.mark.asyncio
async def test_handler_paths_return_normally_under_every_tracer(caplog):
    """AC2 requires identical STATUS, not only identical bodies.

    The streaming test asserts `response.status_code` directly, because a
    `StreamingResponse` carries one. The other two drivers call their handlers
    directly and return a pydantic model, so FastAPI -- which is what turns a
    return value into a status -- is not in the loop. What IS observable there
    is that the handler returns a model rather than raising, which is the only
    way status could diverge on those paths at this level.

    **Declared limit:** a full status comparison for those two would need an
    ASGI client. These drivers deliberately do not use one, and this test does
    not claim otherwise.
    """
    from app.schemas.chat import ChatResponse

    tracing.configure_for_testing(None)
    try:
        for tracer in (None, _WorkingTracer(), _RaisingTracer(),
                       _RaisingOnExitTracer(), _SlowTracer()):
            tracing.configure_for_testing(tracer)
            response = await chat(
                ChatRequest(message="hello", stream=False),
                db=_FakeAsyncSession(),
                chat_service=ChatService(provider=_StreamingProvider(), timeout_s=1.0),
            )
            assert isinstance(response, ChatResponse)
    finally:
        tracing.configure_for_testing(None)
