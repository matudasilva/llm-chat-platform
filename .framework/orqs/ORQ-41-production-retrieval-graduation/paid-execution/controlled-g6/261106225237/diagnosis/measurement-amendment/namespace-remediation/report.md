# Namespace startup remediation

**BLOCKED_AA_NAMESPACE_FIX_SOURCE_REVIEW_PASS**. Operator approved correcting
the namespace and advancing. Only blocked_latency_worker.py and its focused
test file changed. The failed261109141719 attempt, data, authorization, start
markers, raw traces and review receipts remain retained and non-resumable.

R1 is resolved in reviewed source: `_cache_namespace` moves cell/block into the
15-character lower-alphanumeric run token `{run_id}b{cell_index}{block}` and
keeps the final component exactly `{arm}`. The actual main/install call uses
that formatter. Every32planned tuple has a distinct valid namespace; another
run has a disjoint set. Shared NamespacedRedis validation, Redis methods/TTL/
cache policy, controller, app and request timing callbacks remain unchanged.

New regressions cover the actual startup bridge, not only run_block. Two fresh
processes call real worker.main -> real install -> real NamespacedRedis under
JSON/c0 and SSE/c1 settings. Only the underlying app lifespan is replaced by a
sentinel which checks installation/actual namespace and stops before any DB/
Redis/provider operation or request admission. run_block is forbidden in that
unit probe. Thus the real installation path is exercised without a deployment.
Full real-PostgreSQL lifespan/performance is not claimed by these unit tests.

Before the source fix both new main/startup tests failed with the exact observed
HarnessError invalid namespace; startup-before.xml retains that expected RED
proof. After the fix both startup probes and the all32namespace constructor/
cross-run isolation check pass; startup-after.xml is3PASS. Full pinned C1-image
network-none/P2 regression is170PASS/0skips/no warnings:80new-harness tests plus
32A/A,23controlled-G6 and35cleanup controls. No performance trial ran.

The distinct reviewer inspected exact two-file diff, genuine installation test
path and RED/GREEN/final XML, ran68pureP2 tests and attributed12native/startup
cases to the parent's qualified image execution. independent-review.md/json
records SOURCE review only, not a new executable-packet review. No new B/H/M.
R2 remains LOW: automatic stdout-only logs require manual stderr recovery on
failure. That separate controller change was not included in the namespace-only
authorization and is not represented as fixed. No shared helper was relaxed.

initial-source/ retains both original files, with exact failed-attempt hashes
25f8.../4b2...; change.patch/source-manifest.json bind current source. All498
other prior app/experiment/test/global-env files are unchanged. No app/P5/
provider/retry/retrieval/SSE/persistence/schema/grant/model/threshold/accounting/
global-env or host-policy change, external/provider call/spend, campaign,G9,
Notion, commit, push or deployment. Source image4e68 and approved1440-request
methodology/5%criterion are unchanged; experimental worker is source-mounted.

Continue with fresh disposable preparation, UUIDs, database names and source
pins plus independent exact-packet review. A new explicit exact-plan execution
authorization is required afterward; the old attempt cannot be restarted.
Global Implement / DECISION_FREEZE_PASS, prior AA/G6 FAILs and paid block remain.

