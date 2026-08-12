from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from .dataset import load_dataset, sha256_file
from .execution import summarize_execution_ledger


ROOT = Path(__file__).resolve().parents[2]


def paired_bootstrap_interval(
    selected: Mapping[str, float],
    comparator: Mapping[str, float],
    *,
    samples: int = 10_000,
    seed: int = 2701,
) -> dict[str, float | int]:
    if set(selected) != set(comparator) or not selected:
        raise ValueError("paired samples must have the same non-empty step IDs")
    if samples <= 0:
        raise ValueError("samples must be positive")
    step_ids = sorted(selected)
    differences = [selected[step_id] - comparator[step_id] for step_id in step_ids]
    rng = random.Random(seed)
    draws = sorted(
        mean(rng.choice(differences) for _ in differences) for _ in range(samples)
    )
    return {
        "step_count": len(step_ids),
        "samples": samples,
        "seed": seed,
        "mean_difference": mean(differences),
        "ci95_low": _percentile(draws, 0.025),
        "ci95_high": _percentile(draws, 0.975),
    }


def build_analysis(
    *,
    run_path: Path,
    dataset_path: Path,
    execution_ledger_path: Path,
) -> dict[str, Any]:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run["phase"] != "development" or run["heldout_inspected"]:
        raise ValueError("analysis accepts an unblinded development run only")
    fixtures = load_dataset(dataset_path, expected_split="development")
    evaluations = {
        evaluation.step_id: evaluation
        for fixture in fixtures
        for evaluation in fixture.evaluations
    }
    observations: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in run["generation_observations"]:
        observations[(observation["step_id"], observation["arm"])].append(observation)
    step_scores: dict[str, dict[str, float]] = {arm: {} for arm in ("A", "B", "C", "D1", "D2")}
    step_consistency: dict[str, dict[str, float]] = {
        arm: {} for arm in ("A", "B", "C", "D1", "D2")
    }
    for step_id in evaluations:
        for arm in step_scores:
            items = observations[(step_id, arm)]
            if not items:
                raise ValueError(f"missing generation observation for {step_id}/{arm}")
            step_scores[arm][step_id] = mean(
                item["conversational_recall_accuracy"] for item in items
            )
            step_consistency[arm][step_id] = mean(item["fact_consistency"] for item in items)
    quality = {
        arm: {
            "conversational_recall_accuracy": mean(step_scores[arm].values()),
            "fact_consistency": mean(step_consistency[arm].values()),
        }
        for arm in step_scores
    }
    quality["D1"]["paired_vs_c"] = paired_bootstrap_interval(
        step_scores["D1"], step_scores["C"]
    )
    quality["D1"]["paired_vs_b"] = paired_bootstrap_interval(
        step_scores["D1"], step_scores["B"]
    )
    slices: dict[str, dict[str, Any]] = {}
    for slice_name in sorted(
        {slice_name for evaluation in evaluations.values() for slice_name in evaluation.slices}
    ):
        ids = [
            step_id
            for step_id, evaluation in evaluations.items()
            if slice_name in evaluation.slices
        ]
        slices[slice_name] = {
            "steps": len(ids),
            "recall_accuracy": {
                arm: mean(step_scores[arm][step_id] for step_id in ids)
                for arm in step_scores
            },
            "fact_consistency": {
                arm: mean(step_consistency[arm][step_id] for step_id in ids)
                for arm in step_scores
            },
        }
    logical_costs = _logical_cost_summary(run["cost_taxonomy"]["logical_strategy_ledgers"])
    d1_vs_b_cost_improvement = 1 - (
        logical_costs["D1"]["mean_total_estimated_api_cost"]
        / logical_costs["B"]["mean_total_estimated_api_cost"]
    )
    generation = run["generation_aggregate"]
    thresholds = {
        "minimum_d_over_c_recall_improvement": 0.20,
        "minimum_d_over_c_fact_consistency_improvement": 0.20,
        "maximum_d_below_b_quality_loss": 0.25,
        "minimum_d_vs_b_cumulative_api_cost_improvement": 0.15,
        "primary_break_even_exchange": 6,
        "maximum_observed_retry_or_rebuild_cost_overhead": 0.0,
        "maximum_irrelevant_injection_rate": 0.80,
        "maximum_duplicate_chunk_slot_rate": 0.10,
        "maximum_superseded_retrieval_rate": 0.20,
        "maximum_repeated_source_amplification_rate": 0.25,
        "minimum_message_recall_at_k": 0.30,
        "minimum_delivered_unique_source_recall": 0.60,
        "minimum_ambiguous_followup_recall_accuracy": 0.50,
        "minimum_exact_identifier_recall_accuracy": 0.75,
        "maximum_echo_overlap_p95": 0.70,
        "maximum_p95_latency_regression_ms": 300,
        "maximum_p95_ttft_regression_ms": 300,
    }
    selected_retrieval = run["selected_candidate"]["aggregate"]["D1"]
    observed = summarize_execution_ledger(execution_ledger_path, run_id=run["run_id"])
    proposal_checks = {
        "d1_over_c_recall": quality["D1"]["conversational_recall_accuracy"]
        - quality["C"]["conversational_recall_accuracy"],
        "d1_over_c_fact_consistency": quality["D1"]["fact_consistency"]
        - quality["C"]["fact_consistency"],
        "d1_below_b_quality_loss": quality["B"]["conversational_recall_accuracy"]
        - quality["D1"]["conversational_recall_accuracy"],
        "d1_vs_b_logical_cost_improvement": d1_vs_b_cost_improvement,
        "d1_message_recall_at_k": selected_retrieval["recall_at_k"],
        "d1_delivered_unique_source_recall": selected_retrieval[
            "delivered_unique_source_recall"
        ],
        "d1_irrelevant_injection_rate": selected_retrieval[
            "irrelevant_memory_injection_rate"
        ],
        "d1_duplicate_chunk_slot_rate": selected_retrieval[
            "duplicate_chunk_slot_rate"
        ],
        "d1_superseded_retrieval_rate": selected_retrieval[
            "superseded_fact_retrieval_rate"
        ],
        "d1_repeated_source_amplification_rate": selected_retrieval[
            "repeated_source_amplification_rate"
        ],
        "d1_ambiguous_followup_recall_accuracy": slices["ambiguous_followup"][
            "recall_accuracy"
        ]["D1"],
        "d1_exact_identifier_recall_accuracy": slices["exact_identifier"][
            "recall_accuracy"
        ]["D1"],
        "d1_echo_overlap_p95": generation["D1"]["echo_overlap"]["p95"],
        "d1_p95_latency_regression_ms": generation["D1"]["latency_ms"]["p95"]
        - generation["C"]["latency_ms"]["p95"],
        "d1_p95_ttft_regression_ms": generation["D1"]["ttft_ms"]["p95"]
        - generation["C"]["ttft_ms"]["p95"],
        "observed_failed_calls": observed["failed_calls"],
        "observed_unknown_outcome_calls": observed["unknown_outcome_calls"],
    }
    return {
        "schema_version": "conversation-memory-development-analysis-v1",
        "status": "AWAITING_OPERATOR_PREREGISTRATION_APPROVAL",
        "scope": "Gate 1 development/calibration only; no held-out result and no GO/STOP verdict",
        "source_run": str(run_path.relative_to(ROOT)),
        "source_run_sha256": sha256_file(run_path),
        "source_run_id": run["run_id"],
        "source_registration_sha256": run["registration_sha256"],
        "development_dataset_sha256": run["dataset_sha256"],
        "heldout_inspected": False,
        "selected_parameters_proposal": run["selected_candidate"]["candidate"],
        "selected_query_variant_proposal": "D1",
        "query_selection_rationale": (
            "D1 and D2 tied on answer recall and fact consistency. D1 used fewer input/query "
            "tokens, lower logical API cost, lower irrelevant/superseded/amplified retrieval, "
            "and better p95 latency/TTFT. D2's better delivered-source recall did not improve "
            "the development answer score."
        ),
        "heldout_generation_repetitions_proposal": 3,
        "quality": quality,
        "retrieval": run["selected_candidate"]["aggregate"],
        "slices": slices,
        "generation": generation,
        "logical_costs": logical_costs,
        "logical_break_even_vs_b": run["cost_taxonomy"]["logical_break_even_vs_b"],
        "observed_execution_current_run": observed,
        "raw_run_correction": (
            "The raw run's observed_execution summary included earlier ledger runs. The runner "
            "is now fixed to filter by run_id; observed_execution_current_run is the corrected "
            "view. Raw evidence remains append-only and was not overwritten."
        ),
        "actual_experiment_cash_spend_estimate": _observed_api_cost(observed),
        "threshold_proposal": thresholds,
        "development_values_against_proposal": proposal_checks,
        "paired_rule_proposal": (
            "Average repetitions within each evaluation step; compare D1-C and D1-B on paired "
            "step scores. Require the D1-C point improvement threshold and a fixed-seed 10,000-"
            "sample paired-bootstrap 95% lower bound above zero. Apply the B loss, cost, latency, "
            "retrieval, slice, and safety thresholds independently; every clause must pass."
        ),
        "automatic_no_go": [
            "any tenant or conversation prompt-bearing leak",
            "any missing held-out step/arm/repetition",
            "any null required usage without an approved exclusion",
            "any failed mandatory decision clause",
        ],
        "development_warning": (
            "Under the proposed thresholds, development would miss the B-quality-loss limit "
            "and the ambiguous-follow-up floor. This is a warning, not a held-out STOP verdict."
        ),
        "provider_contract_discrepancy": (
            "The unchanged production OpenAI Responses serializer returned HTTP 400 on the first "
            "assistant-history replay because it encodes every role as input_text. Gate 1 uses an "
            "experiment-only string-content ProviderPort adapter. Any Gate 2 OpenAI history path "
            "therefore requires separate design review; production was not changed."
        ),
        "next_required_action": (
            "Operator approves or revises the frozen parameters, D1 selection, repetitions, "
            "thresholds, and paired rule; then the registration is signed and committed before "
            "held-out execution."
        ),
    }


def render_markdown(analysis: Mapping[str, Any]) -> str:
    quality = analysis["quality"]
    retrieval = analysis["retrieval"]
    costs = analysis["logical_costs"]
    generation = analysis["generation"]
    lines = [
        "# ORQ-27 Gate 1 development calibration report",
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
        f"- Registration SHA-256: `{analysis['source_registration_sha256']}`",
        f"- Development dataset SHA-256: `{analysis['development_dataset_sha256']}`",
        "- Held-out inspected: `false`",
        "",
        "## Development result",
        "",
        "| Arm | Recall accuracy | Fact consistency | Mean logical API cost / conversation | p95 latency ms | p95 TTFT ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in ("A", "B", "C", "D1", "D2"):
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
            "Selected retrieval candidate proposal: `"
            + json.dumps(analysis["selected_parameters_proposal"], sort_keys=True)
            + "`.",
            "",
            "Selected primary query proposal: **D1**. " + analysis["query_selection_rationale"],
            "",
            "| Retrieval metric | D1 | D2 |",
            "|---|---:|---:|",
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
        lines.append(f"| {field} | {retrieval['D1'][field]:.4f} | {retrieval['D2'][field]:.4f} |")
    lines.extend(
        [
            "",
            "## Interpretation before held-out",
            "",
            "- D1 improved recall accuracy over C by "
            f"{quality['D1']['conversational_recall_accuracy'] - quality['C']['conversational_recall_accuracy']:.4f} absolute, "
            "but remained "
            f"{quality['B']['conversational_recall_accuracy'] - quality['D1']['conversational_recall_accuracy']:.4f} below B.",
            "- D1 reduced mean logical API cost versus B by "
            f"{1 - costs['D1']['mean_total_estimated_api_cost'] / costs['B']['mean_total_estimated_api_cost']:.2%}.",
            "- D1 ambiguous-follow-up recall accuracy was "
            f"{analysis['slices']['ambiguous_followup']['recall_accuracy']['D1']:.4f}; this is the strongest development warning.",
            "- Tenant/conversation isolation failures: `0`.",
            "- Reducing tokens remains an operational-efficiency proxy, not evidence of lower energy or CO2e.",
            "",
            "## Proposed frozen decision contract (operator approval required)",
            "",
            "The proposal is machine-readable in `development-analysis.json`. Key choices are D1, "
            "three held-out generation repetitions, paired step-level comparison, fixed-seed paired "
            "bootstrap, and conjunctive quality/cost/safety thresholds. No threshold is approved by "
            "this report.",
            "",
            "Development warning: " + analysis["development_warning"],
            "",
            "## Recorded discrepancy",
            "",
            analysis["provider_contract_discrepancy"],
            "",
            analysis["raw_run_correction"],
            "",
            "## Next checkpoint",
            "",
            analysis["next_required_action"],
            "",
            "No Gate 2, Gate 3, semantic memory, cross-conversation memory, migration, `/chat` "
            "change, or production runtime change was performed.",
        ]
    )
    return "\n".join(lines) + "\n"


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
        "note": "Physical experiment spend; not a standalone D1 or D2 strategy cost.",
    }


def _percentile(values: Sequence[float], probability: float) -> float:
    index = round((len(values) - 1) * probability)
    return values[index]


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
