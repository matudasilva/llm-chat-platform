"""ORQ-26 round 4 of tranche 2: `_corpus_fingerprint` must refuse to declare a
single indexing_mode for a corpus that actually holds more than one.

Without this, `write_corpus_manifest` would pick whichever mode came back
first from an unordered `SELECT DISTINCT`, silently mislabelling a mixed
corpus as a clean "plain" or "contextualized" one.

Skipped unless RAG_TEST_DATABASE_URL and RAG_TEST_DATABASE_URL_APP are set.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.scripts.ingest_corpus import _corpus_fingerprint

pytestmark = pytest.mark.postgres

_TENANT = "tenant-manifest-mode"


def _privileged_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


def _app_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL_APP")
    if not url:
        pytest.skip("RAG_TEST_DATABASE_URL_APP not set")
    return url


async def _seed_document(source_path: str, indexing_mode: str) -> None:
    engine = create_async_engine(_privileged_url())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO documents (id, tenant_id, source_path, content_hash, doc_type, indexing_mode) "
                    "VALUES (:id, :tenant_id, :source_path, :hash, 'markdown', :indexing_mode)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": _TENANT,
                    "source_path": source_path,
                    "hash": str(uuid.uuid4()),
                    "indexing_mode": indexing_mode,
                },
            )
    finally:
        await engine.dispose()


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


@pytest.mark.asyncio
async def test_a_single_mode_corpus_reports_that_mode() -> None:
    await _seed_document("a.md", "plain")
    await _seed_document("b.md", "plain")
    try:
        _, _, _, indexing_mode = await _corpus_fingerprint(_TENANT, _app_url())
        assert indexing_mode == "plain"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_mixed_mode_corpus_is_refused() -> None:
    await _seed_document("a.md", "plain")
    await _seed_document("b.md", "contextualized")
    try:
        with pytest.raises(SystemExit, match="mixed indexing modes"):
            await _corpus_fingerprint(_TENANT, _app_url())
    finally:
        await _cleanup()
