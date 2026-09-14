"""ORQ-37 H4/H6/H9 -- the three Group A findings from the H3-H11 triage.

Each was confirmed against the code before being fixed, and each test here
fails if its fix is reverted:

H9  a punctuation-only out-of-window corpus made `rank_events` raise
    `ValueError` from OUTSIDE the dependency's degradation boundary, so a
    Mode B request 500'd instead of degrading to Mode A.
H6  the response cache consulted only `chat_rag_augmentation_enabled`, so
    with `ebm25_enabled=true` and augmentation off the cache stayed live and
    could serve an answer built on different retrieved evidence. ADR-013 §9
    documented this bypass as extended; the code never was.
H4  `rag.evaluator_verdict` carried `result.content.strip().upper()` with no
    check on the value, so an evaluator echoing its input put query and
    passage text into a span attribute. AC4 forbids any attribute VALUE
    carrying query, chunk or message content.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.api.routes.chat as chat_routes
from app.api import deps
from app.core.domain.conversation_history import HistoryMessage
from app.http import pipeline_metrics



# --- H9: a corpus with no lexical tokens degrades, it does not raise -------


def _install_history(monkeypatch, history):
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
def collector():
    instance, token = pipeline_metrics.init_collector(
        request_instance_id=str(uuid.uuid4()), correlation_id=None
    )
    try:
        yield instance
    finally:
        pipeline_metrics.reset_collector(token)


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


@pytest.mark.asyncio
async def test_punctuation_only_corpus_degrades_instead_of_raising(
    mode_b_on, collector, monkeypatch
) -> None:
    """H9. `bm25_ranking.py:94` raises when average token length is zero, and
    nothing requires stored history to contain alphanumeric tokens."""
    _install_history(
        monkeypatch,
        [
            # Out-of-window turn with no lexical tokens at all.
            HistoryMessage(sequence=1, role="user", content="!!!"),
            HistoryMessage(sequence=2, role="assistant", content="???"),
            # In-window turn, well-formed and perfectly usable.
            HistoryMessage(sequence=3, role="user", content="what is the plan"),
            HistoryMessage(sequence=4, role="assistant", content="the plan is ready"),
        ],
    )

    # The assertion is that this returns at all rather than propagating.
    result = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=uuid.uuid4(), message="plan"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )

    # Degrades to Mode A: the window survives, only the evidence is dropped.
    assert [m.content for m in result.messages] == ["what is the plan", "the plan is ready"]
    assert result.retrieved_events == ()
    # The failure is visible in telemetry rather than silently absorbed.
    assert collector.snapshot()["memory_outcome"] == "error"
    assert collector.snapshot()["ebm25_selected_count"] == 0


@pytest.mark.asyncio
async def test_a_normal_corpus_is_unaffected_by_the_degradation_boundary(
    mode_b_on, collector, monkeypatch
) -> None:
    """The mirror: the boundary must not swallow a working Mode B."""
    _install_history(
        monkeypatch,
        [
            HistoryMessage(sequence=1, role="user", content="the plan for launch"),
            HistoryMessage(sequence=2, role="assistant", content="launch is scheduled"),
            HistoryMessage(sequence=3, role="user", content="anything else"),
            HistoryMessage(sequence=4, role="assistant", content="no"),
        ],
    )

    result = await deps.get_chat_memory_context(
        SimpleNamespace(conversation_id=uuid.uuid4(), message="launch plan"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )

    assert result.retrieved_events != ()
    assert collector.snapshot()["memory_outcome"] != "error"


# --- H6: the cache bypass covers ebm25_enabled ----------------------------


def test_cache_is_bypassed_for_ebm25_even_with_augmentation_off(monkeypatch) -> None:
    """H6/AC17. The configuration ADR-013 §9 named explicitly:
    `ebm25_enabled=true, chat_rag_augmentation_enabled=false`."""
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", False)
    monkeypatch.setattr(chat_routes.settings, "ebm25_enabled", True)
    assert chat_routes._cache_bypass_reason() == "ebm25_memory"


def test_cache_is_live_when_neither_channel_is_enabled(monkeypatch) -> None:
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", False)
    monkeypatch.setattr(chat_routes.settings, "ebm25_enabled", False)
    assert chat_routes._cache_bypass_reason() is None


def test_documental_augmentation_still_takes_the_original_reason(monkeypatch) -> None:
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(chat_routes.settings, "ebm25_enabled", True)
    assert chat_routes._cache_bypass_reason() == "rag_augmentation"


class _CountingCache:
    """Counts what the route actually does to the cache, not what it asks."""

    def __init__(self) -> None:
        self.gets = 0
        self.sets = 0
        self.bypasses: list[str] = []

    async def get(self, **kwargs):
        self.gets += 1
        return None

    async def set(self, **kwargs):
        self.sets += 1

    def log_bypass(self, *, reason):
        self.bypasses.append(reason)


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self) -> None:
        self.objects: list[object] = []

    def begin(self):
        return _Transaction()

    def add(self, obj) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        return None


class _StubChatService:
    async def run(self, *, request_id, messages, provider_metadata=None):
        from app.core.domain.chat_types import ChatServiceResult
        from app.core.domain.provider import ProviderResult
        from app.core.domain.types import ChatMessage as _CM

        return ChatServiceResult(
            request_id=request_id,
            assistant_message=_CM(role="assistant", content="answer"),
            provider_result=ProviderResult(
                content="answer", provider="stub", model_version="v1", prompt_version="v1"
            ),
        )


async def _drive_route(monkeypatch, *, augmentation: bool, ebm25: bool) -> _CountingCache:
    from app.schemas.chat import ChatRequest

    cache = _CountingCache()
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", augmentation)
    monkeypatch.setattr(chat_routes.settings, "ebm25_enabled", ebm25)
    monkeypatch.setattr(chat_routes.settings, "conversation_history_enabled", False)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache)
    await chat_routes.chat(
        ChatRequest(message="a question"),
        db=_Session(),
        chat_service=_StubChatService(),
    )
    return cache


@pytest.mark.asyncio
async def test_the_cache_is_neither_read_nor_written_under_mode_b(monkeypatch) -> None:
    """H6, asserted on BEHAVIOUR rather than on the shape of the source.

    The first version of this test counted three `_cache_bypass_reason()`
    call sites. Independent re-validation mutated the gates to call the
    helper and ignore its answer, and all nine tests still passed -- the
    structural count could not see it. This drives the real route and counts
    what it actually does to the cache, which that mutation cannot survive.
    """
    cache = await _drive_route(monkeypatch, augmentation=False, ebm25=True)

    assert cache.gets == 0, "Mode B must not READ a key that cannot see its evidence"
    assert cache.sets == 0, "Mode B must not WRITE one either"
    assert cache.bypasses == ["ebm25_memory"]


@pytest.mark.asyncio
async def test_the_cache_is_live_when_no_channel_needs_a_bypass(monkeypatch) -> None:
    """The mirror, and the reason the test above is not vacuous: with both
    flags off the very same route DOES read and write."""
    cache = await _drive_route(monkeypatch, augmentation=False, ebm25=False)

    assert cache.gets == 1
    assert cache.sets == 1
    assert cache.bypasses == []


# --- H4: an allow-listed attribute may not carry content ------------------


@pytest.mark.asyncio
async def test_an_echoing_evaluator_verdict_never_reaches_the_span_attribute(
    monkeypatch,
) -> None:
    """H4/AC4, driving the REAL `_evaluate`.

    An earlier draft of this test re-implemented the guard inline and proved
    nothing about shipped code. This one builds a real `RetrievalPipeline`,
    gives it a provider double that echoes its input (a legitimate provider
    behaviour, and exactly the shape independent validation used), captures
    every attribute the real code sets, and asserts the marker never appears
    in any of them.
    """
    from app.core.domain import retrieval_pipeline as rp

    captured: dict[str, object] = {}
    monkeypatch.setattr(rp, "set_attribute", lambda span, key, value: captured.__setitem__(key, value))

    MARKER = "SECRET_DOCUMENT_MARKER"

    class _EchoingProvider:
        async def generate(self, provider_input):
            # Echoes the user message back, verbatim -- query and passages.
            echoed = provider_input.messages[-1].content
            return SimpleNamespace(content=echoed)

    pipeline = rp.RetrievalPipeline.__new__(rp.RetrievalPipeline)
    pipeline._provider = _EchoingProvider()

    verdict = await pipeline._evaluate(
        request_id=uuid.uuid4(),
        query=f"what about {MARKER}",
        chunks=[],
    )

    # The attribute must not carry it, however the evaluator misbehaved.
    assert MARKER not in str(captured.get("rag.evaluator_verdict"))
    assert captured["rag.evaluator_verdict"] == "unrecognized"
    # The RETURN value is deliberately untouched: what the pipeline does with
    # an unexpected verdict is abstention behaviour, which §No-alcance
    # excludes from this ORQ.
    assert MARKER in verdict


@pytest.mark.asyncio
async def test_an_expected_verdict_still_reaches_the_attribute(monkeypatch) -> None:
    """The mirror: the guard must not blind the attribute in the normal case."""
    from app.core.domain import retrieval_pipeline as rp

    captured: dict[str, object] = {}
    monkeypatch.setattr(rp, "set_attribute", lambda span, key, value: captured.__setitem__(key, value))

    class _WellBehavedProvider:
        async def generate(self, provider_input):
            return SimpleNamespace(content="sufficient")

    pipeline = rp.RetrievalPipeline.__new__(rp.RetrievalPipeline)
    pipeline._provider = _WellBehavedProvider()

    verdict = await pipeline._evaluate(request_id=uuid.uuid4(), query="q", chunks=[])

    assert captured["rag.evaluator_verdict"] == "SUFFICIENT"
    assert verdict == "SUFFICIENT"


def test_the_two_expected_verdicts_still_pass_through() -> None:
    from app.core.domain import retrieval_pipeline

    assert "SUFFICIENT" in retrieval_pipeline._EVALUATOR_VERDICTS
    assert "INSUFFICIENT" in retrieval_pipeline._EVALUATOR_VERDICTS
    # The evaluator prompt and the allow-list cannot drift apart silently.
    assert "SUFFICIENT or INSUFFICIENT" in retrieval_pipeline._EVALUATOR_PROMPT
