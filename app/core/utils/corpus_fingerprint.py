"""A deterministic digest over a corpus's (source_path, content_hash) pairs.

Pure and dependency-free on purpose. Two callers need it without acquiring
each other's dependencies: `app.scripts.ingest_corpus` (the writer, which
transitively imports the generation provider factory for `--contextualize`)
and `experiments/evaluation/run_evaluation.py` (a reader, guard 3 — AC7
requires the runner import nothing from generation or reranking, even
transitively). Living under `app.core.utils` keeps it on the app side of the
boundary the harness README declares: this directory is not imported by the
application, it only imports from it.
"""

from __future__ import annotations

import hashlib


def content_fingerprint(rows: list[tuple[str, str]]) -> str:
    """Hashes the sorted set of (source_path, content_hash) pairs.

    Counts alone (document_count, chunk_count) let a corpus with the right
    totals but different text pass a guard silently (round 2 and round 3 of
    ORQ-26 tranche 2 both flagged this). Sorted so row order — which the
    database does not guarantee — cannot change the digest.
    """
    lines = "\n".join(f"{path}:{content_hash}" for path, content_hash in sorted(rows))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()
