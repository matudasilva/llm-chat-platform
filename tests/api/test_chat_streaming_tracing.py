"""ORQ-37 T2 — the SSE body is byte-identical with tracing on and off (AC2).

Route-level counterpart to the chunk-level assertions in
`tests/core/test_tracing_pipeline_stages.py`. `/chat` is not modified by this
test or by T2; it is driven exactly as `tests/api/test_chat_streaming.py`
drives it, and the raw response body is compared after normalizing the
request-scoped UUID fields, which differ per request by design.
"""

from __future__ import annotations

import re
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


async def _raw_sse_body() -> str:
    response = await chat(
        ChatRequest(message="hello", stream=True),
        db=_FakeAsyncSession(),
        chat_service=ChatService(provider=_StreamingProvider(), timeout_s=1.0),
    )
    parts: list[str] = []
    async for chunk in response.body_iterator:
        parts.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return _UUID.sub("<uuid>", "".join(parts))


@pytest.mark.asyncio
async def test_sse_body_is_byte_identical_with_tracing_disabled_and_enabled():
    tracing.configure_for_testing(None)
    try:
        disabled = await _raw_sse_body()

        tracing.configure_for_testing(_WorkingTracer())
        enabled = await _raw_sse_body()

        tracing.configure_for_testing(_RaisingTracer())
        broken = await _raw_sse_body()
    finally:
        tracing.configure_for_testing(None)

    assert enabled == disabled
    assert broken == disabled
    # The body is real, so equality is not equality of two empty strings.
    assert "event: token" in disabled and "event: done" in disabled
    assert disabled.count("event: token") == len(_TOKENS)


# --- AC2's remaining halves: non-streaming /chat and /retrieval -------------


async def _non_streaming_body() -> str:
    response = await chat(
        ChatRequest(message="hello", stream=False),
        db=_FakeAsyncSession(),
        chat_service=ChatService(provider=_StreamingProvider(), timeout_s=1.0),
    )
    return _UUID.sub("<uuid>", response.model_dump_json())


@pytest.mark.asyncio
async def test_non_streaming_chat_is_identical_with_tracing_disabled_and_enabled():
    tracing.configure_for_testing(None)
    try:
        disabled = await _non_streaming_body()

        tracing.configure_for_testing(_WorkingTracer())
        enabled = await _non_streaming_body()

        tracing.configure_for_testing(_RaisingTracer())
        broken = await _non_streaming_body()
    finally:
        tracing.configure_for_testing(None)

    assert enabled == disabled
    assert broken == disabled
    assert "hello mundo" in disabled  # a real body, not two empty strings


@pytest.mark.asyncio
async def test_retrieval_is_identical_with_tracing_disabled_and_enabled(monkeypatch):
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
    finally:
        tracing.configure_for_testing(None)

    assert enabled == disabled
    assert broken == disabled
    assert "rewritten query" in disabled
