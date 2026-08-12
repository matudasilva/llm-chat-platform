# ORQ-27 Gate 1 held-out report

**Verdict:** NO_GO

ORQ-27 Gate 1 offline experiment only; no runtime, Gate 2, Gate 3, or semantic-memory authorization

## Reproducibility

- Source run: `experiments/conversational_memory/runs/heldout-2026-08-12T224320.447316+0000-99ab1c40-9ca4-4029-b23e-c50bc012fa37.json`
- Source run SHA-256: `17aeb473088b33ea215cdd8e02c67a31cfe298f8b5e8ca05bb22c49c27b7234a`
- Run ID: `99ab1c40-9ca4-4029-b23e-c50bc012fa37`
- Instrument commit: `c6ddbe630dfa47279b44d5904ecece53c18c6d4f`
- Registration SHA-256: `1a28938563d21413fd80b2e33b2ff43ad019f396ff15a82fc7004a19fba85edd`
- Held-out dataset SHA-256: `ea6bbcc631451758f18640073a5cc04aabafa9ef5ea8ffb5269150a7fa55a64f`
- Attempt ledger SHA-256: `27dcab4f854b25122f026887e49fc31ab8f1777426de07a8ee894ff044876c35`
- Attempt: `1`; replacement used: `false`
- Clauses passed: `16/20`

## Primary result

| Arm | Recall | Fact consistency | Mean logical API cost/conversation |
|---|---:|---:|---:|
| A | 0.0000 | 0.0000 | $0.00030175 |
| B | 0.9306 | 0.9306 | $0.00076111 |
| C | 0.2917 | 0.2917 | $0.00037784 |
| D1 | 0.6389 | 0.6389 | $0.00047856 |
| D2_JSON | 0.3333 | 0.3333 | $0.00048201 |
| D2_TEXT | 0.6806 | 0.6806 | $0.00049217 |

The registered primary arm was `D1`. It improved recall over C by 0.3472, with a one-sided clustered 95% lower bound of 0.3333. It reduced logical API cost versus B by 37.12%.

## Failed conjunctive clauses

| Clause | Value | Required | Evaluation |
|---|---:|---:|---|
| `maximum_d_below_b_recall_loss` | 0.29166666666666674 | <= 0.15 | unrounded point/registered guard |
| `maximum_d_below_b_fact_consistency_loss` | 0.29166666666666674 | <= 0.15 | unrounded point/registered guard |
| `minimum_ambiguous_followup_recall_accuracy` | 0.0 | >= 0.5 | unrounded point/registered guard |
| `maximum_p95_ttft_regression_ms` | 361.524336534786 | <= 300 | unrounded point/registered guard |

## Execution integrity and cost

- API calls: `433` succeeded, `0` failed, `0` unknown.
- Required generation usage missing: `0`.
- Tenant/conversation isolation failures: `0`.
- Estimated physical embedding cost: `$0.00024748`.
- Generation cost from actual usage: `$0.02119290`.
- Total estimated physical API cost: `$0.02144038`.

## Decision

The selected D1 strategy improved recall and consistency over the recent-window baseline and reduced logical API cost versus bounded history replay, but it failed the registered quality-preservation, ambiguous-follow-up, and p95 TTFT clauses. The conjunctive Gate 1 decision is therefore NO_GO, so ORQ-27 stops before Gate 2.

D2_JSON and D2_TEXT remain diagnostic. Their held-out results cannot replace the development-selected D1 arm or rescue NO_GO under the frozen registration.

Do not implement Gate 2 or Gate 3. Any new query or memory design requires a new operator-approved hypothesis and pre-registration; this held-out cannot be rerun.
