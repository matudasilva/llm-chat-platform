# ORQ-27 Gate 1 development calibration report

**Status:** AWAITING_OPERATOR_PREREGISTRATION_APPROVAL

Gate 1 development/calibration only; no held-out result and no GO/STOP verdict

## Reproducibility

- Source run: `experiments/conversational_memory/runs/development-2026-08-12T204950.323380+0000-84945e5b-a377-4c0c-bdd5-201917b29dff.json`
- Source run SHA-256: `161110e23fc3e40e6c2d2c7d6e37ca061061d3b133116f82a2c2ff24e14e96f1`
- Run ID: `84945e5b-a377-4c0c-bdd5-201917b29dff`
- Registration SHA-256: `b43ab57df779de2a631be64c5564bf2a794632f7555437b2e01a100710a95354`
- Development dataset SHA-256: `c4e0864aecf4585a01a31bf6915c2426d9c76024339f475dcd6df3caec1f8c1b`
- Held-out inspected: `false`

## Development result

| Arm | Recall accuracy | Fact consistency | Mean logical API cost / conversation | p95 latency ms | p95 TTFT ms |
|---|---:|---:|---:|---:|---:|
| A | 0.0000 | 0.0000 | 0.00030120 | 2743.25 | 2361.07 |
| B | 0.9167 | 0.8333 | 0.00076104 | 2381.00 | 1928.08 |
| C | 0.2917 | 0.2500 | 0.00037568 | 1814.35 | 1497.85 |
| D1 | 0.6250 | 0.5833 | 0.00060711 | 1575.85 | 1221.45 |
| D2 | 0.6250 | 0.5833 | 0.00062329 | 2396.05 | 1908.84 |

Selected retrieval candidate proposal: `{"chunk_max_chars": 1000, "chunk_overlap_chars": 0, "recent_window_max_messages": 2, "retrieval_top_k_chunks": 6, "similarity_threshold": 0.2}`.

Selected primary query proposal: **D1**. D1 and D2 tied on answer recall and fact consistency. D1 used fewer input/query tokens, lower logical API cost, lower irrelevant/superseded/amplified retrieval, and better p95 latency/TTFT. D2's better delivered-source recall did not improve the development answer score.

| Retrieval metric | D1 | D2 |
|---|---:|---:|
| precision_at_k | 0.3333 | 0.3125 |
| recall_at_k | 0.3333 | 0.3125 |
| mrr | 0.3333 | 0.4167 |
| delivered_unique_source_recall | 0.6458 | 0.7708 |
| irrelevant_memory_injection_rate | 0.7653 | 0.7431 |
| duplicate_chunk_slot_rate | 0.0674 | 0.0903 |
| superseded_fact_retrieval_rate | 0.1111 | 0.1458 |
| repeated_source_amplification_rate | 0.2143 | 0.4286 |

## Interpretation before held-out

- D1 improved recall accuracy over C by 0.3333 absolute, but remained 0.2917 below B.
- D1 reduced mean logical API cost versus B by 20.23%.
- D1 ambiguous-follow-up recall accuracy was 0.0000; this is the strongest development warning.
- Tenant/conversation isolation failures: `0`.
- Reducing tokens remains an operational-efficiency proxy, not evidence of lower energy or CO2e.

## Proposed frozen decision contract (operator approval required)

The proposal is machine-readable in `development-analysis.json`. Key choices are D1, three held-out generation repetitions, paired step-level comparison, fixed-seed paired bootstrap, and conjunctive quality/cost/safety thresholds. No threshold is approved by this report.

Development warning: Under the proposed thresholds, development would miss the B-quality-loss limit and the ambiguous-follow-up floor. This is a warning, not a held-out STOP verdict.

## Recorded discrepancy

The unchanged production OpenAI Responses serializer returned HTTP 400 on the first assistant-history replay because it encodes every role as input_text. Gate 1 uses an experiment-only string-content ProviderPort adapter. Any Gate 2 OpenAI history path therefore requires separate design review; production was not changed.

The raw run's observed_execution summary included earlier ledger runs. The runner is now fixed to filter by run_id; observed_execution_current_run is the corrected view. Raw evidence remains append-only and was not overwritten.

## Next checkpoint

Operator approves or revises the frozen parameters, D1 selection, repetitions, thresholds, and paired rule; then the registration is signed and committed before held-out execution.

No Gate 2, Gate 3, semantic memory, cross-conversation memory, migration, `/chat` change, or production runtime change was performed.
