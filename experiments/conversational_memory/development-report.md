# ORQ-27 Gate 1 final development calibration report

**Status:** AWAITING_OPERATOR_PREREGISTRATION_APPROVAL

Gate 1 final development/calibration iteration only; no held-out result and no GO/STOP verdict

## Reproducibility

- Source run: `experiments/conversational_memory/runs/development-2026-08-12T221254.540786+0000-a619de7a-5532-4fb7-a76b-ea443f2f8b90.json`
- Source run SHA-256: `c9a7aa6afc8f1d47cb38a5bc89724e1bc04e0ffda8ed9b72b754a7218aa24ccd`
- Run ID: `a619de7a-5532-4fb7-a76b-ea443f2f8b90`
- Instrument commit: `bd649718ff04a1b4096feb43a09cdbea5e22f2c3`
- Source-run registration SHA-256: `1c4758143ef3a70c2e978de47a33c0baf4887dfdcbefbd97138b2ca6dc4f0a83`
- Proposed registration SHA-256: `db8eba43a15b3ecc5f05c32c37634af5ba245bc57573e0b00a9f3506923e4097`
- Source registration verified from the instrument commit: `true`
- Development dataset SHA-256: `c4e0864aecf4585a01a31bf6915c2426d9c76024339f475dcd6df3caec1f8c1b`
- Scorer: `nested-forbidden-span-safe-v2`
- Held-out inspected: `false`

## Development result

| Arm | Recall | Consistency | Mean logical API cost/conversation | p95 latency ms | p95 TTFT ms |
|---|---:|---:|---:|---:|---:|
| A | 0.0000 | 0.0000 | 0.00030272 | 2110.90 | 1205.30 |
| B | 0.9583 | 0.9583 | 0.00076144 | 1621.95 | 1184.74 |
| C | 0.2917 | 0.2917 | 0.00037852 | 1950.30 | 1357.31 |
| D1 | 0.6250 | 0.6250 | 0.00047582 | 2253.95 | 1958.80 |
| D2_JSON | 0.3333 | 0.3333 | 0.00047925 | 1640.50 | 1027.26 |
| D2_TEXT | 0.5556 | 0.5556 | 0.00049114 | 2454.30 | 1766.23 |

Selected parameter proposal: `{"chunk_max_chars": 1000, "chunk_overlap_chars": 80, "recent_window_max_messages": 2, "retrieval_top_k_chunks": 6, "similarity_threshold": 0.5}`.

Selected query proposal: **D1**. The predeclared lexicographic rule selected this arm from unrounded development values: consistency=0.625, recall=0.625, ambiguous=0.0, exact_identifier=1.0, logical_cost=0.00047581749999999997.

| Retrieval metric | D1 | D2_JSON | D2_TEXT |
|---|---:|---:|---:|
| precision_at_k | 0.3333 | 0.1250 | 0.4167 |
| recall_at_k | 0.3333 | 0.1250 | 0.4167 |
| mrr | 0.3333 | 0.2292 | 0.5417 |
| delivered_unique_source_recall | 0.6250 | 0.2917 | 0.5833 |
| irrelevant_memory_injection_rate | 0.2361 | 0.3792 | 0.5000 |
| duplicate_chunk_slot_rate | 0.0000 | 0.0208 | 0.0104 |
| superseded_fact_retrieval_rate | 0.0903 | 0.0931 | 0.1042 |
| repeated_source_amplification_rate | 0.0000 | 0.0741 | 0.1190 |

## Proposed held-out contract — operator approval required

Average repetitions within each step, then unrounded step values within each conversation. Resample conversations for a fixed-seed 10,000-sample paired bootstrap and require the one-sided selected-arm-minus-C recall 95 percent lower bound above zero. Small slices use exact point aggregates without intervals. Every quality, cost, latency, retrieval, slice, and safety clause is conjunctive.

Failed development clauses under the proposed held-out margins: `["maximum_d_below_b_recall_loss", "maximum_d_below_b_fact_consistency_loss", "minimum_ambiguous_followup_recall_accuracy", "maximum_p95_latency_regression_ms", "maximum_p95_ttft_regression_ms"]`.

## Recorded production-adapter discrepancy

The unchanged production OpenAI Responses serializer returned HTTP 400 on the first assistant-history replay because it encodes every role as input_text. Gate 1 uses an experiment-only string-content ProviderPort adapter. Any Gate 2 history path requires separate design review and contractual JSON/SSE coverage; production was unchanged.

## Next checkpoint

The operator approves or revises the proposed parameters, selected query variant, margins, repetitions, and clustered paired rule. Only then may registration be signed and committed before a single held-out execution.

No held-out execution, Gate 2, Gate 3, semantic memory, migration, `/chat` change, or production runtime change was performed.
