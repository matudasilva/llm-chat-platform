# Paid G6 client measurement readiness — scoped amendment proposal

## Concrete gap

P5 is the reviewed economic admission/STOP harness. LocalAPI.execute consumes SSE token frames but returns only Completion(success,request_id); it retains no timestamp for first content. The approved design requires streaming first-content p95 <=5s, separately from first SSE event. Ledger UTC completion windows, provider total latency, request metrics and total response time cannot reconstruct first-content arrival. No paid sample should be spent before this evidence can be retained. This is a G6 readiness gap, not a reopening of the P5 accounting/STOP closure.

## Minimal proposed implementation, approval required

Add an optional campaign-only observation seam to the existing LocalAPI transport, plus a small file recorder outside app/. Default observation remains disabled for historical callers. The paid caller must enable and pin it before admission.

Capture one monotonic origin before connection/send; timestamp HTTP headers, first SSE event, first nonempty token frame, JSON/SSE validated body completion, and optionally SSE done separately. Observe the existing parser rather than introducing another parser, proxy, HTTP request or provider call. Never infer TTFT from total latency. Record campaign/request/manifest-entry/tenant identity, timestamps and derived durations; non-stream TTFT is null, never zero. No invented timing threshold or confidence claim.

Keep the absolute deadline and post-done full-body validation unchanged. Timestamp in memory on the observed event; fsync the request measurement after transport validation and before returning its completion barrier, avoiding disk I/O in the token arrival path. Missing/contradictory measurement or durability failure must stop admission through the existing FAILED/R_max handling, without resend. Failed/unresolved responses must remain economic failures and cannot be relabeled success by measurement. Measurements do not lower conservative admission charges.

No app/, provider, retry, retrieval, SSE server, schema, grants, model, threshold or accounting changes; no new dependency/framework/control plane. No global logging changes. Existing source identity/hash checks remain in force. Update only campaign harness/tests and scoped evidence/design amendment.

Focused deterministic tests: JSON completion; first SSE event distinct from first content; multiple/empty token frames; full body after done; framing/content-length and deadline failures preserved; missing/failed record -> conservative stop; per-request correlation/tenant and manifest binding; no duplicate request/settlement; independent 168 replay unchanged. All tests under P2 without provider credentials/egress. Independent review required before paid use.

## Other execution readiness

Dedicated fixture DB is prepared separately; its full independent read-only verification is pending. Live provider API/network/config and immutable block pins still need construction and preflight. G6 controlled C1/C0 N=100 per language/path remains a separate free controlled measurement requirement; G123 semantic/fault PASS is not a substitute for that timing population. G7 actual usage is reconciled by a separate post-campaign verifier, never by giving DB/provider credentials to P5. No paid execution has begun.

## Operator approval and implementation

Operator explicitly approved this minimal amendment in conversation. Implemented observer/recorder, strict source pins, pre-admission campaign/manifest recorder binding and paid CLI enforcement. Historical P5 closure is preserved; source-identity/CLI findings from initial validation are retained separately, and scoped re-review is required. The receipt records payload/transport observations only; ledger settlement remains authoritative after deadline, corroboration and cleanup.
