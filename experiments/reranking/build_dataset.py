from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.providers.openai_embedding_provider import OpenAIEmbeddingConfig, OpenAIEmbeddingProvider
from app.core.providers.pgvector_store import PgVectorStore
from app.core.settings import settings
from app.http.middleware.tenant import tenant_scope
from app.infra.db.session import build_rag_sessionmaker


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def build(*, ground_truth_path: Path, output_path: Path, tenant_id: str) -> None:
    rows = _load_jsonl(ground_truth_path)
    if len(rows) != 60:
        raise ValueError(f"ground truth must contain exactly 60 queries, got {len(rows)}")
    if len({row["query_id"] for row in rows}) != 60:
        raise ValueError("query_id values must be unique")
    for row in rows:
        for judgment in row["judgments"]:
            path = judgment["source_path"]
            if path.startswith("docs/private/") or path.startswith(".framework/"):
                raise ValueError(f"excluded source in ground truth: {path}")
            if judgment["relevance"] not in {1, 2}:
                raise ValueError("ground-truth relevance must be 1 or 2")

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    if not settings.database_url_app:
        raise RuntimeError("DATABASE_URL_APP is required")
    embedding = OpenAIEmbeddingProvider(
        OpenAIEmbeddingConfig(
            api_key=settings.openai_api_key,
            dimensions=settings.rag_embedding_dimensions,
        )
    )
    vectors = await embedding.embed_many([row["query"] for row in rows])
    sessionmaker = build_rag_sessionmaker(settings.database_url_app)
    output_rows: list[dict[str, Any]] = []

    with tenant_scope(tenant_id):
        for row, vector in zip(rows, vectors.vectors):
            async with sessionmaker() as session:
                candidates = await PgVectorStore(session).hybrid_search(
                    row["query"],
                    vector,
                    top_k=30,
                )
                document_ids = [candidate.document_id for candidate in candidates]
                source_result = await session.execute(
                    text("SELECT id, source_path FROM documents WHERE id = ANY(:document_ids)"),
                    {"document_ids": document_ids},
                )
                source_paths = {str(item.id): item.source_path for item in source_result}

            relevance_by_path = {
                judgment["source_path"]: judgment["relevance"]
                for judgment in row["judgments"]
            }
            serialized_candidates = [
                {
                    "candidate_id": str(candidate.chunk_id),
                    "document_id": str(candidate.document_id),
                    "source_path": source_paths[str(candidate.document_id)],
                    "text": candidate.text,
                    "baseline_rank": rank,
                    "rrf_score": float(candidate.score),
                    "relevance": relevance_by_path.get(source_paths[str(candidate.document_id)], 0),
                }
                for rank, candidate in enumerate(candidates, start=1)
            ]
            if len(serialized_candidates) != 30:
                raise RuntimeError(
                    f"{row['query_id']} returned {len(serialized_candidates)} candidates; expected 30"
                )
            expected_paths = set(relevance_by_path)
            found_paths = {candidate["source_path"] for candidate in serialized_candidates}
            output_rows.append(
                {
                    **row,
                    "candidate_recall_at_30": len(expected_paths & found_paths) / len(expected_paths),
                    "candidates": serialized_candidates,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in output_rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the frozen ORQ-22 reranking dataset.")
    parser.add_argument("--ground-truth", type=Path, default=Path("experiments/reranking/ground_truth.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("experiments/reranking/dataset.jsonl"))
    parser.add_argument("--tenant-id", default="acme")
    args = parser.parse_args()
    asyncio.run(build(ground_truth_path=args.ground_truth, output_path=args.output, tenant_id=args.tenant_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
