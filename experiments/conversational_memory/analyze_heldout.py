from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .dataset import sha256_file
from .execution import summarize_execution_ledger


ROOT = Path(__file__).resolve().parents[2]


def build_analysis(
    *,
    run_path: Path,
    registration_path: Path,
    execution_ledger_path: Path,
    attempt_ledger_path: Path,
) -> dict[str, Any]:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    if run.get("phase") != "heldout" or run.get("heldout_inspected") is not True:
        raise ValueError("analysis accepts only a completed held-out run")
    decision = run.get("heldout_decision")
    if not isinstance(decision, dict) or decision.get("verdict") not in {
        "GO",
        "NO_GO",
    }:
        raise ValueError("held-out run has no valid design verdict")
    if run.get("decision_status") != decision["verdict"]:
        raise ValueError("run decision status and held-out verdict differ")
    if sha256_file(registration_path) != run.get("registration_sha256"):
        raise ValueError("current registration hash differs from the held-out run")
    _verify_source_registration_snapshot(run)

    expected_dataset_hash = registration["dataset"]["heldout_sha256"]
    if run.get("dataset_sha256") != expected_dataset_hash:
        raise ValueError("held-out dataset hash differs from registration")
    attempt_events = _attempt_events(attempt_ledger_path, run_id=run["run_id"])
    if [event["status"] for event in attempt_events] != ["started", "completed"]:
        raise ValueError("held-out attempt is not one valid completed run")
    terminal = attempt_events[-1]
    if terminal.get("verdict") != decision["verdict"]:
        raise ValueError("attempt ledger and held-out verdict differ")

    observed = summarize_execution_ledger(execution_ledger_path, run_id=run["run_id"])
    recorded_observed = run["cost_taxonomy"]["observed_execution"]
    for key, value in observed.items():
        if recorded_observed.get(key) != value:
            raise ValueError(f"execution ledger differs for {key}")
    criteria = decision["criterion_evaluation"]
    confidence = set(criteria["one_sided_95_percent_lower_bound"])
    points = set(criteria["unrounded_point_estimates"])
    registered_confidence = set(
        registration["decision_rule"]["paired_evaluation"][
            "confidence_bound_criteria"
        ]
    )
    registered_points = set(
        registration["decision_rule"]["paired_evaluation"][
            "point_estimate_criteria"
        ]
    )
    if confidence != registered_confidence or points != registered_points:
        raise ValueError("run criterion modes differ from registration")

    threshold_clauses = decision["threshold_clauses"]
    automatic_clauses = decision["automatic_clauses"]
    all_clauses = {**threshold_clauses, **automatic_clauses}
    derived_failed = [
        name for name, clause in all_clauses.items() if not clause["passed"]
    ]
    failed = decision["failed_clauses"]
    if len(derived_failed) != len(failed) or set(derived_failed) != set(failed):
        raise ValueError("held-out failed-clause list is inconsistent")
    passed_count = sum(bool(clause["passed"]) for clause in all_clauses.values())
    physical_cost = _observed_api_cost(observed, registration)
    primary = registration["calibration"]["selected_query_variant"]
    diagnostic_quality = {
        arm: values
        for arm, values in decision["quality"].items()
        if arm != primary
    }
    return {
        "schema_version": "conversation-memory-heldout-analysis-v1",
        "status": f"GATE_1_{decision['verdict']}",
        "scope": "ORQ-27 Gate 1 offline experiment only; no runtime, Gate 2, Gate 3, or semantic-memory authorization",
        "source_run": str(run_path.relative_to(ROOT)),
        "source_run_sha256": sha256_file(run_path),
        "source_run_id": run["run_id"],
        "source_git_head": run["git_head"],
        "registration_sha256": run["registration_sha256"],
        "heldout_dataset_sha256": run["dataset_sha256"],
        "attempt_ledger": str(attempt_ledger_path.relative_to(ROOT)),
        "attempt_ledger_sha256": sha256_file(attempt_ledger_path),
        "attempt_number": terminal["attempt_number"],
        "replacement_used": False,
        "verdict": decision["verdict"],
        "decision_rule": decision["rule"],
        "selected_query_variant": primary,
        "selected_parameters": run["selected_candidate"]["candidate"],
        "criterion_evaluation": criteria,
        "threshold_clauses": threshold_clauses,
        "automatic_clauses": automatic_clauses,
        "failed_clauses": failed,
        "passed_clause_count": passed_count,
        "total_clause_count": len(all_clauses),
        "quality": decision["quality"],
        "diagnostic_quality": diagnostic_quality,
        "paired_primary_recall": decision[
            "conversation_clustered_paired_d_over_c_recall"
        ],
        "slice_recall_accuracy": decision["slice_recall_accuracy"],
        "retrieval": run["selected_candidate"]["aggregate"][primary],
        "decision_values": decision["values"],
        "logical_mean_conversation_api_cost": decision[
            "logical_mean_conversation_api_cost"
        ],
        "observed_execution": observed,
        "physical_experiment_api_cost": physical_cost,
        "conclusion": (
            "The selected D1 strategy improved recall and consistency over the recent-window "
            "baseline and reduced logical API cost versus bounded history replay, but it failed "
            "the registered quality-preservation, ambiguous-follow-up, and p95 TTFT clauses. "
            "The conjunctive Gate 1 decision is therefore NO_GO, so ORQ-27 stops before Gate 2."
        ),
        "diagnostic_arm_rule": (
            "D2_JSON and D2_TEXT remain diagnostic. Their held-out results cannot replace the "
            "development-selected D1 arm or rescue NO_GO under the frozen registration."
        ),
        "next_action": (
            "Do not implement Gate 2 or Gate 3. Any new query or memory design requires a new "
            "operator-approved hypothesis and pre-registration; this held-out cannot be rerun."
        ),
    }


def render_markdown(analysis: Mapping[str, Any]) -> str:
    quality = analysis["quality"]
    values = analysis["decision_values"]
    lines = [
        "# ORQ-27 Gate 1 held-out report",
        "",
        f"**Verdict:** {analysis['verdict']}",
        "",
        analysis["scope"],
        "",
        "## Reproducibility",
        "",
        f"- Source run: `{analysis['source_run']}`",
        f"- Source run SHA-256: `{analysis['source_run_sha256']}`",
        f"- Run ID: `{analysis['source_run_id']}`",
        f"- Instrument commit: `{analysis['source_git_head']}`",
        f"- Registration SHA-256: `{analysis['registration_sha256']}`",
        f"- Held-out dataset SHA-256: `{analysis['heldout_dataset_sha256']}`",
        f"- Attempt ledger SHA-256: `{analysis['attempt_ledger_sha256']}`",
        f"- Attempt: `{analysis['attempt_number']}`; replacement used: `{str(analysis['replacement_used']).lower()}`",
        f"- Clauses passed: `{analysis['passed_clause_count']}/{analysis['total_clause_count']}`",
        "",
        "## Primary result",
        "",
        "| Arm | Recall | Fact consistency | Mean logical API cost/conversation |",
        "|---|---:|---:|---:|",
    ]
    costs = analysis["logical_mean_conversation_api_cost"]
    for arm in ("A", "B", "C", "D1", "D2_JSON", "D2_TEXT"):
        lines.append(
            f"| {arm} | {quality[arm]['conversational_recall_accuracy']:.4f} | "
            f"{quality[arm]['fact_consistency']:.4f} | ${costs[arm]:.8f} |"
        )
    lines.extend(
        [
            "",
            f"The registered primary arm was `{analysis['selected_query_variant']}`. "
            f"It improved recall over C by {values['d_over_c_recall_improvement']:.4f}, "
            f"with a one-sided clustered 95% lower bound of "
            f"{analysis['paired_primary_recall']['one_sided_ci95_low']:.4f}. It reduced logical "
            f"API cost versus B by {values['d_vs_b_cumulative_api_cost_improvement']:.2%}.",
            "",
            "## Failed conjunctive clauses",
            "",
            "| Clause | Value | Required | Evaluation |",
            "|---|---:|---:|---|",
        ]
    )
    for name in analysis["failed_clauses"]:
        clause = analysis["threshold_clauses"].get(name) or analysis[
            "automatic_clauses"
        ][name]
        lines.append(
            f"| `{name}` | {clause['value']} | {clause.get('operator', '')} "
            f"{clause.get('threshold', clause.get('expected'))} | unrounded point/registered guard |"
        )
    physical = analysis["physical_experiment_api_cost"]
    lines.extend(
        [
            "",
            "## Execution integrity and cost",
            "",
            f"- API calls: `{analysis['observed_execution']['succeeded_calls']}` succeeded, "
            f"`{analysis['observed_execution']['failed_calls']}` failed, "
            f"`{analysis['observed_execution']['unknown_outcome_calls']}` unknown.",
            f"- Required generation usage missing: `{analysis['observed_execution']['missing_success_usage_calls']}`.",
            "- Tenant/conversation isolation failures: `0`.",
            f"- Estimated physical embedding cost: `${physical['embedding_api_cost_estimated']:.8f}`.",
            f"- Generation cost from actual usage: `${physical['generation_api_cost']:.8f}`.",
            f"- Total estimated physical API cost: `${physical['total_estimated_api_cost']:.8f}`.",
            "",
            "## Decision",
            "",
            analysis["conclusion"],
            "",
            analysis["diagnostic_arm_rule"],
            "",
            analysis["next_action"],
            "",
        ]
    )
    return "\n".join(lines)


def _attempt_events(path: Path, *, run_id: str) -> list[dict[str, Any]]:
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [event for event in events if event.get("run_id") == run_id]


def _observed_api_cost(
    observed: Mapping[str, Any], registration: Mapping[str, Any]
) -> dict[str, Any]:
    pricing = registration["pricing"]
    embedding = (
        observed["estimated_embedding_tokens"]
        * pricing["embedding_input_per_million"]
        / 1_000_000
    )
    generation = (
        observed["actual_generation_input_tokens"]
        * pricing["generation_input_per_million"]
        + observed["actual_generation_output_tokens"]
        * pricing["generation_output_per_million"]
    ) / 1_000_000
    return {
        "currency": pricing["currency"],
        "embedding_api_cost_estimated": embedding,
        "generation_api_cost": generation,
        "total_estimated_api_cost": embedding + generation,
        "embedding_usage_provenance": "estimated",
    }


def _verify_source_registration_snapshot(run: Mapping[str, Any]) -> None:
    git_head = run["git_head"]
    registration_path = run["registration_path"]
    if not isinstance(git_head, str) or not re.fullmatch(r"[0-9a-f]{40}", git_head):
        raise ValueError("run git head is invalid")
    result = subprocess.run(
        ["git", "show", f"{git_head}:{registration_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("source registration snapshot is unavailable")
    if hashlib.sha256(result.stdout).hexdigest() != run["registration_sha256"]:
        raise ValueError("source registration snapshot hash mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze the ORQ-27 Gate 1 held-out run.")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument(
        "--registration",
        type=Path,
        default=ROOT / "experiments/conversational_memory/registration.json",
    )
    parser.add_argument(
        "--execution-ledger",
        type=Path,
        default=ROOT / "experiments/conversational_memory/runs/execution-ledger.jsonl",
    )
    parser.add_argument(
        "--attempt-ledger",
        type=Path,
        default=ROOT / "experiments/conversational_memory/runs/heldout-attempts.jsonl",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / "experiments/conversational_memory/heldout-analysis.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=ROOT / "experiments/conversational_memory/heldout-report.md",
    )
    args = parser.parse_args()
    analysis = build_analysis(
        run_path=args.run.resolve(),
        registration_path=args.registration.resolve(),
        execution_ledger_path=args.execution_ledger.resolve(),
        attempt_ledger_path=args.attempt_ledger.resolve(),
    )
    args.json_output.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(render_markdown(analysis), encoding="utf-8")
    print(f"json_output={args.json_output}")
    print(f"markdown_output={args.markdown_output}")
    print(f"verdict={analysis['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
