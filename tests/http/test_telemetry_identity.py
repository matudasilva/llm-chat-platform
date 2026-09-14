"""ORQ-37 Gate A/B1, T8-identity — AC32, AC26, AC3, and AC2's remaining halves.

R18 in one sentence: `request_id` is taken from the inbound `X-Request-ID`
verbatim, so anything reading it is reading client-controlled text. T8 does not
change that field -- existing consumers and response headers depend on it -- it
adds a **server-generated** identity beside it and lets telemetry use only that.

AC25 is deliberately **not** covered here: it asserts the uniqueness constraint
on `rag_request_metrics`, and that table is T14's.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest

from app.core.observability import schema, tracing
from app.http import pipeline_metrics
from app.http.middleware.request_context import RequestContextMiddleware
from app.http.request_context import (
    get_request_id,
    get_request_instance_id,
    get_telemetry_correlation_id,
    validate_correlation_id,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class _Span:
    def __init__(self, name, parent):
        self.name, self.parent = name, parent
        self.children, self.attributes = [], {}
        self.ended = False

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _StackTracer:
    def __init__(self):
        self.stack, self.spans = [], []

    def start_as_current_span(self, name):
        parent = self.stack[-1] if self.stack else None
        current = _Span(name, parent)
        if parent:
            parent.children.append(current)
        self.spans.append(current)
        tracer = self

        class _CM:
            def __enter__(self):
                tracer.stack.append(current)
                return current

            def __exit__(self, *exc):
                current.ended = True
                tracer.stack.pop()
                return False

        return _CM()

    def by_name(self, name):
        found = [s for s in self.spans if s.name == name]
        assert len(found) == 1, f"expected one {name}, got {len(found)}"
        return found[0]


@pytest.fixture
def tracer():
    double = _StackTracer()
    tracing.configure_for_testing(double)
    yield double
    tracing.configure_for_testing(None)


async def _drive(app_inner, *, headers=None):
    """Run one HTTP request through the middleware and return (status, captured)."""
    captured: dict = {}
    sent: list = []

    async def _send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "headers": [(k.lower(), v) for k, v in (headers or [])],
    }

    async def _inner(scope, receive, send):
        captured["request_id"] = get_request_id()
        captured["instance_id"] = get_request_instance_id()
        captured["correlation_id"] = get_telemetry_correlation_id()
        captured["collector"] = pipeline_metrics.get_collector()
        if app_inner is not None:
            await app_inner(captured)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    await RequestContextMiddleware(_inner)(scope, None, _send)
    return sent, captured


# --- AC32: identity is server-generated; the header is only correlation ----


@pytest.mark.asyncio
async def test_identity_is_minted_even_with_no_inbound_header():
    _, captured = await _drive(None)
    uuid.UUID(captured["instance_id"])  # raises if not a UUID
    assert captured["correlation_id"] is None


@pytest.mark.asyncio
async def test_a_valid_inbound_header_becomes_correlation_never_identity():
    supplied = str(uuid.uuid4())
    _, captured = await _drive(None, headers=[(b"x-request-id", supplied.encode())])

    assert captured["correlation_id"] == supplied
    assert captured["instance_id"] != supplied
    uuid.UUID(captured["instance_id"])


@pytest.mark.asyncio
async def test_two_requests_replaying_one_header_get_distinct_identities():
    """The property AC25 will rest on at T14: a replayed header must not be
    able to collapse two requests into one identity."""
    supplied = str(uuid.uuid4()).encode()
    _, first = await _drive(None, headers=[(b"x-request-id", supplied)])
    _, second = await _drive(None, headers=[(b"x-request-id", supplied)])

    assert first["instance_id"] != second["instance_id"]
    assert first["correlation_id"] == second["correlation_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile, label",
    [
        (b"not-a-uuid", "garbage"),
        (b"x" * 8192, "8 KB of text"),
        (b"\x00\x01\x02control", "control characters"),
        (b"\n\nevent: done\ndata: {}", "SSE frame forgery"),
        (b"'; DROP TABLE messages; --", "SQL-shaped"),
        (b"\xff\xfe\xfd", "invalid UTF-8"),
        (b"   ", "whitespace only"),
    ],
)
async def test_a_hostile_header_is_dropped_entirely(hostile, label):
    """Dropped, not truncated and not emitted in another form: an allow-list
    over attribute *keys* cannot constrain attribute *values*."""
    _, captured = await _drive(None, headers=[(b"x-request-id", hostile)])

    assert captured["correlation_id"] is None, label
    uuid.UUID(captured["instance_id"])


@pytest.mark.asyncio
async def test_a_hostile_header_never_reaches_a_span_attribute(tracer):
    hostile = b"\x00ignore-previous-instructions" + b"z" * 4000
    await _drive(None, headers=[(b"x-request-id", hostile)])

    request_span = tracer.by_name(schema.REQUEST_SPAN)
    assert set(request_span.attributes) == {"request.instance_id"}
    for value in request_span.attributes.values():
        assert "ignore-previous-instructions" not in str(value)


@pytest.mark.asyncio
async def test_the_span_carries_correlation_only_when_the_header_validated(tracer):
    supplied = str(uuid.uuid4())
    await _drive(None, headers=[(b"x-request-id", supplied.encode())])

    attributes = tracer.by_name(schema.REQUEST_SPAN).attributes
    assert attributes["request.correlation_id"] == supplied
    assert attributes["request.instance_id"] != supplied


@pytest.mark.asyncio
async def test_responses_are_unchanged_by_any_of_this():
    """The existing X-Request-ID / X-Correlation-ID response contract is not
    this ORQ's to change, and is asserted to be intact."""
    supplied = b"a-legacy-non-uuid-request-id"
    sent, captured = await _drive(None, headers=[(b"x-request-id", supplied)])

    start = next(m for m in sent if m["type"] == "http.response.start")
    echoed = dict(start["headers"])
    assert echoed[b"x-request-id"] == supplied
    assert captured["request_id"] == supplied.decode()  # legacy field untouched


def test_validation_canonicalises_rather_than_echoing_the_raw_string():
    """`UUID` accepts hyphenless input, so echoing the raw string would let a
    non-canonical spelling through under a validated name."""
    canonical = str(uuid.uuid4())
    assert validate_correlation_id(canonical) == canonical
    assert validate_correlation_id(canonical.replace("-", "")) == canonical


def test_the_length_bound_fires_before_the_parser():
    """The 36-character bound is checked first, so the braced and `urn:uuid:`
    spellings `UUID` would otherwise accept are rejected on length alone. That
    ordering is the point: it keeps oversized input away from the parser
    entirely, and it makes the accepted set exactly the canonical 36-character
    form (plus the 32-character hyphenless one)."""
    canonical = str(uuid.uuid4())
    assert validate_correlation_id("{" + canonical + "}") is None  # 38 chars
    assert validate_correlation_id("urn:uuid:" + canonical) is None  # 45 chars
    assert len(canonical) == 36 and validate_correlation_id(canonical) == canonical


# --- AC26: the collector -----------------------------------------------------


@pytest.mark.asyncio
async def test_the_collector_exists_on_every_request_regardless_of_flags(monkeypatch):
    from app.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "chat_rag_augmentation_enabled", False)
    _, captured = await _drive(None)

    collector = captured["collector"]
    assert collector is not None
    assert collector.snapshot()["request_instance_id"] == captured["instance_id"]


@pytest.mark.asyncio
async def test_the_collector_is_reset_after_the_request():
    await _drive(None)
    assert pipeline_metrics.get_collector() is None


@pytest.mark.asyncio
async def test_the_collector_carries_the_server_identity_not_the_header():
    supplied = str(uuid.uuid4())
    _, captured = await _drive(None, headers=[(b"x-request-id", supplied.encode())])

    snapshot = captured["collector"].snapshot()
    assert snapshot["request_instance_id"] == captured["instance_id"]
    assert snapshot["request_instance_id"] != supplied
    assert snapshot["request_id"] == supplied  # advisory correlation only


@pytest.mark.asyncio
async def test_recording_is_a_no_op_outside_a_request():
    pipeline_metrics.record(mode="A")  # must not raise


@pytest.mark.asyncio
async def test_a_snapshot_is_a_copy():
    async def _write(captured):
        captured["snapshot"] = captured["collector"].snapshot()
        captured["collector"].record(mode="B")

    _, captured = await _drive(_write)
    assert "mode" not in captured["snapshot"]
    assert captured["collector"].snapshot()["mode"] == "B"


def test_a_request_rejected_by_the_size_limit_never_reaches_the_collector():
    """`add_middleware` is LIFO: RequestContextMiddleware is added first and is
    innermost, RequestSizeLimitMiddleware is added second and sits outside it.
    A rejected request therefore produces no row -- declared, not accidental."""
    main = (REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert main.index("add_middleware(RequestContextMiddleware)") < main.index(
        "add_middleware(RequestSizeLimitMiddleware"
    )


def test_every_dependency_writing_to_the_collector_is_async():
    """FastAPI runs a *sync* dependency in a threadpool under a copied context,
    where `ContextVar.set()` does not propagate back -- a sync writer would
    appear to work and silently lose every field."""
    offenders = []
    for path in (REPO_ROOT / "app").rglob("*.py"):
        # The collector module defines the API; it is not a consumer of it.
        if path.name == "pipeline_metrics.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):  # sync def only
                body = ast.dump(node)
                # Writers, not readers: `record` is the only mutating entry
                # point, and it is what a copied context would silently lose.
                if "pipeline_metrics" in body and "record" in body:
                    offenders.append(f"{path.name}:{node.name}")
    assert offenders == [], f"sync functions writing to the collector: {offenders}"

    # The scan must be able to fail, or it asserts nothing. A sync function
    # that writes is detected by the same logic, verified on a constructed one.
    sample = ast.parse(
        "def bad():\n    from app.http import pipeline_metrics\n"
        "    pipeline_metrics.record(mode='A')\n"
    )
    node = next(n for n in ast.walk(sample) if isinstance(n, ast.FunctionDef))
    dumped = ast.dump(node)
    assert "pipeline_metrics" in dumped and "record" in dumped


# --- AC3: the span tree -------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_spans_are_children_of_the_request_span(tracer):
    """The tree AC3 requires, assembled through the real middleware and the
    real pipeline/ChatService code paths."""
    from tests.core.test_tracing_pipeline_stages import (
        _FakeEmbedding,
        _FakeProvider,
        _FakeReranker,
        _FakeVectorStore,
        _chunk,
    )
    from app.core.domain.chat_service import ChatService
    from app.core.domain.reranker import RankedDocument
    from app.core.domain.retrieval_pipeline import RetrievalPipeline
    from app.core.domain.types import ChatMessage

    async def _work(captured):
        pipeline = RetrievalPipeline(
            provider=_FakeProvider(rewritten="rewritten"),
            embedding=_FakeEmbedding(),
            vector_store=_FakeVectorStore([_chunk(i) for i in range(3)]),
            reranker=_FakeReranker(results=[RankedDocument(index=0, rank=1)]),
            min_reranked_results=5,
        )
        await pipeline.retrieve(request_id=uuid.uuid4(), query="q")
        await ChatService(provider=_FakeProvider(rewritten="answer"), timeout_s=5.0).run(
            request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="q")]
        )

    _, captured = await _drive(_work)

    request_span = tracer.by_name(schema.REQUEST_SPAN)
    assert [c.name for c in request_span.children] == [
        "rag.rewrite",
        "rag.retrieve",
        "rag.rerank",
        "rag.evaluate",
        "rag.generate",
    ]
    assert request_span.attributes["request.instance_id"] == captured["instance_id"]
    assert all(child.ended for child in request_span.children)
    assert request_span.ended


@pytest.mark.asyncio
async def test_every_emitted_attribute_key_is_declared(tracer):
    await _drive(None, headers=[(b"x-request-id", str(uuid.uuid4()).encode())])
    for current in tracer.spans:
        assert set(current.attributes) <= schema.ALLOWED_ATTRIBUTE_KEYS


@pytest.mark.asyncio
async def test_nothing_carries_a_bare_request_id_key(tracer):
    await _drive(None)
    for current in tracer.spans:
        assert "request_id" not in current.attributes


# --- AC2: a faulty tracer changes nothing at the middleware ------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", [True, False])
async def test_a_faulty_tracer_leaves_the_response_and_context_intact(broken):
    class _RaisingTracer:
        def start_as_current_span(self, name):
            raise RuntimeError("tracer is broken")

    tracing.configure_for_testing(_RaisingTracer() if broken else None)
    try:
        sent, captured = await _drive(None)
    finally:
        tracing.configure_for_testing(None)

    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 200
    assert captured["collector"] is not None
    uuid.UUID(captured["instance_id"])
    assert pipeline_metrics.get_collector() is None  # resets still ran
