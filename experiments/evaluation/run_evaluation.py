"""ORQ-26 evaluation runner: measures the candidate generator, records the run.

Imports nothing from generation or reranking. That is asserted by a test rather
than trusted (AC7): the whole value of this instrument is that it calls
`PgVectorStore.hybrid_search` and an embedding provider, and nothing else.

Three guards run before any measurement, and each fails the run outright:

  1. `registration.json` is committed and unmodified, with non-null thresholds
     and a signed approval. A threshold chosen after seeing the numbers
     registers nothing (ADR-009 decision 3).
  2. The corpus manifest exists, so `ingestion_commit` is a recorded fact rather
     than an assertion (ADR-009 decision 4).
  3. No golden-set query string occurs in the ingested corpus. Asserted against
     `chunks` under tenant scope, not against the filesystem: the vectors were
     written at an earlier commit, so a later rephrasing on disk would hide a
     leak the corpus still carries.

    python -m experiments.evaluation.run_evaluation
    python -m experiments.evaluation.run_evaluation --dry-run   # guards + metrics, no store write
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import text

from app.core.domain.retrieval_factory import build_embedding_provider
from app.core.providers.pgvector_store import PgVectorStore
from app.core.settings import settings
from app.http.middleware.tenant import tenant_scope
from app.infra.db.session import build_rag_sessionmaker
from experiments.evaluation import metrics as M
from experiments.evaluation.store import EvaluationStore, RunProvenance

_REGISTRATION = Path("experiments/evaluation/registration.json")
_GOLDEN_SET = Path("experiments/evaluation/golden_set.jsonl")
_MANIFEST = Path("experiments/evaluation/.corpus_manifest.json")

# ORQ-22's frozen candidate_recall_at_30 split over the same 60 queries, used as
# the drift reference. Reported, never asserted (AC8).
_ORQ22_CEILING = {1.0: 43, 0.5: 15, 0.0: 2}

_EXPERIMENT_NAME = "orq-26-candidate-generator-baseline"


class GuardFailure(RuntimeError):
    """A precondition failed; no measurement was taken."""


@dataclass(frozen=True)
class Registration:
    payload: dict[str, Any]
    sha256: str
    commit: str

    @property
    def thresholds(self) -> dict[str, float]:
        return self.payload["decision_rule"]["thresholds"]

    @property
    def k_values(self) -> list[int]:
        return self.payload["metrics"]["k_values"]

    @property
    def tenant_id(self) -> str:
        return self.payload["corpus"]["tenant_id"]

    @property
    def pinned_commit(self) -> str:
        return self.payload["corpus"]["pinned_commit"]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def load_registration(path: Path = _REGISTRATION) -> Registration:
    """Guard 1. Refuses anything that would let the rule be chosen after the fact."""
    if not path.exists():
        raise GuardFailure(f"{path} does not exist")

    if _git("status", "--porcelain", "--", str(path)):
        raise GuardFailure(
            f"{path} is modified or untracked in the worktree. Pre-registration means the "
            "contract predates the run; commit it first."
        )
    commit = _git("log", "-1", "--format=%H", "--", str(path))
    if not commit:
        raise GuardFailure(f"{path} has no commit history; it cannot predate a run")

    raw = path.read_bytes()
    payload = json.loads(raw)

    thresholds = payload["decision_rule"]["thresholds"]
    missing = [name for name, value in thresholds.items() if value is None]
    if missing:
        raise GuardFailure(
            f"decision thresholds are null: {', '.join(missing)}. A threshold chosen after "
            "seeing the numbers registers nothing."
        )
    if not payload.get("approved_by") or not payload.get("approved_at"):
        raise GuardFailure(
            "registration.json is unsigned (approved_by/approved_at). Unsigned, the "
            "pre-registration is decoration rather than precedence."
        )

    return Registration(
        payload=payload, sha256=hashlib.sha256(raw).hexdigest(), commit=commit
    )


def load_golden_set(registration: Registration, path: Path = _GOLDEN_SET) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    registered = registration.payload["golden_set"]["sha256"]
    if digest != registered:
        raise GuardFailure(
            f"golden set hash {digest} does not match the registered {registered}; "
            "the frozen set was modified after registration"
        )
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def load_manifest(path: Path = _MANIFEST) -> dict[str, Any]:
    """Guard 2. Without it there is nothing honest to put in `ingestion_commit`."""
    if not path.exists():
        raise GuardFailure(
            f"{path} does not exist. Run app.scripts.ingest_corpus, which writes it; "
            "the database records a per-document content_hash but no corpus revision, so "
            "without the manifest a run cannot say which commit it measured."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for field in ("commit", "ingested_at", "document_count", "chunk_count"):
        if field not in manifest:
            raise GuardFailure(f"{path} is missing '{field}'")
    return manifest


async def assert_no_query_leaked(session, queries: Sequence[str]) -> None:
    """Guard 3, asserted against the measured corpus rather than the filesystem."""
    result = await session.execute(
        text(
            "SELECT DISTINCT q.query FROM unnest(CAST(:queries AS text[])) AS q(query) "
            "JOIN chunks ON chunks.text ILIKE '%' || q.query || '%'"
        ),
        {"queries": list(queries)},
    )
    leaked = [row.query for row in result]
    if leaked:
        raise GuardFailure(
            f"{len(leaked)} golden-set quer{'y' if len(leaked) == 1 else 'ies'} occur verbatim in "
            f"the ingested corpus, which would flatter every metric: {leaked[:3]}"
        )


async def _source_paths(session, document_ids: Sequence[Any]) -> dict[str, str]:
    if not document_ids:
        return {}
    result = await session.execute(
        text("SELECT id, source_path FROM documents WHERE id = ANY(:ids)"),
        {"ids": list(document_ids)},
    )
    return {str(row.id): row.source_path for row in result}


async def measure(registration: Registration, golden_set: list[dict[str, Any]]) -> dict[str, Any]:
    """Runs the golden set and returns per-query, per-language and aggregate metrics."""
    embedding = build_embedding_provider(settings)
    vectors = (await embedding.embed_many([row["query"] for row in golden_set])).vectors

    sessionmaker = build_rag_sessionmaker(settings.database_url_app)
    k_values = registration.k_values
    per_query: list[dict[str, Any]] = []

    with tenant_scope(registration.tenant_id):
        async with sessionmaker() as session:
            await assert_no_query_leaked(session, [row["query"] for row in golden_set])

        for row, vector in zip(golden_set, vectors):
            relevant = M.relevant_paths(row["relevant"])
            entry: dict[str, Any] = {
                "query_id": row["query_id"],
                "language": row["language"],
                "pair_id": row["pair_id"],
            }
            ranked_at_k: dict[int, list[str]] = {}
            for k in k_values:
                # k=10, 20 and 30 are three separate retrievals, not one pool
                # truncated three times: LIMIT :top_k sits inside each CTE,
                # before the FULL OUTER JOIN that fuses them. Reusing a k=30
                # result to compute recall@10 would measure a different thing
                # and silently invalidate the registered decision rule.
                async with sessionmaker() as session:
                    chunks = await PgVectorStore(session).hybrid_search(
                        row["query"], vector, top_k=k
                    )
                    paths = await _source_paths(
                        session, [chunk.document_id for chunk in chunks]
                    )
                ranked = [paths[str(chunk.document_id)] for chunk in chunks]
                ranked_at_k[k] = ranked
                entry[f"recall@{k}"] = M.recall_at_k(ranked, relevant, k)

            entry["MAP@10"] = M.average_precision_at_k(ranked_at_k[10], relevant, 10)
            entry["MRR@10"] = M.reciprocal_rank_at_k(ranked_at_k[10], relevant, 10)
            per_query.append(entry)

    keys = [f"recall@{k}" for k in k_values] + ["MAP@10", "MRR@10"]
    aggregate = {key: M.mean([entry[key] for entry in per_query]) for key in keys}
    per_language = {
        language: {
            key: M.mean([e[key] for e in per_query if e["language"] == language])
            for key in keys
        }
        for language in sorted({entry["language"] for entry in per_query})
    }
    return {
        "per_query": per_query,
        "per_language": per_language,
        "aggregate": aggregate,
        "ceiling_drift": _ceiling_drift(per_query),
    }


def _ceiling_drift(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    """Reported as corpus-drift evidence, never asserted as a pass (AC8)."""
    observed: dict[float, int] = {1.0: 0, 0.5: 0, 0.0: 0}
    for entry in per_query:
        value = entry["recall@30"]
        observed[value] = observed.get(value, 0) + 1
    return {
        "orq22_recall_at_30_split": {str(k): v for k, v in _ORQ22_CEILING.items()},
        "observed_recall_at_30_split": {str(k): v for k, v in sorted(observed.items(), reverse=True)},
        "delta": {
            str(k): observed.get(k, 0) - _ORQ22_CEILING[k] for k in _ORQ22_CEILING
        },
        "note": "Reported as corpus-drift evidence. Not a pass/fail criterion.",
    }


def compute_verdict(registration: Registration, aggregate: dict[str, float]) -> dict[str, Any]:
    """Applies the registered rule. Never asserted in prose, never hardcoded."""
    thresholds = registration.thresholds
    floor = thresholds["recall_at_10_floor"]
    margin = thresholds["recall_gap_margin"]
    gap = aggregate["recall@20"] - aggregate["recall@10"]

    below_floor = aggregate["recall@10"] < floor
    gap_exceeded = gap > margin
    inadequate = below_floor or gap_exceeded

    reasons = []
    if below_floor:
        reasons.append(f"recall@10 {aggregate['recall@10']:.4f} < floor {floor}")
    if gap_exceeded:
        reasons.append(f"recall@20-recall@10 gap {gap:.4f} > margin {margin}")

    return {
        "verdict": "CANDIDATE_GENERATOR_INADEQUATE" if inadequate else "CANDIDATE_GENERATOR_ADEQUATE",
        "recall_at_10": aggregate["recall@10"],
        "recall_gap": gap,
        "recall_at_10_floor": floor,
        "recall_gap_margin": margin,
        "reasons": reasons,
        "scope_note": (
            "A verdict on hybrid_search under this frozen configuration and pinned corpus. "
            "Not a verdict on production retrieval, which also rewrites and reranks."
        ),
    }


async def main_async(*, dry_run: bool) -> int:
    registration = load_registration()
    golden_set = load_golden_set(registration)
    manifest = load_manifest()

    if manifest["commit"] != registration.pinned_commit:
        raise GuardFailure(
            f"corpus was ingested from {manifest['commit']}, but the registration pins "
            f"{registration.pinned_commit}"
        )

    results = await measure(registration, golden_set)
    verdict = compute_verdict(registration, results["aggregate"])

    report = {
        "experiment": _EXPERIMENT_NAME,
        "registration_sha256": registration.sha256,
        "registration_commit": registration.commit,
        "ingestion_commit": manifest["commit"],
        "code_commit": _git("rev-parse", "HEAD"),
        "corpus": {
            "document_count": manifest["document_count"],
            "chunk_count": manifest["chunk_count"],
        },
        "aggregate": results["aggregate"],
        "per_language": results["per_language"],
        "ceiling_drift": results["ceiling_drift"],
        "decision": verdict,
    }

    if not dry_run:
        report["run_id"] = str(await _record(registration, manifest, results, verdict))

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


async def _record(
    registration: Registration,
    manifest: dict[str, Any],
    results: dict[str, Any],
    verdict: dict[str, Any],
):
    if not settings.evaluation_store_url:
        raise GuardFailure("EVALUATION_STORE_URL is not set; the run has nowhere to be recorded")

    store = EvaluationStore(settings.evaluation_store_url)
    try:
        await store.ensure_schema()
        run_id = await store.create_run(
            experiment_name=_EXPERIMENT_NAME,
            provenance=RunProvenance(
                registration_sha256=registration.sha256,
                registration_commit=registration.commit,
                golden_set_sha256=registration.payload["golden_set"]["sha256"],
                ingestion_commit=manifest["commit"],
                code_commit=_git("rev-parse", "HEAD"),
            ),
            params={
                "k_values": ",".join(str(k) for k in registration.k_values),
                "tenant_id": registration.tenant_id,
                "pinned_commit": registration.pinned_commit,
                "document_count": str(manifest["document_count"]),
                "chunk_count": str(manifest["chunk_count"]),
                "recall_at_10_floor": str(verdict["recall_at_10_floor"]),
                "recall_gap_margin": str(verdict["recall_gap_margin"]),
            },
            tags={
                "verdict": verdict["verdict"],
                "run_class": registration.payload["corpus"]["run_class"],
            },
        )
        await store.log_metrics(run_id, results["aggregate"])
        for language, values in results["per_language"].items():
            await store.log_metrics(
                run_id, {f"{key}[{language}]": value for key, value in values.items()}
            )
        await store.finish_run(run_id, status="FINISHED")
        return run_id
    finally:
        await store.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ORQ-26 candidate-generator baseline.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the guards and compute metrics without writing to the store.",
    )
    args = parser.parse_args(argv)
    try:
        return asyncio.run(main_async(dry_run=args.dry_run))
    except GuardFailure as failure:
        print(f"guard failed: {failure}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
