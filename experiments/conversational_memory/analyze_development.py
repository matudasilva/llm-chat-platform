from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

from .dataset import load_dataset, sha256_file
from .execution import summarize_execution_ledger
from .run_experiment import (
    ARMS,
    MEMORY_ARMS,
    evaluate_registered_thresholds,
    paired_bootstrap_interval,
)


ROOT = Path(__file__).resolve().parents[2]
QUERY_TIE_PRIORITY = {"D1": 0, "D2_TEXT": 1, "D2_JSON": 2}


def build_analysis(
    *,
    run_path: Path,
    dataset_path: Path,
    execution_ledger_path: Path,
) -> dict[str, Any]:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run["phase"] != "development" or run["heldout_inspected"]:
        raise ValueError("analysis accepts an unblinded development run only")
    registration_path = ROOT / run["registration_path"]
    _verify_source_registration_snapshot(run)
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    fixtures = load_dataset(dataset_path, expected_split="development")
    evaluations = {
        evaluation.step_id: evaluation
        for fixture in fixtures
        for evaluation in fixture.evaluations
    }
    step_clusters = {
        evaluation.step_id: fixture.conversation_id
        for fixture in fixtures
        for evaluation in fixture.evaluations
    }
    expected_repetitions = registration["calibration"]["managed_generation_repetitions"]
    observations: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in run["generation_observations"]:
        observations[(observation["step_id"], observation["arm"])].append(observation)
    step_scores: dict[str, dict[str, float]] = {arm: {} for arm in ARMS}
    step_consistency: dict[str, dict[str, float]] = {arm: {} for arm in ARMS}
    for step_id in evaluations:
        for arm in ARMS:
            items = observations[(step_id, arm)]
            repetitions = {item["repetition"] for item in items}
            if len(items) != expected_repetitions or repetitions != set(
                range(1, expected_repetitions + 1)
            ):
                raise ValueError(f"incomplete generation observations for {step_id}/{arm}")
            step_scores[arm][step_id] = mean(
                item["conversational_recall_accuracy"] for item in items
            )
            step_consistency[arm][step_id] = mean(
                item["fact_consistency"] for item in items
            )
    quality = {
        arm: {
            "conversational_recall_accuracy": mean(step_scores[arm].values()),
            "fact_consistency": mean(step_consistency[arm].values()),
        }
        for arm in ARMS
    }
    for arm in MEMORY_ARMS:
        quality[arm]["paired_vs_c"] = paired_bootstrap_interval(
            step_scores[arm],
            step_scores["C"],
            step_clusters=step_clusters,
            samples=10_000,
            seed=2701,
        )
        quality[arm]["paired_vs_b"] = paired_bootstrap_interval(
            step_scores[arm],
            step_scores["B"],
            step_clusters=step_clusters,
            samples=10_000,
            seed=2701,
        )
    slices = _slice_metrics(evaluations, step_scores, step_consistency)
    logical_costs = _logical_cost_summary(run["cost_taxonomy"]["logical_strategy_ledgers"])
    retrieval = run["selected_candidate"]["aggregate"]
    selected_arm, selection_scorecards = select_query_variant(
        quality=quality,
        slices=slices,
        logical_costs=logical_costs,
        retrieval=retrieval,
    )
    generation = run["generation_aggregate"]
    observed = summarize_execution_ledger(execution_ledger_path, run_id=run["run_id"])
    proposal_values = _proposal_values(
        selected_arm=selected_arm,
        quality=quality,
        slices=slices,
        logical_costs=logical_costs,
        retrieval=retrieval,
        generation=generation,
        break_even=run["cost_taxonomy"]["logical_break_even_vs_b"],
        observed=observed,
    )
    thresholds = registration["decision_rule"]["thresholds"]
    proposal_clauses = evaluate_registered_thresholds(proposal_values, thresholds)
    failed_development_clauses = [
        name for name, clause in proposal_clauses.items() if not clause["passed"]
    ]
    return {
        "schema_version": "conversation-memory-development-analysis-v2",
        "status": "AWAITING_OPERATOR_PREREGISTRATION_APPROVAL",
        "scope": "Gate 1 final development/calibration iteration only; no held-out result and no GO/STOP verdict",
        "source_run": str(run_path.relative_to(ROOT)),
        "source_run_sha256": sha256_file(run_path),
        "source_run_id": run["run_id"],
        "source_git_head": run["git_head"],
        "source_registration_sha256": run["registration_sha256"],
        "source_registration_git_snapshot_verified": True,
        "proposal_registration_sha256": sha256_file(registration_path),
        "development_dataset_sha256": run["dataset_sha256"],
        "heldout_inspected": False,
        "scorer_version": "nested-forbidden-span-safe-v2",
        "selected_parameters_proposal": run["selected_candidate"]["candidate"],
        "selected_query_variant_proposal": selected_arm,
        "query_selection_rule": registration["calibration"]["query_selection_rule"],
        "query_selection_scorecards": selection_scorecards,
        "query_selection_rationale": _selection_rationale(selected_arm, selection_scorecards),
        "heldout_generation_repetitions_proposal": expected_repetitions,
        "quality": quality,
        "retrieval": retrieval,
        "slices": slices,
        "generation": generation,
        "logical_costs": logical_costs,
        "logical_break_even_vs_b": run["cost_taxonomy"]["logical_break_even_vs_b"],
        "observed_execution_current_run": observed,
        "actual_experiment_cash_spend_estimate": _observed_api_cost(observed),
        "threshold_proposal": thresholds,
        "development_values_against_proposal": proposal_values,
        "development_threshold_clauses": proposal_clauses,
        "failed_development_clauses": failed_development_clauses,
        "paired_rule_proposal": (
            "Average repetitions within each step, then unrounded step values within each "
            "conversation. Resample conversations for a fixed-seed 10,000-sample paired "
            "bootstrap and require the one-sided selected-arm-minus-C recall 95 percent lower "
            "bound above zero. Small slices use exact point aggregates without intervals. Every "
            "quality, cost, latency, retrieval, slice, and safety clause is conjunctive."
        ),
        "automatic_no_go": registration["decision_rule"]["automatic_no_go"],
        "provider_contract_discrepancy": (
            "The unchanged production OpenAI Responses serializer returned HTTP 400 on the first "
            "assistant-history replay because it encodes every role as input_text. Gate 1 uses an "
            "experiment-only string-content ProviderPort adapter. Any Gate 2 history path requires "
            "separate design review and contractual JSON/SSE coverage; production was unchanged."
        ),
        "next_required_action": (
            "The operator approves or revises the proposed parameters, selected query variant, "
            "margins, repetitions, and clustered paired rule. Only then may registration be "
            "signed and committed before a single held-out execution."
        ),
    }


def select_query_variant(
    *,
    quality: Mapping[str, Mapping[str, Any]],
    slices: Mapping[str, Mapping[str, Any]],
    logical_costs: Mapping[str, Mapping[str, Any]],
    retrieval: Mapping[str, Mapping[str, Any]],
) -> tuple[str, dict[str, dict[str, float | int]]]:
    scorecards: dict[str, dict[str, float | int]] = {}
    for arm in MEMORY_ARMS:
        scorecards[arm] = {
            "fact_consistency": quality[arm]["fact_consistency"],
            "conversational_recall_accuracy": quality[arm][
                "conversational_recall_accuracy"
            ],
            "ambiguous_followup_recall_accuracy": slices["ambiguous_followup"][
                "recall_accuracy"
            ][arm],
            "exact_identifier_recall_accuracy": slices["exact_identifier"][
                "recall_accuracy"
            ][arm],
            "mean_logical_api_cost": logical_costs[arm][
                "mean_total_estimated_api_cost"
            ],
            "irrelevant_memory_injection_rate": retrieval[arm][
                "irrelevant_memory_injection_rate"
            ],
            "superseded_fact_retrieval_rate": retrieval[arm][
                "superseded_fact_retrieval_rate"
            ],
            "repeated_source_amplification_rate": retrieval[arm][
                "repeated_source_amplification_rate"
            ],
            "mean_query_estimated_tokens": retrieval[arm]["mean_query_estimated_tokens"],
            "tie_priority": QUERY_TIE_PRIORITY[arm],
        }

    def rank(arm: str) -> tuple[float | int, ...]:
        item = scorecards[arm]
        return (
            -item["fact_consistency"],
            -item["conversational_recall_accuracy"],
            -item["ambiguous_followup_recall_accuracy"],
            -item["exact_identifier_recall_accuracy"],
            item["mean_logical_api_cost"],
            item["irrelevant_memory_injection_rate"],
            item["superseded_fact_retrieval_rate"],
            item["repeated_source_amplification_rate"],
            item["mean_query_estimated_tokens"],
            item["tie_priority"],
        )

    return min(MEMORY_ARMS, key=rank), scorecards


def render_markdown(analysis: Mapping[str, Any]) -> str:
    quality = analysis["quality"]
    retrieval = analysis["retrieval"]
    costs = analysis["logical_costs"]
    generation = analysis["generation"]
    selected = analysis["selected_query_variant_proposal"]
    lines = [
        "# ORQ-27 Gate 1 final development calibration report",
        "",
        f"**Status:** {analysis['status']}",
        "",
        analysis["scope"],
        "",
        "## Reproducibility",
        "",
        f"- Source run: `{analysis['source_run']}`",
        f"- Source run SHA-256: `{analysis['source_run_sha256']}`",
        f"- Run ID: `{analysis['source_run_id']}`",
        f"- Instrument commit: `{analysis['source_git_head']}`",
        f"- Source-run registration SHA-256: `{analysis['source_registration_sha256']}`",
        f"- Proposed registration SHA-256: `{analysis['proposal_registration_sha256']}`",
        "- Source registration verified from the instrument commit: `true`",
        f"- Development dataset SHA-256: `{analysis['development_dataset_sha256']}`",
        f"- Scorer: `{analysis['scorer_version']}`",
        "- Held-out inspected: `false`",
        "",
        "## Development result",
        "",
        "| Arm | Recall | Consistency | Mean logical API cost/conversation | p95 latency ms | p95 TTFT ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        lines.append(
            f"| {arm} | {quality[arm]['conversational_recall_accuracy']:.4f} | "
            f"{quality[arm]['fact_consistency']:.4f} | "
            f"{costs[arm]['mean_total_estimated_api_cost']:.8f} | "
            f"{generation[arm]['latency_ms']['p95']:.2f} | "
            f"{generation[arm]['ttft_ms']['p95']:.2f} |"
        )
    lines.extend(
        [
            "",
            "Selected parameter proposal: `"
            + json.dumps(analysis["selected_parameters_proposal"], sort_keys=True)
            + "`.",
            "",
            f"Selected query proposal: **{selected}**. {analysis['query_selection_rationale']}",
            "",
            "| Retrieval metric | D1 | D2_JSON | D2_TEXT |",
            "|---|---:|---:|---:|",
        ]
    )
    for field in (
        "precision_at_k",
        "recall_at_k",
        "mrr",
        "delivered_unique_source_recall",
        "irrelevant_memory_injection_rate",
        "duplicate_chunk_slot_rate",
        "superseded_fact_retrieval_rate",
        "repeated_source_amplification_rate",
    ):
        lines.append(
            f"| {field} | "
            + " | ".join(f"{retrieval[arm][field]:.4f}" for arm in MEMORY_ARMS)
            + " |"
        )
    lines.extend(
        [
            "",
            "## Proposed held-out contract — operator approval required",
            "",
            analysis["paired_rule_proposal"],
            "",
            "Failed development clauses under the proposed held-out margins: `"
            + json.dumps(analysis["failed_development_clauses"])
            + "`.",
            "",
            "## Recorded production-adapter discrepancy",
            "",
            analysis["provider_contract_discrepancy"],
            "",
            "## Next checkpoint",
            "",
            analysis["next_required_action"],
            "",
            "No held-out execution, Gate 2, Gate 3, semantic memory, migration, `/chat` change, "
            "or production runtime change was performed.",
        ]
    )
    return "\n".join(lines) + "\n"


def _slice_metrics(
    evaluations: Mapping[str, Any],
    step_scores: Mapping[str, Mapping[str, float]],
    step_consistency: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    slice_names = sorted(
        {slice_name for evaluation in evaluations.values() for slice_name in evaluation.slices}
    )
    for slice_name in slice_names:
        step_ids = [
            step_id
            for step_id, evaluation in evaluations.items()
            if slice_name in evaluation.slices
        ]
        result[slice_name] = {
            "steps": len(step_ids),
            "recall_accuracy": {
                arm: mean(step_scores[arm][step_id] for step_id in step_ids) for arm in ARMS
            },
            "fact_consistency": {
                arm: mean(step_consistency[arm][step_id] for step_id in step_ids)
                for arm in ARMS
            },
        }
    return result


def _proposal_values(
    *,
    selected_arm: str,
    quality: Mapping[str, Mapping[str, Any]],
    slices: Mapping[str, Mapping[str, Any]],
    logical_costs: Mapping[str, Mapping[str, Any]],
    retrieval: Mapping[str, Mapping[str, Any]],
    generation: Mapping[str, Mapping[str, Any]],
    break_even: Mapping[str, Mapping[str, Any]],
    observed: Mapping[str, Any],
) -> dict[str, float | int | None]:
    selected_cost = logical_costs[selected_arm]["mean_total_estimated_api_cost"]
    baseline_cost = logical_costs["B"]["mean_total_estimated_api_cost"]
    break_even_values = [
        item["break_even_exchange"]
        for item in break_even.values()
        if item["arm"] == selected_arm
    ]
    retrieval_values = retrieval[selected_arm]
    return {
        "d_over_c_recall_improvement": quality[selected_arm][
            "conversational_recall_accuracy"
        ]
        - quality["C"]["conversational_recall_accuracy"],
        "d_over_c_fact_consistency_improvement": quality[selected_arm]["fact_consistency"]
        - quality["C"]["fact_consistency"],
        "d_below_b_recall_loss": quality["B"]["conversational_recall_accuracy"]
        - quality[selected_arm]["conversational_recall_accuracy"],
        "d_below_b_fact_consistency_loss": quality["B"]["fact_consistency"]
        - quality[selected_arm]["fact_consistency"],
        "d_vs_b_cumulative_api_cost_improvement": 1 - selected_cost / baseline_cost,
        "worst_break_even_exchange": max(break_even_values)
        if break_even_values and all(value is not None for value in break_even_values)
        else None,
        "observed_retry_or_rebuild_cost_overhead": 0.0
        if observed["failed_calls"] == 0 and observed["unknown_outcome_calls"] == 0
        else None,
        "irrelevant_injection_rate": retrieval_values["irrelevant_memory_injection_rate"],
        "duplicate_chunk_slot_rate": retrieval_values["duplicate_chunk_slot_rate"],
        "superseded_retrieval_rate": retrieval_values["superseded_fact_retrieval_rate"],
        "repeated_source_amplification_rate": retrieval_values[
            "repeated_source_amplification_rate"
        ],
        "message_recall_at_k": retrieval_values["recall_at_k"],
        "delivered_unique_source_recall": retrieval_values[
            "delivered_unique_source_recall"
        ],
        "ambiguous_followup_recall_accuracy": slices["ambiguous_followup"][
            "recall_accuracy"
        ][selected_arm],
        "exact_identifier_recall_accuracy": slices["exact_identifier"][
            "recall_accuracy"
        ][selected_arm],
        "echo_overlap_p95": generation[selected_arm]["echo_overlap"]["p95"],
        "p95_latency_regression_ms": generation[selected_arm]["latency_ms"]["p95"]
        - generation["C"]["latency_ms"]["p95"],
        "p95_ttft_regression_ms": generation[selected_arm]["ttft_ms"]["p95"]
        - generation["C"]["ttft_ms"]["p95"],
    }


def _logical_cost_summary(ledgers: Mapping[str, Any]) -> dict[str, Any]:
    by_arm: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for ledger in ledgers.values():
        by_arm[ledger["arm"]].append(ledger)
    return {
        arm: {
            "conversations": len(items),
            "mean_total_estimated_api_cost": mean(
                item["total_estimated_api_cost"] for item in items
            ),
            "mean_cumulative_input_tokens": mean(
                item["steps"][-1]["cumulative_input_tokens"] for item in items
            ),
            "mean_cumulative_output_tokens": mean(
                item["steps"][-1]["cumulative_output_tokens"] for item in items
            ),
        }
        for arm, items in sorted(by_arm.items())
    }


def _selection_rationale(
    selected_arm: str, scorecards: Mapping[str, Mapping[str, Any]]
) -> str:
    selected = scorecards[selected_arm]
    return (
        "The predeclared lexicographic rule selected this arm from unrounded development values: "
        f"consistency={selected['fact_consistency']}, recall={selected['conversational_recall_accuracy']}, "
        f"ambiguous={selected['ambiguous_followup_recall_accuracy']}, "
        f"exact_identifier={selected['exact_identifier_recall_accuracy']}, "
        f"logical_cost={selected['mean_logical_api_cost']}."
    )


def _observed_api_cost(observed: Mapping[str, Any]) -> dict[str, Any]:
    embedding = observed["estimated_embedding_tokens"] * 0.02 / 1_000_000
    generation = (
        observed["actual_generation_input_tokens"] * 0.15
        + observed["actual_generation_output_tokens"] * 0.60
    ) / 1_000_000
    return {
        "currency": "USD",
        "embedding_cost_estimated": embedding,
        "generation_cost_from_actual_usage": generation,
        "total_estimated_api_cost": embedding + generation,
        "note": "Physical experiment spend; not a standalone memory-strategy cost.",
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
    actual = hashlib.sha256(result.stdout).hexdigest()
    if actual != run["registration_sha256"]:
        raise ValueError("source registration snapshot hash mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze an unblinded ORQ-27 development run.")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "experiments/conversational_memory/data/development.jsonl",
    )
    parser.add_argument(
        "--execution-ledger",
        type=Path,
        default=ROOT / "experiments/conversational_memory/runs/execution-ledger.jsonl",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / "experiments/conversational_memory/development-analysis.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=ROOT / "experiments/conversational_memory/development-report.md",
    )
    args = parser.parse_args()
    analysis = build_analysis(
        run_path=args.run.resolve(),
        dataset_path=args.dataset.resolve(),
        execution_ledger_path=args.execution_ledger.resolve(),
    )
    args.json_output.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(render_markdown(analysis), encoding="utf-8")
    print(f"json_output={args.json_output}")
    print(f"markdown_output={args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
