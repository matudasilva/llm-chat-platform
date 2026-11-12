# Synthetic adapter focused revalidation — 2026-11-12

The two requested suites passed under P2 before changes: **24 passed in 0.12s**.
The historical 11-test result does not cover the current preparation/bootstrap
changes. This record supplements the historical Validation section in
`implementation.md` without replacing its prior evidence.

Only `tests/experiments/test_orq41_synthetic_bootstrap.py` was changed in this
continuation. A parametrized subprocess test copies the worker or controller,
bootstrap, and exact reviewed core bytes into a temporary directory, then loads
the adjacent core with `python -I -B`, an empty environment, and a temporary
working directory. It verifies the expected digest and absence of `experiments`
imports. No adapter correction was needed.

After this addition, both focused suites passed: **26 passed in 0.18s**.
The exact command, source hashes, and independent review result are recorded in
`revalidation.json`; `revalidation-p2.xml` is an exact copy of the final JUnit
output emitted at `/tmp/orq41-synthetic-current-p2.xml`.

The command retained the absolute P2 guard path, empty environment, disabled
credential paths and metadata access, and empty network namespace from the
specified Validation command. The P2 audit log was absent after both runs.
Isolated `-I` subprocesses ignore PYTHONPATH, so their protection is the inherited
empty network namespace, not Python guard injection. These tests execute only
local bootstrap/guard checks and do not attempt socket or provider calls.

Independent read-only review by `/root/synthetic_review` (gpt-6-luna) covered the
four synthetic adapter modules and both focused test files, including the new
test. It reported no actionable findings within the preparation-only claims;
it did not execute tests or modify files.

Actual image/interpreter availability, real container PID1, Unix namespace and
socket integration, and installer execution remain unvalidated. Successful
isolated loading resolves only the offline adjacent-core import check.

No `app/`, P5, or reviewed lifecycle source was edited. No host/service operation,
Docker, provisioning, egress/provider call, benchmark/campaign, Notion operation,
or commit was performed. Existing unrelated working-tree changes were preserved.
**G6 remains FAIL; paid execution remains BLOCKED.** No staging authorization or
ORQ closure is implied by this focused offline result.
