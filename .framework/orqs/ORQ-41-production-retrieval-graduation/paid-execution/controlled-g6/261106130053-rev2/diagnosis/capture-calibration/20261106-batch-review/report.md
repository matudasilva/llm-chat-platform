# Rewrite capture calibration

Status: CAPTURE_CALIBRATION_COMPLETE_NOT_A_GATE.

The G6 interval starts at ASGI ingress and ends at primary native-send entry, before primary Capture processing. Rewrite Capture processing is inside that interval. JSON/SSE response parsing and final candidate validation are outside the reported preparation interval.

This diagnostic reconstructs the 400 measured original rewrite fixture inputs using the adapter payload builder and botocore local Converse serializer. No SDK client is created. The reconstructed bodies are retained in inputs.json; they are not claimed to be the retained historical wire bytes. Nine batches of 400 sends per arm follow one warm-up batch, with rotating/reversed arm order. Clocks surround complete sent loops only. Hashes, independent expected text receipts, raw bytes, dispatch ordering, observer reconciliation and chain/cap validation execute after the clocks.

| Arm | Median CPU per send (microseconds) | CPU batch range per send (microseconds) |
|---|---:|---:|
| tape | 0.793 | 0.745–0.848 |
| capture_passive | 12.389 | 11.923–13.013 |
| capture_active | 31.957 | 31.833–35.820 |

Active Capture minus Tape is approximately 31.164 microseconds (0.03116 ms) per rewrite send in this calibration. This confirms asymmetric harness work but supplies no evidence that deferring Capture would close the 3.09–5.21 ms historical threshold excess. No cost is subtracted from p95. The result does not invalidate or replace CONTROLLED_G6_FAIL.

Limitations: current local interpreter/host rather than original pinned source-container resources; one evidence state per batch rather than per request; lifecycle construction/finalization is outside the clocks; no scopes/SDK hooks or whole request is timed. These are aggregate means over batches, not request p95 estimates. Earlier fine-wrapper profile values are not directly comparable or calibratable using these results.

P2: unshare -rn, env -i, empty HOME, absent provider credentials/config, metadata disabled, empty application dotenv path and P2 network guard. Network audit is empty. API requests, database queries, provider calls and paid spend are zero. No app, P5, production harness or threshold edits were made.

Next recommended diagnostic: bounded paired C0/C1 preparation measurements on fresh local disposable DB fixtures using only aggregate process CPU and monotonic wall timestamps at ASGI ingress and primary send. Preserve original candidate accounting and transport capture, avoid per-function wrappers, and freeze the sample count/order before execution. This would distinguish additional process CPU from wall-time variation before proposing a runtime fix. New local ASGI execution requires its own reviewed prospective manifest; it is not authorized or executed by this calibration.
