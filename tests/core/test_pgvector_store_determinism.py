"""ORQ-26 Task 0 / AC7: hybrid_search is deterministic for an unchanged corpus.

Repeating a call and getting the same answer is not evidence — it passes on the
unfixed query whenever the plan happens to be stable. So this module seeds a
corpus that *forces* the two tie shapes the fix exists for, and asserts the
exact order the `id` tiebreaker must produce:

  1. ties inside a CTE's `ORDER BY ... LIMIT`, which decide *membership* of the
     candidate pool, not merely its internal order;
  2. exact ties on the fused RRF score, which arise by construction whenever a
     chunk is found by only one leg — 1.0/(60+r) from the semantic leg equals
     1.0/(60+r) from the keyword leg at the same rank.

Skipped unless RAG_TEST_DATABASE_URL (privileged, for seeding) and
RAG_TEST_DATABASE_URL_APP (the rag_app role) are both set — see pytest.ini's
`postgres` marker and tests/conftest.py's skip predicate.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.providers.pgvector_store import _RRF_K, PgVectorStore
from app.http.middleware.tenant import tenant_scope
from app.infra.db.session import build_rag_sessionmaker

pytestmark = pytest.mark.postgres

_TENANT = "tenant-determinism"

# The query embedding, and the embedding of every semantic-leg chunk: cosine
# distance 0, so the whole group ties and only `id` can order it.
_NEAR = [1.0] + [0.0] * 1535
# Orthogonal to _NEAR — cosine distance 1 — so these chunks lose the semantic
# race and reach the fused set through the keyword leg alone. Note that cosine
# distance ignores magnitude: a uniformly scaled copy of _NEAR would sit at
# distance 0, not "far", and every chunk would tie on the semantic leg.
_FAR = [0.0] * 1535 + [1.0]

_QUERY_TEXT = "alpha"
# Matches _QUERY_TEXT; identical across the group, so ts_rank ties too.
_KEYWORD_TEXT = "alpha alpha alpha"
# Shares no lexeme with _QUERY_TEXT, so these are excluded from the keyword CTE.
_SEMANTIC_TEXT = "zeta zeta zeta"

_GROUP_SIZE = 3


def _privileged_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


def _app_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL_APP")
    if not url:
        pytest.skip("RAG_TEST_DATABASE_URL_APP not set")
    return url


def _vector(embedding: list[float]) -> str:
    return "[" + ",".join(str(v) for v in embedding) + "]"


@pytest.fixture
async def tied_corpus():
    """Seeds two groups that tie internally on every ordering key.

    Seeded as the privileged role because RLS does not apply to it; the search
    below still runs as rag_app under tenant_scope, so the assertions only ever
    see this tenant's rows.
    """
    engine = create_async_engine(_privileged_url())
    semantic_doc, keyword_doc = uuid.uuid4(), uuid.uuid4()
    semantic_ids = [uuid.uuid4() for _ in range(_GROUP_SIZE)]
    keyword_ids = [uuid.uuid4() for _ in range(_GROUP_SIZE)]
    try:
        async with engine.begin() as conn:
            for doc_id, path in [(semantic_doc, "det-semantic.md"), (keyword_doc, "det-keyword.md")]:
                await conn.execute(
                    text(
                        "INSERT INTO documents (id, tenant_id, source_path, content_hash, doc_type) "
                        "VALUES (:id, :tenant_id, :path, :hash, 'markdown')"
                    ),
                    {
                        "id": doc_id,
                        "tenant_id": _TENANT,
                        "path": path,
                        "hash": f"hash-{path}",
                    },
                )
            groups = [
                (semantic_ids, semantic_doc, _SEMANTIC_TEXT, _NEAR),
                (keyword_ids, keyword_doc, _KEYWORD_TEXT, _FAR),
            ]
            for chunk_ids, doc_id, body, embedding in groups:
                for ordinal, chunk_id in enumerate(chunk_ids):
                    await conn.execute(
                        text(
                            "INSERT INTO chunks "
                            "(id, document_id, tenant_id, ordinal, text, embedding, search_vector) "
                            "VALUES (:id, :doc_id, :tenant_id, :ordinal, :text, "
                            "CAST(:embedding AS vector), to_tsvector('english', :text))"
                        ),
                        {
                            "id": chunk_id,
                            "doc_id": doc_id,
                            "tenant_id": _TENANT,
                            "ordinal": ordinal,
                            "text": body,
                            "embedding": _vector(embedding),
                        },
                    )
        yield {"semantic_ids": semantic_ids, "keyword_ids": keyword_ids}
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM documents WHERE tenant_id = :tenant_id"),
                {"tenant_id": _TENANT},
            )
        await engine.dispose()


async def _retrieve(top_k: int):
    sessionmaker = build_rag_sessionmaker(_app_url())
    with tenant_scope(_TENANT):
        async with sessionmaker() as session:
            return await PgVectorStore(session).hybrid_search(
                _QUERY_TEXT, _NEAR, top_k=top_k
            )


async def _search(top_k: int) -> list[uuid.UUID]:
    return [chunk.chunk_id for chunk in await _retrieve(top_k)]


def _expected_order(tied_corpus: dict[str, list[uuid.UUID]], top_k: int) -> list[uuid.UUID]:
    """Recomputes the contract independently of the SQL that implements it.

    With top_k == _GROUP_SIZE the semantic CTE holds exactly the near group and
    the keyword CTE exactly the keyword group, each ranked 1..n by `id` because
    every other ordering key ties. So each group's i-th member scores
    1/(_RRF_K + i + 1) from its single leg, and pairs across groups tie exactly.
    """
    scored: list[tuple[float, uuid.UUID]] = []
    for group in (tied_corpus["semantic_ids"], tied_corpus["keyword_ids"]):
        for index, chunk_id in enumerate(sorted(group)):
            scored.append((1.0 / (_RRF_K + index + 1), chunk_id))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [chunk_id for _, chunk_id in scored[:top_k]]


@pytest.mark.asyncio
async def test_fused_ties_are_broken_by_id(tied_corpus) -> None:
    # Every returned pair of adjacent rows either differs in score or is
    # ordered by id; asserting the whole sequence pins both at once.
    assert await _search(_GROUP_SIZE) == _expected_order(tied_corpus, _GROUP_SIZE)


@pytest.mark.asyncio
async def test_cte_membership_is_stable_under_ties(tied_corpus) -> None:
    # top_k below the group size makes each CTE's `ORDER BY ... LIMIT` choose a
    # strict subset of a fully tied group. Which rows it admits is exactly what
    # the tiebreaker on the CTE-level ORDER BY decides.
    truncated = _GROUP_SIZE - 1
    returned = await _search(truncated)
    admitted_semantic = set(sorted(tied_corpus["semantic_ids"])[:truncated])
    admitted_keyword = set(sorted(tied_corpus["keyword_ids"])[:truncated])
    assert set(returned) <= admitted_semantic | admitted_keyword
    assert len(returned) == truncated


@pytest.fixture
async def uniform_corpus():
    """Seeds one group in which *every* ordering key ties, for all chunks.

    Same embedding as the query (cosine distance 0) and the same text, which
    also matches the query, so both legs see an identically-tied population and
    admit the same subset. The fused set is then exactly `top_k` rows, which is
    what makes CTE membership observable as an equality rather than as a
    subset.
    """
    engine = create_async_engine(_privileged_url())
    document_id = uuid.uuid4()
    chunk_ids = [uuid.uuid4() for _ in range(5)]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO documents (id, tenant_id, source_path, content_hash, doc_type) "
                    "VALUES (:id, :tenant_id, 'det-uniform.md', 'hash-uniform', 'markdown')"
                ),
                {"id": document_id, "tenant_id": _TENANT},
            )
            for ordinal, chunk_id in enumerate(chunk_ids):
                await conn.execute(
                    text(
                        "INSERT INTO chunks "
                        "(id, document_id, tenant_id, ordinal, text, embedding, search_vector) "
                        "VALUES (:id, :doc_id, :tenant_id, :ordinal, :text, "
                        "CAST(:embedding AS vector), to_tsvector('english', :text))"
                    ),
                    {
                        "id": chunk_id,
                        "doc_id": document_id,
                        "tenant_id": _TENANT,
                        "ordinal": ordinal,
                        "text": _KEYWORD_TEXT,
                        "embedding": _vector(_NEAR),
                    },
                )
        yield chunk_ids
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM documents WHERE tenant_id = :tenant_id"),
                {"tenant_id": _TENANT},
            )
        await engine.dispose()


@pytest.fixture
async def semantic_only_corpus():
    """A tied population that the keyword leg cannot see at all.

    Every chunk sits at cosine distance 0 from the query and shares no lexeme
    with it, so `search_vector @@ plainto_tsquery(...)` excludes all of them and
    the keyword CTE is empty. The fused set is then *exactly* the semantic CTE,
    which is what lets its `ORDER BY ... LIMIT` be asserted directly rather than
    inferred.
    """
    engine = create_async_engine(_privileged_url())
    document_id = uuid.uuid4()
    chunk_ids = [uuid.uuid4() for _ in range(5)]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO documents (id, tenant_id, source_path, content_hash, doc_type) "
                    "VALUES (:id, :tenant_id, 'det-semantic-only.md', 'hash-semonly', 'markdown')"
                ),
                {"id": document_id, "tenant_id": _TENANT},
            )
            for ordinal, chunk_id in enumerate(chunk_ids):
                await conn.execute(
                    text(
                        "INSERT INTO chunks "
                        "(id, document_id, tenant_id, ordinal, text, embedding, search_vector) "
                        "VALUES (:id, :doc_id, :tenant_id, :ordinal, :text, "
                        "CAST(:embedding AS vector), to_tsvector('english', :text))"
                    ),
                    {
                        "id": chunk_id,
                        "doc_id": document_id,
                        "tenant_id": _TENANT,
                        "ordinal": ordinal,
                        "text": _SEMANTIC_TEXT,
                        "embedding": _vector(_NEAR),
                    },
                )
        yield chunk_ids
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM documents WHERE tenant_id = :tenant_id"),
                {"tenant_id": _TENANT},
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_semantic_cte_membership_is_exactly_the_id_ordered_subset(
    semantic_only_corpus,
) -> None:
    # Direct test of the semantic CTE's `ORDER BY ... LIMIT`: with the keyword
    # leg empty, the returned rows ARE that CTE's membership, so equality here
    # is a statement about the clause and not an inference from a fused result.
    top_k = 3
    returned = await _search(top_k)
    assert returned == sorted(semantic_only_corpus)[:top_k]


@pytest.mark.asyncio
async def test_uniform_ties_pin_both_legs_through_the_fused_scores(uniform_corpus) -> None:
    # The keyword CTE cannot be isolated the way the semantic one can: the
    # semantic leg has no WHERE clause, so it always contributes rows and no
    # corpus makes the fused output equal the keyword membership alone.
    #
    # The scores pin it instead. In a fully tied population each returned chunk
    # must score 1/(60+r) from BOTH legs at the same r. If the keyword CTE had
    # admitted a different subset, or ordered its members differently, some
    # returned chunk would carry a single-leg score of 1/(60+r) rather than the
    # doubled one, and this assertion would fail.
    top_k = 3
    chunks = await _retrieve(top_k)
    expected = [
        (chunk_id, 2 * (1.0 / (_RRF_K + rank)))
        for rank, chunk_id in enumerate(sorted(uniform_corpus)[:top_k], start=1)
    ]
    assert [(chunk.chunk_id, pytest.approx(float(chunk.score))) for chunk in chunks] == expected


@pytest.mark.asyncio
async def test_repeated_searches_agree(tied_corpus) -> None:
    # The weak property, kept because it is the one AC7 states literally. It
    # only means something alongside the two assertions above.
    first = await _search(_GROUP_SIZE)
    second = await _search(_GROUP_SIZE)
    assert first == second
