# C1 window receipt copy implementation

The operator approved the exact revision2 patch. Applied only the private scalar-receipt copy helper and its three window-copy call sites in app/core/observability/context_evidence.py. The fallback remains deepcopy for nested/unexpected/subclass/aliased containers. Snapshot deepcopy, SHA-256/JSON chaining, identities, limits, locking and best-effort behavior remain unchanged. No domain/route/provider/retry/persistence/streaming/P5 change was made.

Exact source proof: reverse the approved patch on a temporary source copy and verify that the resulting SHA-256 equals revision2/result.json source_sha256. Passed; no actual runtime rollback was performed.

New regression file: tests/experiments/test_orq41_c1_receipt_copy.py. Covers full observation-chain equality versus original deepcopy behavior for empty/48-message histories, packing/truncation, limits, abort/builder failures, fast-path isolation, nested/subclass/unexpected fallback, repeated dictionary aliases, cycles, snapshot mutation and copy failure best-effort semantics.

P2 commands: unshare -rn with env -i, empty HOME, nonexistent AWS credentials/config, metadata disabled, empty APP_SETTINGS_ENV_FILE, P2 socket guard and PYTHONDONTWRITEBYTECODE=1. Empty network audit. No campaign or diagnostic requests; native provider tests use local fakes, zero real external/provider calls; USD 0.

Focused command:

.venv/bin/python -m pytest -q tests/experiments/test_orq41_c1_receipt_copy.py tests/experiments/test_orq41_c1_evidence.py --junitxml=/tmp/orq41-copy-implementation/focused.xml

49 passed.

Expanded command:

.venv/bin/python -m pytest -q tests/experiments/test_orq41_c1_findings_remediation.py tests/experiments/test_orq41_c1_transport.py tests/experiments/test_orq41_render_dispatch.py tests/experiments/test_orq41_gate_validation.py tests/core/test_context_packer.py --junitxml=/tmp/orq41-copy-implementation/regression.xml

230 passed. Total author validation 279 passed. JUnit files are retained here. Distinct review evidence is recorded separately; it is not inferred from author tests.

Performance evidence remains the pre-implementation offline microbenchmark only: roughly 0.22 ms per three copies on the reconstructed fixture workload. No new image was built or G6 timing run executed. No claim that this change closes the +5% threshold. Existing pinned images and original diagnostic evidence remain historical, unchanged; a future optimized candidate needs new source/image pins. CONTROLLED_G6_FAIL and paid admission block remain in place. No Notion or commits.

Distinct review completed: C1_RECEIPT_COPY_IMPLEMENTATION_INDEPENDENT_REVIEW_PASS, 54/54 independent P2 checks, no open BLOCKER/HIGH/MEDIUM findings. See independent-review/review.md and receipt.json. This is correctness/evidence review, not G6 performance PASS.
