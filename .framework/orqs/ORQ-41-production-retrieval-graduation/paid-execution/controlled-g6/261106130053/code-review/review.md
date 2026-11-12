# Prospective controlled G6 harness independent review

**CONTROLLED_G6_HARNESS_INDEPENDENT_REVIEW_FINDINGS**. Original frozen plan `9c8a1324ae90c08e2209bf460a7533afe23f022bc48f7800e4dd9d911db45890` remains NOT EXECUTED. All original harness hashes matched when these probes ran. No independent-review PASS authorization file is issued.

## MEDIUM G6-R1 — missing candidate accounting context can pass

`controlled_latency_worker.py:73` rejects only `any(not state.valid for state in lifecycle.evidence_states)`. Empty lists and multiple valid contexts pass. The actual best-effort `context_evidence.request_evidence` yields None if Evidence initialization raises; install.retain appends only non-None state. The functional request/native payload can therefore remain normal while the C1 accounting work is absent and sample receives PASS, potentially certifying artificially reduced preparation overhead.

Independent probe invokes the real context manager with a controlled constructor failure, then evaluates the exact worker AST rejection condition; rejection is false. A second probe confirms duplicate valid contexts also evade rejection. Minimum fix: require exactly one valid, closed candidate accounting state correlated to the current request; reject missing/duplicate/unclosed/wrong identity before sample PASS. Perform validation after the measured primary-dispatch endpoint, preserving the intended timing boundary.

## MEDIUM G6-R2 — ASGI timeout argument does not enforce request deadline

`controlled_latency_worker.py:58` relies on httpx.post(timeout=30) with ASGITransport. The local ASGI transport runs the application coroutine without enforcing that network timeout. Independent no-socket dummy ASGI probe sleeps30ms and still returns204 with timeout1ms. This is not an actual platform request or gate sample. An application coroutine stall can escape the intended request bound and leave the worker active until the controller Docker wait times out.

Minimum fix: explicit outer asyncio deadline around the actual request/response lifecycle using the already accepted operational request limit, followed by bounded quiescence/failure handling. No retry or new gate threshold. Preserve this original plan/source receipt and prospectively amend/refreeze the reviewed code before any gate request; no result-dependent boundary adjustment is allowed.

## Other inspected properties and remaining proof

The frozen population has420 paired sample identities (100 measured plus5 warmups per language/path per arm),800 measured requests/40 warmups total. Each measured category contributes25 samples per cell, input request/conversation IDs are shared across arms and unique across samples, and separate DBs contain equal recorded preparation business/schema hashes and P3 content hashes. Cell arm order is fixed and balanced. Relative nearest-rank p95 compares integers without float tolerance (+5%, including zero-baseline rule); failed/missing/duplicate payload/call populations reject. No best-run choice or absolute live-latency claim is introduced.

Timing endpoint before primary capture.sent bookkeeping is explicit and symmetric; rewrite capture cost before the endpoint is part of the controlled arm difference. It does not certify live latency. Native providers terminate at in-memory SDK transports with no external credentials/network. Existing independent C1/C0 semantic evidence remains supporting evidence; this latency harness still needs corrected per-sample evidence presence validation.

Before enabling execution, independently corroborate all prepared DB fixtures and normalized effective config parity (full config hashes differ because databases differ). Counts and equal hashes alone do not independently establish that both DBs exactly match the frozen fixture plan. A read-only verifier can check all420 conversations/9600 ordered messages per arm, P3/RLS/schema and same effective config excluding only database names. No plan PASS should be issued until these and findings are resolved.

14 pure P2 tests passed:11 original controls plus3 counterexample probes demonstrating the findings. Original probes/XML are preserved here. Reviewer made no source fix, database write, actual platform API call, gate execution, provider/paid/network call or privileged tool request.
