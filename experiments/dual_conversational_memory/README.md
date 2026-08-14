# ORQ-29 offline development laboratory

This package implements only the operator-authorized authoring and development
calibration surface for ORQ-29 Gate 1. It does not integrate conversational
memory into the application, and it does not create, locate, hash, or inspect a
held-out dataset.

The frozen manifest is `development-manifest.json`. It fixes the synthetic data
shape, candidate space, selection order, models, prices, one-repetition policy,
and hard external-call ceilings. The generated `data/dataset-manifest.json`
binds the authoring and development files to that manifest. All data is
synthetic.

## Safe validation

The default runner mode performs no external calls:

```bash
python -m experiments.dual_conversational_memory.build_dataset
python -m experiments.dual_conversational_memory.run_development
pytest -q tests/experiments/test_dual_conversational_memory_protocol.py \
  tests/experiments/test_dual_conversational_memory_core.py
```

## Single authorized development execution

The external mode is single-use:

```bash
python -m experiments.dual_conversational_memory.run_development --execute-external
```

Before the first external call it creates a local reservation, fetches
`origin`, and proves that the required refs match the frozen commit. Every call
is written to an append-only ledger before dispatch and receives one terminal
record. There are no automatic retries. An exhausted limit, unknown outcome,
trace mismatch, or external failure makes development invalid and prevents
compensating calls.

The ledger distinguishes physical execution from the logical cost of an
independent arm. A physically shared embedding index is charged in full to each
memory arm that would require it. Missing billable usage remains unavailable;
it is never replaced with zero.

## Boundary

The resulting report is unblinded development calibration. It is not the final
pre-registration, a Gate 1 verdict, permission to access held-out data, or
authorization for Gate 2, Gate 3, production code, migrations, or runtime
memory.
