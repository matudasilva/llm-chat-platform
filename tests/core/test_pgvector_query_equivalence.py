"""Real-PG equivalence to the frozen pre-remediation hybrid retrieval query.

The reference is self-contained; tests do not depend on ORQ artifact paths.
Administrative seeding is limited to fresh test tenants. All retrieval assertions
use rag_app/read-only transactions, including an unscoped connection for RLS.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, nullcontext
import hashlib
import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.providers.pgvector_store import PgVectorStore
from app.http.middleware.tenant import tenant_scope
from app.infra.db.session import build_rag_sessionmaker

pytestmark = pytest.mark.postgres
_MODES = ("force_custom_plan", "force_generic_plan")
_NEAR = [1.0] + [0.0] * 1535
_FAR = [0.0] * 1535 + [1.0]
_DEEP_TEXT = " ".join("lexeme" + str(i) for i in range(131072))


def _url(name):
    value = os.environ.get(name)
    if not value:
        pytest.skip(name + " must identify disposable PostgreSQL")
    return value


def _vector(values):
    return "[" + ",".join(str(float(v)) for v in values) + "]"


@asynccontextmanager
async def _session(url, tenant, mode):
    assert mode in _MODES
    if tenant is None:
        engine = create_async_engine(url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
    else:
        factory = build_rag_sessionmaker(url)
        engine = factory.kw["bind"]
    try:
        with tenant_scope(tenant) if tenant is not None else nullcontext():
            async with factory() as session:
                try:
                    await session.connection(execution_options={"postgresql_readonly": True})
                    await session.execute(text("SET LOCAL statement_timeout='10s'"))
                    await session.execute(text("SET LOCAL plan_cache_mode=" + mode))
                    state = (await session.execute(text(
                        "SELECT current_user,session_user,"
                        "(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),"
                        "(SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user),"
                        "current_setting('row_security'),current_setting('transaction_read_only'),"
                        "current_setting('plan_cache_mode'),current_setting('app.tenant_id',true)"
                    ))).one()
                    assert state[:2] == ("rag_app", "rag_app")
                    assert state[2:4] == (False, False)
                    assert state[4:7] == ("on", "on", mode)
                    assert state[7] == tenant
                    yield session
                finally:
                    await session.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def corpus():
    """Disjoint tenants with out-of-ID-order semantic/keyword/overlap ties."""
    admin = create_async_engine(_url("RAG_TEST_DATABASE_URL"))
    tenant_a, tenant_b = "lex-a-" + uuid.uuid4().hex, "lex-b-" + uuid.uuid4().hex
    docs = {tenant_a: uuid.uuid4(), tenant_b: uuid.uuid4()}
    ids = {tenant_a: set(), tenant_b: set()}
    base = uuid.uuid4().int & ~((1 << 32) - 1)
    groups = [
        (tenant_a, [30, 10, 20], "zeta zeta", _NEAR),
        (tenant_a, [60, 40, 50], "alpha alpha", _FAR),
        (tenant_a, [90, 70, 80], "alpha beta", _NEAR),
        (tenant_a, [120, 110], "café recuperación contacto", _FAR),
        (tenant_b, [1030, 1010, 1020], "alpha private other tenant", _NEAR),
    ]
    try:
        async with admin.begin() as conn:
            for tenant, did in docs.items():
                await conn.execute(text(
                    "INSERT INTO documents(id,tenant_id,source_path,content_hash,doc_type)"
                    " VALUES(:id,:tenant,'equivalence.md','test-hash','markdown')"
                ), dict(id=did, tenant=tenant))
            ordinal = 0
            for tenant, offsets, body, embedding in groups:
                for offset in offsets:
                    cid = uuid.UUID(int=base + offset)
                    ids[tenant].add(cid)
                    await conn.execute(text(
                        "INSERT INTO chunks(id,document_id,tenant_id,ordinal,text,embedding,search_vector,metadata)"
                        " VALUES(:id,:doc,:tenant,:ordinal,:body,CAST(:vector AS vector),"
                        "to_tsvector('english',:body),CAST(:metadata AS jsonb))"
                    ), dict(id=cid, doc=docs[tenant], tenant=tenant, ordinal=ordinal,
                            body=body, vector=_vector(embedding),
                            metadata=json.dumps({"offset": offset, "nested": [1, None]}) if offset % 20 else None))
                    ordinal += 1
        yield dict(a=tenant_a, b=tenant_b, ids=ids)
    finally:
        async with admin.begin() as conn:
            await conn.execute(text("DELETE FROM documents WHERE id IN (:a,:b)"),
                               dict(a=docs[tenant_a], b=docs[tenant_b]))
        await admin.dispose()


async def _run(variant, tenant, mode, query="alpha", vector=None, top_k=20, empty=False):
    url = _url("RAG_TEST_EMPTY_DATABASE_URL_APP" if empty else "RAG_TEST_DATABASE_URL_APP")
    vector = _NEAR if vector is None else vector
    try:
        async with _session(url, tenant, mode) as session:
            if variant == "original":
                result = await session.execute(text(_REFERENCE_SQL), dict(
                    query_text=query, query_embedding=_vector(vector), top_k=top_k, rrf_k=60))
                rows = [(r.id, r.document_id, r.text, r.metadata, r.score) for r in result]
            else:
                result = await PgVectorStore(session).hybrid_search(query, vector, top_k=top_k)
                rows = [(r.chunk_id, r.document_id, r.text, r.metadata, r.score) for r in result]
            return ("ok", rows)
    except DBAPIError as exc:
        state = getattr(exc.orig, "sqlstate", None)
        if state == "57014":
            pytest.fail("Test query timed out; error equivalence was not established")
        cause = exc.orig.__cause__
        message = getattr(cause, "message", None)
        digest = hashlib.sha256(message.encode()).hexdigest() if message is not None else None
        return ("error", state, type(cause).__name__, digest)


_QUERIES = [
    pytest.param("alpha", id="positive-en"),
    pytest.param("alpha beta", id="overlapping-en"),
    pytest.param("zeta", id="semantic-en"),
    pytest.param("the and", id="stopwords"),
    pytest.param("", id="empty"),
    pytest.param("  ", id="whitespace"),
    pytest.param("!& |()", id="punctuation"),
    pytest.param('"alpha beta"', id="quoted"),
    pytest.param("recuperación contacto", id="positive-es"),
    pytest.param("café", id="unicode"),
    pytest.param("alpha' OR '1'='1", id="quoted-input"),
    pytest.param(None, id="null-query"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("top_k", (0, 1, 2, 3, 20, None))
@pytest.mark.parametrize("query", _QUERIES)
async def test_ordered_full_rows_and_exact_scores_match(corpus, mode, top_k, query):
    expected = await _run("original", corpus["a"], mode, query=query, top_k=top_k)
    actual = await _run("shipped", corpus["a"], mode, query=query, top_k=top_k)
    assert expected[0] == "ok"
    assert actual == expected
    assert {row[0] for row in actual[1]} <= corpus["ids"][corpus["a"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("scope", ("other", "unknown", "unset"))
async def test_tenant_scope_matches_reference(corpus, mode, scope):
    tenant = corpus["b"] if scope == "other" else None if scope == "unset" else "lex-unknown"
    expected = await _run("original", tenant, mode)
    actual = await _run("shipped", tenant, mode)
    assert actual == expected and actual[0] == "ok"
    if scope == "other":
        assert actual[1]
        assert {r[0] for r in actual[1]} <= corpus["ids"][corpus["b"]]
    else:
        assert actual[1] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_positive_keyword_only_candidates_keep_fused_tie_order(corpus, mode):
    # The semantic top three are offsets 10/20/30; keyword top three are
    # 40/50/60. Each pair at equal rank ties on RRF score, so final id wins.
    base = next(iter(corpus["ids"][corpus["a"]])).int & ~((1 << 32) - 1)
    expected_ids = [uuid.UUID(int=base + offset) for offset in (10, 40, 20)]
    for variant in ("original", "shipped"):
        result = await _run(variant, corpus["a"], mode, top_k=3)
        assert result[0] == "ok"
        assert [row[0] for row in result[1]] == expected_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_physical_empty_corpus_matches_reference(mode):
    expected = await _run("original", "lex-empty", mode, empty=True)
    actual = await _run("shipped", "lex-empty", mode, empty=True)
    assert actual == expected == ("ok", [])


@pytest.mark.asyncio
async def test_reference_computational_error_fixture(corpus):
    result = await _run("original", corpus["a"], "force_generic_plan", query=_DEEP_TEXT)
    assert result[0] == "error" and result[1].startswith("54"), result[:3]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("scope", ("visible", "unknown", "unset", "physical-empty"))
@pytest.mark.parametrize("fault", (
    "dimension", "empty-vector", "negative-limit", "deep-text",
    "deep-text-dimension", "deep-text-empty-vector", "deep-text-negative-limit", "deep-text-zero-limit",
    "deep-text-unlimited",
))
async def test_input_error_parity(corpus, mode, scope, fault):
    tenant = corpus["a"] if scope == "visible" else None if scope == "unset" else "lex-unknown"
    kwargs = dict(query=_DEEP_TEXT if fault.startswith("deep-text") else "alpha",
                  vector=[] if "empty-vector" in fault else [1.0] * 1535 if "dimension" in fault else _NEAR,
                  top_k=-1 if "negative-limit" in fault else 0 if "zero-limit" in fault else None if "unlimited" in fault else 20,
                  empty=scope == "physical-empty")
    expected = await _run("original", tenant, mode, **kwargs)
    actual = await _run("shipped", tenant, mode, **kwargs)
    assert actual == expected


class _CaptureStatement:
    calls = 0

    async def execute(self, statement, parameters):
        self.calls += 1
        self.statement, self.parameters = statement, parameters
        return []


def _literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + value.replace("'", "''") + "'"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_plan_materializes_lexical_value_before_chunk_filter(corpus, mode):
    capture = _CaptureStatement()
    await PgVectorStore(capture).hybrid_search("alpha", _NEAR, top_k=3)
    assert capture.calls == 1
    async with _session(_url("RAG_TEST_DATABASE_URL_APP"), corpus["a"], mode) as session:
        compiled = capture.statement.compile(dialect=session.bind.dialect)
        driver = (await (await session.connection()).get_raw_connection()).driver_connection
        name = "lexical_plan_" + uuid.uuid4().hex[:10]
        await driver.execute("PREPARE " + name + " AS " + str(compiled))
        try:
            args = ",".join(_literal(capture.parameters[k]) for k in compiled.positiontup)
            plan = await driver.fetchval("EXPLAIN (ANALYZE TRUE,VERBOSE TRUE,FORMAT JSON) EXECUTE "
                                         + name + "(" + args + ")")
        finally:
            await driver.execute("DEALLOCATE " + name)
        if isinstance(plan, str):
            plan = json.loads(plan)
        producers, semantic_producers = [], []

        def check(node, inside=False):
            producer = node.get("Subplan Name") == "CTE lexical_query"
            if producer:
                producers.append(node)
            if node.get("Subplan Name") == "CTE semantic":
                semantic_producers.append(node)
            here = inside or producer
            if not here:
                fields = {k: v for k, v in node.items() if k != "Plans"}
                assert "plainto_tsquery" not in json.dumps(fields)
            for child in node.get("Plans", []):
                check(child, here)

        check(plan[0]["Plan"])
        assert len(producers) == 1
        assert producers[0]["Actual Rows"] == producers[0]["Actual Loops"] == 1
        assert len(semantic_producers) == 1
        assert semantic_producers[0]["Actual Rows"] == 3
        assert semantic_producers[0]["Actual Loops"] == 1

        def nodes(node):
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        dependencies = [node for node in nodes(producers[0])
                        if node.get("Node Type") == "CTE Scan" and node.get("CTE Name") == "semantic"]
        assert len(dependencies) == 1
        assert dependencies[0]["Actual Rows"] == 3
        assert dependencies[0]["Actual Loops"] == 1

# SHA-256 bbbc32db306a7dc8b6bd884e04b908f546f202fff32be3329d9a2277bba0394e.
_REFERENCE_SQL = """
                WITH semantic AS (
                    SELECT id, document_id, text, metadata,
                           row_number() OVER (ORDER BY embedding <=> CAST(:query_embedding AS vector), id) AS rank
                    FROM chunks
                    ORDER BY embedding <=> CAST(:query_embedding AS vector), id
                    LIMIT :top_k
                ),
                keyword AS (
                    SELECT id, document_id, text, metadata,
                           row_number() OVER (ORDER BY ts_rank(search_vector, plainto_tsquery('english', :query_text)) DESC, id) AS rank
                    FROM chunks
                    WHERE search_vector @@ plainto_tsquery('english', :query_text)
                    ORDER BY ts_rank(search_vector, plainto_tsquery('english', :query_text)) DESC, id
                    LIMIT :top_k
                ),
                fused AS (
                    SELECT
                        COALESCE(semantic.id, keyword.id) AS id,
                        COALESCE(semantic.document_id, keyword.document_id) AS document_id,
                        COALESCE(semantic.text, keyword.text) AS text,
                        COALESCE(semantic.metadata, keyword.metadata) AS metadata,
                        COALESCE(1.0 / (:rrf_k + semantic.rank), 0.0)
                            + COALESCE(1.0 / (:rrf_k + keyword.rank), 0.0) AS score
                    FROM semantic
                    FULL OUTER JOIN keyword ON semantic.id = keyword.id
                )
                SELECT id, document_id, text, metadata, score
                FROM fused
                ORDER BY score DESC, id
                LIMIT :top_k
                """
