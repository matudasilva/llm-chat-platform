# Balanced A/A execution interrupted before the first request

**BLOCKED_AA_EXECUTION_INCOMPLETE_STARTUP_FAILURE**.
Independent disposition: **BLOCKED_AA_EXECUTION_INDEPENDENT_REVIEW_FINDINGS**.
The operator authorized one local-stub A/A against exact plan
`ae37ecfb95379e52c8feff53fedfaabb83a99b2b3b6a7d61521cd58aaa7177bc`.
The controller admitted its first worker once; it exited1 before app lifespan
or run_block. No request, warmup, measured sample, provider invocation or paid
operation occurred. There is no valid calibration outcome or p95 to report.
Do not classify this incomplete attempt as AA_CALIBRATION_FAIL or G6 PASS.

## Observed failure and independent reproduction

**BLOCKED-AA-R1 — MEDIUM**, blocked_latency_worker.py:131-132. The worker calls
install with `orq41:g123:261109141719:c0-EN-json-b0:`. Shared
local_api.NamespacedRedis accepts only
`orq41:g123:[a-z0-9]{8,20}:c[01]:`. The compound arm/cell/block key cannot occupy
the final arm component. The real traceback ends at local_api.py:149-150 with
HarnessError('invalid run cache namespace'). app.router.lifespan_context and
run_block have not been entered. This is a harness integration defect, not an
observed evaluator/retrieval/provider/SSE/application behavior regression.

Parent reproduce_startup.py constructs all32 actual planned names and invokes
the existing real NamespacedRedis constructor with a None client. All32 fail
before a Redis operation. A counterfactual compact run/cell/block token followed
by the actual arm yields32 unique accepted names. That is a format check only;
no worker fix, Redis call, startup trial or performance run was implemented.
The distinct reviewer independently reproduced all32 rejections under P2.

The prior source/packet reviews and unit tests missed this main-to-install
handoff. The synthetic actual-loop tests exercised run_block after installation,
so their passing results did not establish startup compatibility. Earlier review
receipts/test results remain retained as historical evidence, not rewritten.

Smallest proposed remediation: correct only the new worker's namespace encoding
to preserve the shared validator's existing contract and per-cell/block/arm
uniqueness; add a regression through the actual namespace constructor and the
real startup/install call site. For example the run token can be
`{run_id}b{cell_index}{block}` with final component `{arm}`. Do not relax
NamespacedRedis or modify app/, provider behavior, cache TTL/policy or thresholds.
Implementation requires the next scoped approval. The corrected source needs
new pins/fresh packet and review before any new execution; this attempt is
not resumable and its markers must remain.

**BLOCKED-AA-R2 — LOW**, blocked_latency.py:662 and shared controller helper:24.
The automatic worker log saved stdout only; Docker CLI stderr contained the
Python traceback. The full stdout and stderr were recovered separately and
retained without overwriting the original c0-EN-json-b0.log. The helper's
stdout equals that original log. No false PASS or automatic resend occurred.
Optional future hardening is harness-local stdout+stderr retention with tests;
do not change the shared helper/runtime silently. No fix was applied here.

## STOP, data and durability evidence

The parent controller exited1 on the first worker's nonzero exit status. It
did not create/admit another worker. The single global execution-start marker
and c0-EN-json-b0-started marker remain. No worker result, result.json or
calibration samples exist. No marker, identity or data was reset to allow retry.

Parent read-only post-failure verification exactly equals the prepared proof:
both databases still contain720conversations and17,280original history messages
with unchanged UUID/content/tenant/sequence/corpus/RLS/schema/locale projection.
usage_events and rag_request_metrics each have0rows in each disposable database.
These rows alone would not prove absence of an external call; here the failure
location before lifespan/request dispatch, memory-native transports and P2
isolation additionally support0application/provider operations. The reviewer
inspected the proof/source and attributed SQL execution to the parent.

Only this attempt's three preparation services were stopped after that proof.
All containers, volumes, databases, stdout/stderr and markers were retained;
the source PostgreSQL remains running with the same identity. Worker had already
exited; no in-flight request cancellation or unsupported provider cancellation
was performed. cleanup.json records sanitized before/after state.

All500 pre-existing app/experiment/test/global-env files and exact approved
harness/support hashes are unchanged. No source correction, app/P5/runtime/
provider/retry/retrieval/SSE/persistence/model/threshold/accounting/schema/grant/
global-env or host-policy change. No new image, dependency, G9, Notion, commit,
push or deployment. No paid campaign was started.

## Review, cost and disposition

Independent review confirms one failed worker,0requests/0warmups/0measurements,
the reproducible MEDIUM integration defect, LOW diagnostic gap and conservative
STOP/no-resend behavior. Source and prepared-review PASS do not certify this
startup path after the newly observed finding. Exact receipts and raw logs are
bound in independent-review.json. No fresh broad pytest was run because this
stage authorized one experiment, not code remediation; pure diagnosis used P2.

External/provider calls and spend:0 / USD0. Campaign hard capUSD5 and effective
boundUSD4.15355688 remain unchanged. Global In Progress / Implement /
DECISION_FREEZE_PASS is preserved; official CONTROLLED_G6_FAIL and
BLOCKED_CONTROLLED_G6_FAIL paid admission remain. All previous measured AA/G6
FAILs remain. Next action is scoped harness startup remediation/tests/review,
then a fresh approved executable packet. No automatic repetition or paid action.

