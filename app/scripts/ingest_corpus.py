"""Offline RAG corpus ingestion (ORQ-21 / ADR-006). Never an HTTP endpoint —
invariant 1 (`/chat` is the only write-path) stays intact (spec.md §Design
decisions 8, AC7).

Usage:
    python -m app.scripts.ingest_corpus --tenant-id acme
    python -m app.scripts.ingest_corpus --tenant-id acme --contextualize

Connects via DATABASE_URL_APP (the unprivileged rag_app role), never
get_tenant_id() — outside an HTTP request that silently returns "default",
which would write the whole corpus into the wrong tenant without erroring.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from app.core.domain.embedding import EmbeddingPort
from app.core.domain.provider import ProviderInput, ProviderPort
from app.core.domain.provider_factory import build_provider
from app.core.domain.types import ChatMessage
from app.core.domain.vector_store import ChunkUpsert
from app.core.providers.openai_embedding_provider import OpenAIEmbeddingConfig, OpenAIEmbeddingProvider
from app.core.providers.pgvector_store import PgVectorStore
from app.core.settings import settings
from app.http.middleware.tenant import tenant_scope
from app.infra.db.session import build_rag_sessionmaker
from app.services.rag_chunking import RawChunk, chunk_document

logger = logging.getLogger(__name__)

_CONTEXTUALIZE_PROMPT = (
    "You situate a text fragment within its source document in 1-2 short sentences. "
    "State only what section/function it belongs to and what the surrounding document is about. "
    "Do not repeat the fragment itself. Do not add commentary."
)

_MARKDOWN_ROOTS = ["docs"]
_PYTHON_ROOT = "app"
_EXCLUDED_DIR_NAMES = {"__pycache__", "alembic"}


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    source_path: str
    doc_type: str
    content: str
    content_hash: str


def _is_git_ignored(repo_root: Path, path: Path) -> bool:
    # spec.md §Risks: "Loader excludes .env, .framework/, and anything
    # gitignored" -- docs/private/ is exactly this case (gitignored project
    # analysis, not corpus-worthy or safe to embed into a shared index).
    # Fails closed: if git is unavailable, treat the path as ignored rather
    # than silently ingesting it.
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=repo_root,
            capture_output=True,
        )
    except FileNotFoundError:
        return True
    return result.returncode == 0


def discover_documents(repo_root: Path) -> list[LoadedDocument]:
    docs: list[LoadedDocument] = []

    for root_name in _MARKDOWN_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            if _is_git_ignored(repo_root, path):
                continue
            docs.append(_load(repo_root, path, "markdown"))

    python_root = repo_root / _PYTHON_ROOT
    if python_root.exists():
        for path in sorted(python_root.rglob("*.py")):
            if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            if _is_git_ignored(repo_root, path):
                continue
            docs.append(_load(repo_root, path, "python"))

    return docs


def _load(repo_root: Path, path: Path, doc_type: str) -> LoadedDocument:
    content = path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return LoadedDocument(
        source_path=str(path.relative_to(repo_root)),
        doc_type=doc_type,
        content=content,
        content_hash=content_hash,
    )


async def _contextualize(provider: ProviderPort, document: LoadedDocument, chunk: RawChunk) -> str:
    prompt = (
        f"Document: {document.source_path}\n"
        f"Section/function: {chunk.section or '(top level)'}\n\n"
        f"Fragment:\n{chunk.text}"
    )
    result = await provider.generate(
        ProviderInput(
            request_id=uuid4(),
            messages=[
                ChatMessage(role="system", content=_CONTEXTUALIZE_PROMPT),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.0,
            max_tokens=80,
        )
    )
    return result.content.strip()


def fingerprint(content_hash: str, indexing_mode: str) -> str:
    return f"{content_hash}:{indexing_mode}"


def should_reindex(existing_fingerprint: str | None, new_fingerprint: str) -> bool:
    """
    ADR-006 §6: a document is re-indexed if either its content changed or its
    indexing mode changed -- content_hash alone is not enough, or a corpus
    built in mixed modes could compare against itself silently.
    """
    return existing_fingerprint != new_fingerprint


def build_search_texts(raw_chunks: list[RawChunk], contexts: list[str | None]) -> list[str]:
    """
    The embedding/tsvector input: context + text when contextualized, text
    alone otherwise. The original chunk text is never mutated by this --
    callers store `text` and `search_text` separately (ChunkUpsert).
    """
    return [
        f"{ctx}\n{rc.text}" if ctx else rc.text
        for ctx, rc in zip(contexts, raw_chunks)
    ]


async def _existing_indexing_mode(session, tenant_id: str, source_path: str) -> tuple[str, str] | None:
    """Returns (document_id, content_hash+':'+indexing_mode) for the current row, if any."""
    result = await session.execute(
        text(
            "SELECT id, content_hash, indexing_mode FROM documents "
            "WHERE tenant_id = :tenant_id AND source_path = :source_path"
        ),
        {"tenant_id": tenant_id, "source_path": source_path},
    )
    row = result.first()
    if row is None:
        return None
    return (str(row.id), f"{row.content_hash}:{row.indexing_mode}")


async def ingest(
    *,
    tenant_id: str,
    repo_root: Path,
    contextualize: bool,
    embedding: EmbeddingPort,
    database_url_app: str,
) -> dict[str, int]:
    documents = discover_documents(repo_root)
    indexing_mode = "contextualized" if contextualize else "plain"
    stats = {"documents_seen": len(documents), "documents_ingested": 0, "documents_skipped": 0, "chunks_ingested": 0}

    context_provider: ProviderPort | None = build_provider() if contextualize else None
    sessionmaker = build_rag_sessionmaker(database_url_app)

    with tenant_scope(tenant_id):
        for document in documents:
            async with sessionmaker() as session:
                async with session.begin():
                    existing = await _existing_indexing_mode(session, tenant_id, document.source_path)
                    new_fingerprint = fingerprint(document.content_hash, indexing_mode)
                    if existing is not None and not should_reindex(existing[1], new_fingerprint):
                        stats["documents_skipped"] += 1
                        continue

                    if existing is not None:
                        await session.execute(
                            text("DELETE FROM documents WHERE id = :id"), {"id": existing[0]}
                        )

                    document_id = uuid4()
                    await session.execute(
                        text(
                            "INSERT INTO documents "
                            "(id, tenant_id, source_path, content_hash, doc_type, indexing_mode) "
                            "VALUES (:id, :tenant_id, :source_path, :content_hash, :doc_type, :indexing_mode)"
                        ),
                        {
                            "id": document_id,
                            "tenant_id": tenant_id,
                            "source_path": document.source_path,
                            "content_hash": document.content_hash,
                            "doc_type": document.doc_type,
                            "indexing_mode": indexing_mode,
                        },
                    )

                    raw_chunks = chunk_document(document.doc_type, document.content)
                    if not raw_chunks:
                        stats["documents_ingested"] += 1
                        continue

                    contexts: list[str | None] = [None] * len(raw_chunks)
                    if contextualize:
                        assert context_provider is not None
                        for i, raw_chunk in enumerate(raw_chunks):
                            contexts[i] = await _contextualize(context_provider, document, raw_chunk)

                    search_texts = build_search_texts(raw_chunks, contexts)
                    embed_result = await embedding.embed_many(search_texts)

                    store = PgVectorStore(session)
                    await store.upsert_chunks(
                        [
                            ChunkUpsert(
                                document_id=document_id,
                                tenant_id=tenant_id,
                                ordinal=i,
                                text=rc.text,
                                context=contexts[i],
                                embedding=embed_result.vectors[i],
                                search_text=search_texts[i],
                                metadata={"section": rc.section} if rc.section else None,
                            )
                            for i, rc in enumerate(raw_chunks)
                        ]
                    )
                    stats["chunks_ingested"] += len(raw_chunks)
                    stats["documents_ingested"] += 1

    return stats


def _build_embedding_provider() -> EmbeddingPort:
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required for RAG ingestion (ADR-006 §1).")
    return OpenAIEmbeddingProvider(
        OpenAIEmbeddingConfig(
            api_key=settings.openai_api_key,
            dimensions=settings.rag_embedding_dimensions,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, help="Tenant to ingest the corpus into. Required — no default.")
    parser.add_argument("--contextualize", action="store_true", help="Prepend an LLM-generated situating context before embedding (off by default, ADR-006 §6).")
    parser.add_argument("--repo-root", default=".", help="Repository root to scan (default: current directory).")
    args = parser.parse_args(argv)

    if not settings.database_url_app:
        raise SystemExit("DATABASE_URL_APP is required for RAG ingestion (spec.md §Design decisions 4/8).")

    logging.basicConfig(level=logging.INFO)
    embedding = _build_embedding_provider()

    stats = asyncio.run(
        ingest(
            tenant_id=args.tenant_id,
            repo_root=Path(args.repo_root).resolve(),
            contextualize=args.contextualize,
            embedding=embedding,
            database_url_app=settings.database_url_app,
        )
    )
    logger.info("ingest.summary", extra={"event": "ingest.summary", **stats})
    print(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
