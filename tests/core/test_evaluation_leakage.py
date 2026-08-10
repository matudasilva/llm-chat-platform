"""ORQ-26 AC3: no golden-set query text is present in the measured corpus.

Asserted against `chunks` under tenant scope rather than against the
filesystem. The vectors were written at an earlier commit, so a later
rephrasing on disk would hide a leak the corpus still carries — the filesystem
and the corpus can disagree, and only one of them is what gets measured.

The contaminated case is the point of this module. An assertion that has only
ever been observed passing is not evidence that it can fail.

Skipped unless RAG_TEST_DATABASE_URL and RAG_TEST_DATABASE_URL_APP are set.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.utils.corpus_fingerprint import content_fingerprint
from app.http.middleware.tenant import tenant_scope
from app.infra.db.session import build_rag_sessionmaker
from experiments.evaluation.run_evaluation import (
    CorpusStateError,
    GuardFailure,
    assert_corpus_matches_manifest,
    assert_no_query_leaked,
)

pytestmark = pytest.mark.postgres

_TENANT = "tenant-leakage"
_DUMMY_EMBEDDING = [0.001] * 1536
_GOLDEN_SET = Path("experiments/evaluation/golden_set.jsonl")


def _privileged_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


def _app_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL_APP")
    if not url:
        pytest.skip("RAG_TEST_DATABASE_URL_APP not set")
    return url


def _queries() -> list[str]:
    return [
        json.loads(line)["query"]
        for line in _GOLDEN_SET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


_SOURCE_PATH = "leak-probe.md"


async def _seed(chunk_text: str, *, content_hash: str | None = None) -> str:
    """Seeds one document/chunk pair and returns the content_hash used, so
    callers can compute the fingerprint a guard is expected to match."""
    engine = create_async_engine(_privileged_url())
    document_id = uuid.uuid4()
    content_hash = content_hash or str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO documents (id, tenant_id, source_path, content_hash, doc_type) "
                    "VALUES (:id, :tenant_id, :source_path, :hash, 'markdown')"
                ),
                {
                    "id": document_id,
                    "tenant_id": _TENANT,
                    "source_path": _SOURCE_PATH,
                    "hash": content_hash,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO chunks (id, document_id, tenant_id, ordinal, text, embedding, search_vector) "
                    "VALUES (:id, :doc_id, :tenant_id, 0, :text, CAST(:embedding AS vector), "
                    "to_tsvector('english', :text))"
                ),
                {
                    "id": uuid.uuid4(),
                    "doc_id": document_id,
                    "tenant_id": _TENANT,
                    "text": chunk_text,
                    "embedding": "[" + ",".join(str(v) for v in _DUMMY_EMBEDDING) + "]",
                },
            )
    finally:
        await engine.dispose()
    return content_hash


async def _cleanup() -> None:
    engine = create_async_engine(_privileged_url())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM documents WHERE tenant_id = :tenant_id"),
                {"tenant_id": _TENANT},
            )
    finally:
        await engine.dispose()


async def _assert_against_seeded_corpus() -> None:
    sessionmaker = build_rag_sessionmaker(_app_url())
    with tenant_scope(_TENANT):
        async with sessionmaker() as session:
            await assert_no_query_leaked(session, _queries())


@pytest.mark.asyncio
async def test_a_clean_corpus_passes() -> None:
    await _seed("This chunk discusses retrieval fusion without quoting any evaluation query.")
    try:
        await _assert_against_seeded_corpus()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_leaked_query_fails_the_assertion() -> None:
    leaked = _queries()[0]
    await _seed(f"Some preamble. {leaked} Some trailing prose.")
    try:
        with pytest.raises(GuardFailure, match="occur verbatim in the ingested corpus"):
            await _assert_against_seeded_corpus()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_leak_is_caught_regardless_of_case() -> None:
    # A corpus that lower-cases or title-cases a query still carries the lexical
    # advantage, so the assertion must not be defeated by capitalisation.
    leaked = _queries()[0]
    await _seed(f"Preamble. {leaked.upper()} Trailing.")
    try:
        with pytest.raises(GuardFailure, match="occur verbatim in the ingested corpus"):
            await _assert_against_seeded_corpus()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_measured_corpus_itself_is_clean() -> None:
    # The real assertion, against the tenant the harness actually measures.
    sessionmaker = build_rag_sessionmaker(_app_url())
    with tenant_scope("acme"):
        async with sessionmaker() as session:
            total = (await session.execute(text("SELECT count(*) FROM chunks"))).scalar_one()
            if total == 0:
                pytest.skip("the acme corpus is not ingested in this environment")
            await assert_no_query_leaked(session, _queries())


@pytest.mark.asyncio
async def test_a_corpus_that_does_not_match_the_manifest_is_refused() -> None:
    """The guard that would have caught a wiped corpus.

    `tests/core/test_rag_migration.py` downgrades the schema, emptying
    `documents` and `chunks`. Without this check the next run measured an empty
    corpus and reported 0.0 across the board as though it were a finding —
    which is exactly what happened before the guard existed.
    """
    await _seed("A single chunk, so the tenant holds 1 document and 1 chunk.")
    try:
        sessionmaker = build_rag_sessionmaker(_app_url())
        with tenant_scope(_TENANT):
            async with sessionmaker() as session:
                with pytest.raises(CorpusStateError, match="corpus mismatch"):
                    await assert_corpus_matches_manifest(
                        session,
                        {"commit": "x", "document_count": 999, "chunk_count": 999},
                    )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_matching_corpus_passes_the_guard() -> None:
    content_hash = await _seed("A single chunk, so the tenant holds 1 document and 1 chunk.")
    try:
        sessionmaker = build_rag_sessionmaker(_app_url())
        with tenant_scope(_TENANT):
            async with sessionmaker() as session:
                await assert_corpus_matches_manifest(
                    session,
                    {
                        "commit": "x",
                        "document_count": 1,
                        "chunk_count": 1,
                        "content_fingerprint": content_fingerprint([(_SOURCE_PATH, content_hash)]),
                    },
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_content_mismatch_is_refused_despite_matching_counts() -> None:
    """The guard round 3 found missing: counts alone let a replaced or mutated
    corpus with the same document/chunk totals pass silently."""
    await _seed("A single chunk, so the tenant holds 1 document and 1 chunk.")
    try:
        sessionmaker = build_rag_sessionmaker(_app_url())
        with tenant_scope(_TENANT):
            async with sessionmaker() as session:
                with pytest.raises(CorpusStateError, match="content mismatch"):
                    await assert_corpus_matches_manifest(
                        session,
                        {
                            "commit": "x",
                            "document_count": 1,
                            "chunk_count": 1,
                            "content_fingerprint": "0" * 64,
                        },
                    )
    finally:
        await _cleanup()
