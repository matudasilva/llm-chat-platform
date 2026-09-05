"""ORQ-37 Gate A, T2 — stage instrumentation (AC3 tree, AC2, AC4).

T2 wraps existing stage boundaries. It must not restructure the pipeline, and
the spans must describe current behaviour rather than change it, so most of
what is asserted here is *absence of change*: same results, same exceptions,
same fallbacks, with tracing on and off.

The tracer double models `start_as_current_span`'s nesting with an explicit
stack. That verifies the seam opens context-propagating spans in the right
order and closes them correctly; the real parent/child linkage is the SDK's
job and is not re-tested here.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Sequence

import pytest

from app.core.domain.chat_service import ChatService
from app.core.domain.errors import ProviderExecutionError, ProviderTimeoutError
from app.core.domain.provider import ProviderInput, ProviderResult
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.domain.reranker import RankedDocument, RerankRequest, RerankerError
from app.core.domain.retrieval_pipeline import RetrievalPipeline
from app.core.domain.types import ChatMessage
from app.core.domain.vector_store import RetrievedChunk
from app.core.observability import schema, tracing

_QUERY = "why capabilities over an orchestrator"
_REWRITTEN = "capabilities-first instead of execution orchestrator"


# --- A tracer double that models nesting ----------------------------------


class _Span:
    def __init__(self, name: str, parent: "_Span | None") -> None:
        self.name = name
        self.parent = parent
        self.children: list[_Span] = []
        self.attributes: dict[str, object] = {}
        self.ended = False
        self.exception: BaseException | None = None

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _StackTracer:
    """Models `start_as_current_span`: a span opened inside another is its child."""

    def __init__(self) -> None:
        self.stack: list[_Span] = []
        self.spans: list[_Span] = []

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
                current.exception = exc
                tracer.stack.pop()
                return False

        return _CM()

    def names(self) -> list[str]:
        return [s.name for s in self.spans]

    def by_name(self, name: str) -> _Span:
        matches = [s for s in self.spans if s.name == name]
        assert len(matches) == 1, f"expected exactly one {name}, got {len(matches)}"
        return matches[0]


@pytest.fixture
def tracer():
    double = _StackTracer()
    tracing.configure_for_testing(double)
    tracing.reset_rejected_attribute_keys()
    yield double
    tracing.configure_for_testing(None)
    tracing.reset_rejected_attribute_keys()


# --- Fakes (shape mirrors tests/core/test_retrieval_pipeline.py) ----------


class _FakeProvider:
    def __init__(self, *, rewritten=None, verdict="SUFFICIENT", fail_on=None) -> None:
        self.calls: list[str] = []
        self._rewritten = rewritten
        self._verdict = verdict
        self._fail_on = fail_on or set()

    async def generate(self, input: ProviderInput) -> ProviderResult:
        system = input.messages[0].content
        stage = "evaluator" if "SUFFICIENT" in system else "rewrite"
        self.calls.append(stage)
        if stage in self._fail_on:
            raise RuntimeError("provider unavailable")
        content = self._rewritten if stage == "rewrite" else self._verdict
        return ProviderResult(
            content=content or _QUERY, provider="stub", model_version="v1", prompt_version="v1"
        )


class _FakeEmbedding:
    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises

    async def embed_one(self, text: str) -> Sequence[float]:
        if self._raises is not None:
            raise self._raises
        return [0.1, 0.2, 0.3]

    async def embed_many(self, texts):
        raise NotImplementedError


def _chunk(i: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), text=f"chunk {i}", score=1.0 / (i + 1)
    )


class _FakeVectorStore:
    def __init__(self, candidates) -> None:
        self._candidates = candidates

    async def upsert_chunks(self, chunks):
        raise NotImplementedError

    async def hybrid_search(self, query_text, query_embedding, *, top_k=20):
        return self._candidates


class _FakeReranker:
    def __init__(self, *, results=None, raises=None) -> None:
        self._results = results
        self._raises = raises

    async def rerank(self, request: RerankRequest):
        if self._raises is not None:
            raise self._raises
        return self._results if self._results is not None else []


def _pipeline(*, provider, vector_store, reranker, embedding=None, min_reranked_results=5, top_n=5):
    return RetrievalPipeline(
        provider=provider,
        embedding=embedding or _FakeEmbedding(),
        vector_store=vector_store,
        reranker=reranker,
        top_n=top_n,
        min_reranked_results=min_reranked_results,
    )


def _full_pipeline(**kwargs):
    """rewrite -> retrieve -> rerank -> evaluate, all four reached."""
    return _pipeline(
        provider=_FakeProvider(rewritten=_REWRITTEN),
        vector_store=_FakeVectorStore([_chunk(i) for i in range(5)]),
        reranker=_FakeReranker(results=[RankedDocument(index=0, rank=1)]),
        min_reranked_results=5,  # 1 ranked < 5 -> evaluator triggers
        **kwargs,
    )


# --- Tree ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_four_retrieval_stages_emit_in_pipeline_order(tracer):
    await _full_pipeline().retrieve(request_id=uuid.uuid4(), query=_QUERY)
    assert tracer.names() == ["rag.rewrite", "rag.retrieve", "rag.rerank", "rag.evaluate"]
    assert all(s.ended for s in tracer.spans)


@pytest.mark.asyncio
async def test_stage_spans_nest_under_an_externally_opened_request_span(tracer):
    """AC3's tree property. T2 does not open the request span -- the middleware
    does, at T8 -- so this asserts the stages attach to whatever parent is
    current, which is what makes that later work sufficient."""
    with tracing.span(schema.REQUEST_SPAN):
        await _full_pipeline().retrieve(request_id=uuid.uuid4(), query=_QUERY)

    request_span = tracer.by_name(schema.REQUEST_SPAN)
    assert [c.name for c in request_span.children] == [
        "rag.rewrite",
        "rag.retrieve",
        "rag.rerank",
        "rag.evaluate",
    ]
    assert all(c.children == [] for c in request_span.children)


@pytest.mark.asyncio
async def test_generate_span_nests_under_the_request_span(tracer):
    service = ChatService(provider=_FakeProvider(rewritten="answer"), timeout_s=5.0)
    with tracing.span(schema.REQUEST_SPAN):
        await service.run(request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="q")])

    assert [c.name for c in tracer.by_name(schema.REQUEST_SPAN).children] == ["rag.generate"]


# --- Reached vs not reached ------------------------------------------------


@pytest.mark.asyncio
async def test_rerank_span_exists_when_the_reranker_falls_back(tracer):
    """The finding that redefined "expected spans": a stage entered and fallen
    back is *reached*. Emitting the span only on success would exclude the
    fallback from its own denominator."""
    pipeline = _pipeline(
        provider=_FakeProvider(rewritten=_REWRITTEN),
        vector_store=_FakeVectorStore([_chunk(i) for i in range(3)]),
        reranker=_FakeReranker(raises=RerankerError("reranker down", backend="fake")),
        min_reranked_results=0,
    )
    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.fallback_triggered is True
    rerank = tracer.by_name("rag.rerank")
    assert rerank.attributes["rag.fallback_used"] is True
    assert rerank.attributes["rag.ranked_count"] == 3
    assert rerank.exception is None  # the fallback is not an error


@pytest.mark.asyncio
async def test_rewrite_span_exists_when_the_rewrite_call_fails(tracer):
    pipeline = _pipeline(
        provider=_FakeProvider(fail_on={"rewrite"}),
        vector_store=_FakeVectorStore([]),
        reranker=_FakeReranker(),
    )
    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.rewritten_query == _QUERY  # unchanged fallback behaviour
    assert tracer.by_name("rag.rewrite").attributes["rag.rewrite_outcome"] == "failed"


@pytest.mark.asyncio
async def test_unreached_stages_emit_no_span(tracer):
    """No candidates -> rerank and evaluate are never entered."""
    pipeline = _pipeline(
        provider=_FakeProvider(rewritten=_REWRITTEN),
        vector_store=_FakeVectorStore([]),
        reranker=_FakeReranker(),
    )
    await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert tracer.names() == ["rag.rewrite", "rag.retrieve"]
    assert tracer.by_name("rag.retrieve").attributes["rag.retrieval_outcome"] == "empty"


@pytest.mark.asyncio
async def test_evaluate_span_absent_when_the_evaluator_does_not_trigger(tracer):
    pipeline = _pipeline(
        provider=_FakeProvider(rewritten=_REWRITTEN),
        vector_store=_FakeVectorStore([_chunk(i) for i in range(5)]),
        reranker=_FakeReranker(results=[RankedDocument(index=i, rank=i + 1) for i in range(5)]),
        min_reranked_results=5,
    )
    await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)
    assert "rag.evaluate" not in tracer.names()


@pytest.mark.asyncio
async def test_evaluate_span_exists_when_the_evaluator_call_fails(tracer):
    pipeline = _pipeline(
        provider=_FakeProvider(rewritten=_REWRITTEN, fail_on={"evaluator"}),
        vector_store=_FakeVectorStore([_chunk(0)]),
        reranker=_FakeReranker(results=[RankedDocument(index=0, rank=1)]),
        min_reranked_results=5,
    )
    result = await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    assert result.evaluator_verdict is None
    assert tracer.by_name("rag.evaluate").attributes["rag.evaluate_outcome"] == "failed"


# --- Semantics are unchanged ----------------------------------------------


@pytest.mark.asyncio
async def test_an_embedding_failure_still_propagates(tracer):
    """The retrieve stage has no `except` today; tracing must not add one."""
    pipeline = _pipeline(
        provider=_FakeProvider(rewritten=_REWRITTEN),
        vector_store=_FakeVectorStore([_chunk(0)]),
        reranker=_FakeReranker(),
        embedding=_FakeEmbedding(raises=RuntimeError("embedding backend down")),
    )
    with pytest.raises(RuntimeError, match="embedding backend down"):
        await pipeline.retrieve(request_id=uuid.uuid4(), query=_QUERY)

    retrieve = tracer.by_name("rag.retrieve")
    assert retrieve.ended is True
    assert isinstance(retrieve.exception, RuntimeError)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raised, expected",
    [
        (asyncio.TimeoutError(), ProviderTimeoutError),
        (ProviderError(kind=ProviderErrorKind.timeout, message="slow"), ProviderTimeoutError),
        (ProviderError(kind=ProviderErrorKind.upstream, message="bad"), ProviderExecutionError),
        (RuntimeError("boom"), ProviderExecutionError),
    ],
)
async def test_generation_failures_keep_their_exact_translation(tracer, raised, expected):
    class _Failing:
        async def generate(self, input):
            raise raised

    service = ChatService(provider=_Failing(), timeout_s=5.0)
    with pytest.raises(expected):
        await service.run(request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="q")])

    generate = tracer.by_name("rag.generate")
    assert generate.ended is True
    assert generate.attributes["rag.generation_outcome"] in {
        "timeout",
        "provider_error",
        "error",
    }


@pytest.mark.asyncio
async def test_results_are_identical_with_tracing_on_and_off():
    request_id = uuid.uuid4()

    tracing.configure_for_testing(None)
    off = await _full_pipeline().retrieve(request_id=request_id, query=_QUERY)

    tracing.configure_for_testing(_StackTracer())
    try:
        on = await _full_pipeline().retrieve(request_id=request_id, query=_QUERY)
    finally:
        tracing.configure_for_testing(None)

    assert off.rewritten_query == on.rewritten_query
    assert off.fallback_triggered == on.fallback_triggered
    assert off.evaluator_triggered == on.evaluator_triggered
    assert off.evaluator_verdict == on.evaluator_verdict
    assert [c.rank for c in off.chunks] == [c.rank for c in on.chunks]


@pytest.mark.asyncio
async def test_a_raising_tracer_does_not_change_pipeline_results():
    """AC2 at the stage level: a broken tracer leaves the result untouched."""

    class _RaisingTracer:
        def start_as_current_span(self, name):
            raise RuntimeError("tracer is broken")

    tracing.configure_for_testing(None)
    baseline = await _full_pipeline().retrieve(request_id=uuid.uuid4(), query=_QUERY)

    tracing.configure_for_testing(_RaisingTracer())
    try:
        broken = await _full_pipeline().retrieve(request_id=uuid.uuid4(), query=_QUERY)
    finally:
        tracing.configure_for_testing(None)

    assert broken.rewritten_query == baseline.rewritten_query
    assert broken.evaluator_verdict == baseline.evaluator_verdict
    assert [c.rank for c in broken.chunks] == [c.rank for c in baseline.chunks]


# --- Content-free ----------------------------------------------------------


@pytest.mark.asyncio
async def test_no_stage_emits_an_undeclared_key(tracer):
    await _full_pipeline().retrieve(request_id=uuid.uuid4(), query=_QUERY)
    service = ChatService(provider=_FakeProvider(rewritten="answer"), timeout_s=5.0)
    await service.run(request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="q")])

    for current in tracer.spans:
        undeclared = set(current.attributes) - schema.ALLOWED_ATTRIBUTE_KEYS
        assert undeclared == set(), f"{current.name} emitted {undeclared}"
    assert tracing.rejected_attribute_keys() == ()


@pytest.mark.asyncio
async def test_no_span_attribute_carries_query_or_chunk_text(tracer):
    await _full_pipeline().retrieve(request_id=uuid.uuid4(), query=_QUERY)

    emitted = [
        str(value)
        for current in tracer.spans
        for value in current.attributes.values()
    ]
    for marker in (_QUERY, _REWRITTEN, "chunk 0", "chunk 4"):
        assert not any(marker in value for value in emitted), f"leaked: {marker}"


# --- Streaming generation --------------------------------------------------


class _StreamSession:
    def __init__(self, chunks, *, final_content=None) -> None:
        self.chunks = chunks
        self._final = final_content if final_content is not None else "".join(
            c for c in getattr(chunks, "_static", []) or []
        )

    async def get_final_result(self):
        from app.core.domain.provider import ProviderStreamResult

        return ProviderStreamResult(
            content=self._final,
            provider_result=ProviderResult(
                content=self._final,
                provider="stub",
                model_version="v1",
                prompt_version="v1",
            ),
        )


class _StreamingProvider:
    """A provider with a real `stream`, so ChatService takes the streaming path."""

    def __init__(self, tokens, *, raise_after=None) -> None:
        self._tokens = tokens
        self._raise_after = raise_after

    async def generate(self, input):
        return ProviderResult(
            content="".join(self._tokens), provider="stub", model_version="v1", prompt_version="v1"
        )

    async def stream(self, input):
        tokens = self._tokens
        raise_after = self._raise_after

        async def _chunks():
            for index, token in enumerate(tokens):
                if raise_after is not None and index == raise_after:
                    raise RuntimeError("provider stream broke")
                yield token

        return _StreamSession(_chunks(), final_content="".join(tokens))


async def _drain(service, **kwargs):
    session = await service.stream_chat(
        request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="q")], **kwargs
    )
    return [chunk async for chunk in session.chunks]


@pytest.mark.asyncio
async def test_streaming_success_emits_exactly_one_generate_span(tracer):
    service = ChatService(provider=_StreamingProvider(["a", "b", "c"]), timeout_s=5.0)
    assert await _drain(service) == ["a", "b", "c"]

    generate = tracer.by_name("rag.generate")
    assert generate.ended is True
    assert generate.attributes["rag.generation_outcome"] == "ok"


@pytest.mark.asyncio
async def test_span_opens_on_first_pull_not_when_the_session_is_obtained(tracer):
    """The span must cover generation, not session setup."""
    service = ChatService(provider=_StreamingProvider(["a", "b"]), timeout_s=5.0)
    session = await service.stream_chat(
        request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="q")]
    )
    assert tracer.names() == []  # nothing opened yet

    iterator = session.chunks.__aiter__()
    await iterator.__anext__()
    assert tracer.names() == ["rag.generate"]
    assert tracer.by_name("rag.generate").ended is False  # still open mid-stream

    await iterator.aclose()


@pytest.mark.asyncio
async def test_a_provider_stream_error_closes_the_span_and_still_propagates(tracer):
    service = ChatService(
        provider=_StreamingProvider(["a", "b", "c"], raise_after=1), timeout_s=5.0
    )
    with pytest.raises(RuntimeError, match="provider stream broke"):
        await _drain(service)

    generate = tracer.by_name("rag.generate")
    assert generate.ended is True
    assert generate.attributes["rag.generation_outcome"] == "error"


@pytest.mark.asyncio
async def test_client_disconnect_mid_stream_closes_the_span(tracer):
    """A closed generator raises GeneratorExit, which is BaseException -- an
    `except Exception` would have left the span open forever."""
    service = ChatService(provider=_StreamingProvider(["a", "b", "c"]), timeout_s=5.0)
    session = await service.stream_chat(
        request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="q")]
    )
    iterator = session.chunks.__aiter__()
    assert await iterator.__anext__() == "a"
    await iterator.aclose()

    generate = tracer.by_name("rag.generate")
    assert generate.ended is True
    assert generate.attributes["rag.generation_outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_streamed_chunks_are_byte_identical_with_tracing_on_and_off():
    tokens = ["hola ", "mundo", "", " ñ", "\n\ndata: not-a-frame"]

    tracing.configure_for_testing(None)
    off = await _drain(ChatService(provider=_StreamingProvider(tokens), timeout_s=5.0))

    tracing.configure_for_testing(_StackTracer())
    try:
        on = await _drain(ChatService(provider=_StreamingProvider(tokens), timeout_s=5.0))
    finally:
        tracing.configure_for_testing(None)

    assert off == on == tokens


@pytest.mark.asyncio
async def test_a_raising_tracer_does_not_change_the_stream():
    class _RaisingTracer:
        def start_as_current_span(self, name):
            raise RuntimeError("tracer is broken")

    tokens = ["a", "b", "c"]
    tracing.configure_for_testing(_RaisingTracer())
    try:
        streamed = await _drain(ChatService(provider=_StreamingProvider(tokens), timeout_s=5.0))
    finally:
        tracing.configure_for_testing(None)

    assert streamed == tokens


@pytest.mark.asyncio
async def test_final_result_is_unchanged_by_the_wrapper(tracer):
    service = ChatService(provider=_StreamingProvider(["a", "b"]), timeout_s=5.0)
    session = await service.stream_chat(
        request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="q")]
    )
    assert [c async for c in session.chunks] == ["a", "b"]
    final = await session.get_final_result()
    assert final.assistant_message.content == "ab"
    assert final.provider_result is not None


@pytest.mark.asyncio
async def test_a_provider_without_stream_is_not_double_counted(tracer):
    """The fallback path delegates to run(), which emits its own span."""
    service = ChatService(provider=_FakeProvider(rewritten="answer"), timeout_s=5.0)
    assert await _drain(service) == ["answer"]
    assert tracer.names().count("rag.generate") == 1
