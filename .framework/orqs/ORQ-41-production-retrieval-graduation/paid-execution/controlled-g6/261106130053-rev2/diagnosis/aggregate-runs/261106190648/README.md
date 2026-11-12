# Execution update

Operator authorized execution after prospective review. Status: DIAGNOSTIC_AGGREGATE_COMPLETE, executed once: 40/40 functional PASS, 32 measured + eight warmups, paired native payloads/call purposes match. Parent read-only final DB verifier PASS (20 conversations / 424 messages per arm). Distinct final replay review PASS: execution-review/receipt.json. See report.md and execution-review/. Official CONTROLLED_G6_FAIL remains unchanged. The prospective preparation record below is retained as historical context; execution authorization is no longer pending.

# Bounded aggregate preparation diagnostic

Status: DIAGNOSTIC_AGGREGATE_PREPARED_NOT_EXECUTED. Operator authorization covers preparation only. Independent review is complete: DIAGNOSTIC_AGGREGATE_HARNESS_REVIEW_PASS, bound to the exact plan in independent-review.json. Explicit operator execution approval remains pending. See independent-audit/code-review.md for reviewer scope and limits.

Prospective population: 40 local ASGI requests total, 32 measured and eight warmups. Each arm has five requests per EN/ES x JSON/SSE cell (one document warmup plus document, history, combined and empty measured cases). Concurrency is one. Fresh paired conversations/request IDs are frozen in fixtures.json; no official or earlier diagnostic conversation is reused. New databases contain 20 conversations / 384 history messages each, unchanged P3 corpus content, identical business and schema hashes. Fixture provisioning has completed; no /chat request has been executed.

Same pinned C0/C1 images, PostgreSQL image, configuration semantics and 2 CPU / 2 GiB resources as the prior controlled experiment. New database/cache namespaces have their own effective config identities. Model and thresholds are unchanged; all model/embedding/reranker responses remain local memory-only stubs. P2 topology has PostgreSQL network none and no port bindings; execution workers must share that isolated namespace. No external credentials or dotenv are introduced.

The diagnostic worker is a separate copy of the original controlled worker with four measured cases/one warmup per cell and aggregate CPU readings. The original controlled worker/controller, fine profiler, Capture, provider scopes, SDK hooks, application and P5 are unchanged. The worker preserves existing payload/call parity, request identity, candidate context/dispatch validation, HTTP JSON/SSE validation, deadline and cleanup controls.

Clock boundaries: monotonic wall then process CPU at ASGI ingress; process CPU then monotonic wall at native send wrapper entry. Only primary send readings settle the interval. Rewrite send readings are discarded. The primary timestamp precedes body/hash/capture bookkeeping; rewrite bookkeeping is retained inside the interval. No per-function, SQL, logging or SDK profiling wrappers are installed. Process CPU includes all threads/background activity in the worker process, can exceed elapsed wall time under parallel execution, and cannot be subtracted from wall time to infer database wait. Neither clock measures per-stage causal cost. Clock read overhead is retained, never subtracted.

No gate statistic or PASS threshold is produced from this diagnostic. Inspect paired raw process CPU and wall distributions by category/cell descriptively. Do not correct the historical p95 or select a favorable repetition. Small sample size and host scheduling remain limitations. The official CONTROLLED_G6_FAIL and paid-admission block remain unchanged.

Execution is fail closed on missing independent review, source/config/data drift, existing execution-started barrier, invalid response/evidence or worker failure. No automatic resend/restart. An unresolved attempt preserves all evidence and requires operator review. The review receipt must bind plan_sha256 with status DIAGNOSTIC_AGGREGATE_HARNESS_REVIEW_PASS before --execute can admit requests. The command is documented for later authorization, not invoked:

python -m experiments.production_graduation.gate_validation.controlled_latency_aggregate --execute <this-directory>

Independent review must verify exact sample population and fresh identities, corpus/RLS and database projections, clock order and timing boundaries, retained Capture/SDK/accounting behavior, deadline/cleanup/no-resend handling, source/config/image/resource pins, P2 constraints and no claim of gate graduation.
