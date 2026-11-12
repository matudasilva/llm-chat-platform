# Prospective wait/GC diagnostic

DIAGNOSTIC_WAITS_PREPARED_NOT_EXECUTED. Not an official G6 gate.

Forty serial local requests: 32 measured plus eight separate document warmups. Each language/protocol/source cell contains two combined and two empty measured cases. Fresh paired request/conversation UUIDs and separate databases; frozen P3 corpus. Source order is counterbalanced across language and protocol: C0 first for EN JSON and ES SSE; C1 first for EN SSE and ES JSON. One attempt, no automatic resend or favorable repetition. The existing official G6 worker and P5 are unchanged.

The reviewed optimized C1 image and original C0 image, effective settings, native payload/Capture validation, request deadlines and two-CPU/two-GiB limits remain fixed. Before execution the controller requires independent-review.json PASS linked to the exact plan bytes, rechecks all source/support/config/business/schema identities and exclusively records execution-started.json. Partial execution cannot be resumed automatically.

## Measurement and validity

Ingress and native primary-send boundaries retain aggregate process CPU and monotonic wall timestamps. AsyncSession.execute is delegated unchanged with start/stop clocks around the await; these spans include driver execution and rescheduling, not isolated PostgreSQL server time. Existing adapter _call_client is delegated with queued, worker-entered, worker-exited and returned markers. This measures that helper's handoff, not every thread/task in the application. Only shared local diagnostic modules are instrumented; both arms get identical hooks. Full candidate evidence remains mandatory.

GC callbacks record collection start/stop, generation and thread identity. A collection can involve process-global work or another thread; active serial request association is not proof that the request caused it. Context-owner metadata is retained separately. The recorder has a 256-event cap per request. Observer failure/overflow, wrong SQL/SDK owner, missing/duplicate/out-of-order interval or incomplete SDK/SQL coverage invalidates the diagnostic. Functional results/errors are delegated unchanged. SQL/SDK intervals may complete after primary dispatch; retain them and clip to the measurement window during analysis.

Callbacks are attached through response/quiescence, then detached during cleanup; snapshots/independent chain validation occur after the recorded interval tape is closed. Native primary capture bookkeeping remains after the endpoint. No per-helper, per-hash or per-receipt timers are installed. The diagnostic itself adds overhead and cannot correct historical p95.

## Prespecified analysis

First require all 40 functional/identity/payload checks, 20 unique valid candidate contexts, exact arm pairing, bounded complete correlated intervals and empty P2 audit. Then compare signed paired C1-minus-C0 wall and process CPU by category/cell, retaining individual values, medians, ranges and order strata. Only eight measured pairs per category; no performance PASS threshold or stable causal estimate is implied.

Intersect SQL and GC intervals with [ingress, primary dispatch]. Report unions within each category and the cross-category union; do not add overlapping spans. SDK queue segments are queued-to-entered and return segments exited-to-returned; retain thread IDs and distinguish pre/post-boundary portions. CPU counts all process threads. Never use wall minus CPU as a wait estimate or sum process CPU, SQL awaits, GC pauses and SDK intervals. A substantial GC/SQL/handoff association suggests a follow-up hypothesis only; absence of captured overlap does not prove that scheduling had no effect. No percentile substitution, estimated-cost subtraction, gate threshold change, observer disabling or paid readiness claim is allowed.

## Validation and environmental incident

47 controls passed in the exact optimized C1 image under Docker network=none and the P2 socket guard; controls.xml is retained. Both prepared databases independently verified by an adapted read-only verifier executed by parent: 20 conversations/384 history messages, exact fixture UUID/content/order, P3/RLS/schema parity and normalized effective config equality. This is not a distinct-agent attestation.

Host Python 3.13.9 hung during asyncio.run default-executor teardown. A minimal asyncio.to_thread reproduction without this observer also returned its value and then hung. Diagnostic tests were interrupted and repeated in the actual pinned worker Python 3.13.15, where they passed. No assertion or production behavior was changed to bypass the host issue. The image emits the existing pytest-asyncio unset-loop-scope deprecation warning.

No new API requests, provider calls, external egress or spend occurred during preparation. Independent harness/plan review is required before execution. G6 FAIL, paid block, Implement / DECISION_FREEZE_PASS remain unchanged. No app/P5/model/threshold/accounting/DB-schema/global-env change, campaign, Notion or commit.

## Prospective review remediation

Independent review found acceptance of repeated or backwards GC cycles sharing a thread/generation identity. The validator now retains previous cycle start/stop per GC identity and rejects duplicates/backwards intervals while allowing legitimate later cycles. Four regressions were added; 47 controls pass in the pinned image. Initial source/plan/preparation/43-control XML/DB receipt are preserved under initial-review/. No request had executed. Plan/preparation hashes refreshed before read-only re-verification and independent re-review.
