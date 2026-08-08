"""Derives ORQ-26's frozen golden set from ORQ-22's ground truth.

Pure file transform: no database, no network, no embedding call. That is
deliberate — the artifact this writes is the pre-registered contract, so
producing it must not depend on anything that could differ between runs.

`experiments/reranking/` is read-only here. ORQ-22's published benchmark
evidence stays byte-identical (ORQ-26 AC2).

    python -m experiments.evaluation.build_golden_set
    python -m experiments.evaluation.build_golden_set --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_GROUND_TRUTH = Path("experiments/reranking/ground_truth.jsonl")
_GOLDEN_SET = Path("experiments/evaluation/golden_set.jsonl")
_CHECKSUM = Path("experiments/evaluation/golden_set.sha256")

_EXPECTED_ROWS = 60
_EXPECTED_PAIRS = 30
# ORQ-22 declared judgments before retrieval ran and admitted only these two
# grades; 0 is implicit for anything unjudged, never written (build_dataset.py:33-34).
_VALID_GRADES = {1, 2}
# ADR-006 §1 excludes these roots from ingestion, so a judgment naming one
# would be unreachable by construction.
_EXCLUDED_PREFIXES = ("docs/private/", ".framework/")


class GoldenSetError(ValueError):
    """The source ground truth violates an invariant the golden set relies on."""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def derive(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validates the ground truth and returns the golden-set rows.

    Every check here is a property the metrics or the pre-registration depend
    on. They are asserted rather than assumed because the source file lives in
    another ORQ's directory and this one must not edit it to fix a problem.
    """
    if len(rows) != _EXPECTED_ROWS:
        raise GoldenSetError(f"expected {_EXPECTED_ROWS} ground-truth rows, got {len(rows)}")
    if len({row["query_id"] for row in rows}) != _EXPECTED_ROWS:
        raise GoldenSetError("query_id values must be unique")

    derived: list[dict[str, Any]] = []
    for index in range(0, _EXPECTED_ROWS, 2):
        english, spanish = rows[index], rows[index + 1]
        pair_id = f"p{index // 2 + 1:02d}"
        if english["language"] != "en" or spanish["language"] != "es":
            raise GoldenSetError(f"{pair_id}: expected an en/es row pair")
        # The bilingual design is only meaningful if both halves are judged
        # identically; otherwise a per-language gap would measure the labels,
        # not the retriever.
        if english["judgments"] != spanish["judgments"]:
            raise GoldenSetError(f"{pair_id}: paired queries carry different judgments")
        if english["query"] == spanish["query"]:
            raise GoldenSetError(f"{pair_id}: paired queries are not distinct texts")

        for row in (english, spanish):
            for judgment in row["judgments"]:
                source_path = judgment["source_path"]
                if source_path.startswith(_EXCLUDED_PREFIXES):
                    raise GoldenSetError(f"{row['query_id']}: excluded source {source_path}")
                if judgment["relevance"] not in _VALID_GRADES:
                    raise GoldenSetError(
                        f"{row['query_id']}: grade {judgment['relevance']} outside {sorted(_VALID_GRADES)}"
                    )
            paths = [judgment["source_path"] for judgment in row["judgments"]]
            if len(paths) != len(set(paths)):
                raise GoldenSetError(f"{row['query_id']}: duplicate source_path in judgments")

            derived.append(
                {
                    "query_id": row["query_id"],
                    "pair_id": pair_id,
                    "language": row["language"],
                    "query": row["query"],
                    "relevant": [
                        {"source_path": judgment["source_path"], "grade": judgment["relevance"]}
                        for judgment in sorted(
                            row["judgments"], key=lambda item: item["source_path"]
                        )
                    ],
                }
            )
    return derived


def serialize(derived: list[dict[str, Any]]) -> str:
    # sort_keys and a trailing newline per row make the bytes a function of the
    # content alone, so the checksum is reproducible on any machine.
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in derived
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive ORQ-26's frozen golden set.")
    parser.add_argument("--ground-truth", type=Path, default=_GROUND_TRUTH)
    parser.add_argument("--output", type=Path, default=_GOLDEN_SET)
    parser.add_argument("--checksum", type=Path, default=_CHECKSUM)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed golden set matches this derivation; write nothing.",
    )
    args = parser.parse_args()

    payload = serialize(derive(_load_jsonl(args.ground_truth)))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    if args.check:
        committed = args.output.read_text(encoding="utf-8")
        if committed != payload:
            print(f"{args.output} does not match the derivation from {args.ground_truth}")
            return 1
        recorded = args.checksum.read_text(encoding="utf-8").split()[0]
        if recorded != digest:
            print(f"{args.checksum} records {recorded}, derivation is {digest}")
            return 1
        print(f"golden set matches derivation ({digest})")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    args.checksum.write_text(f"{digest}  {args.output.name}\n", encoding="utf-8")
    print(f"wrote {args.output} ({digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
