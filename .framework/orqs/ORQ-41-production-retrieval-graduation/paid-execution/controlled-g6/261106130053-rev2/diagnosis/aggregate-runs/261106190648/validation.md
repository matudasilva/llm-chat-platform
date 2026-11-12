# Preparation validation

28/28 deterministic tests PASS under unshare -rn with env -i, empty HOME, nonexistent AWS config/credentials, metadata disabled, empty application dotenv path, P2 socket guard and empty network audit. Tests cover fresh bounded paired populations, denial before review/admission, rejection of official gate plans, primary timestamp preceding capture and rewrite preservation, plus existing controlled-G6 invariants. JUnit: tests.xml.

Validation command (with the recorded scrubbed P2 environment):

.venv/bin/python -m pytest -q tests/experiments/test_orq41_controlled_latency_aggregate.py tests/experiments/test_orq41_controlled_latency.py --junitxml=/tmp/orq41-aggregate-tests.xml

Preparation command (scrubbed host environment, local Docker access):

.venv/bin/python -m experiments.production_graduation.gate_validation.controlled_latency_aggregate

Preparation used existing local images with --pull=never / network none for config inspection and local PostgreSQL only. Both databases have 20 conversations / 384 messages, matching business/schema projections and original P3 content SHA-256. See preparation.json. No API requests, external/provider calls, diagnostic execution, paid spend, gate rerun, Notion or commits.

This is author validation, not an independent review. Corpus identity/count evidence is recorded; a separate read-only fixture/RLS review remains required before execution. The executable source/fixture/plan hashes are checked against preparation.json; no execution-started.json exists.
