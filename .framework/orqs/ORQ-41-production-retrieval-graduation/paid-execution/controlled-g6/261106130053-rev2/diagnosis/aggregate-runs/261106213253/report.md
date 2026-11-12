# Optimized C1 image diagnostic

DIAGNOSTIC_AGGREGATE_COMPLETE. Executed once after operator authorization and prospective independent review. This is a 40-request diagnostic (32 measured/eight warmups), not an N100 G6 gate or paid campaign.

New C1 image: sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707. Its parent is sha256:7417a2af20101903f3fc9326af26da074eec6dd3b90987b5b5f74c1986a58d06. Offline classic Docker build used pull=false and network none, one COPY, no RUN/install/download. Full app inventories differ only in core/observability/context_evidence.py, matching reviewed source SHA32490a738e58d2499b6f3a2bac9ee961f6d060a486830752d7b5207b5398ba20. Dependencies and other app files are inherited unchanged. The new image passed 49 focused P2 tests before execution; see receipt-copy-proposal/implementation/image-pin/.

Same C0 image, resources2CPU/2GiB, local memory-only native generation/embedding/reranker stubs, aggregate clocks and unchanged capture/SDK/accounting checks. Fresh namespaces and paired UUIDs were provisioned in new disposable DBs. The explicit prospective image amendment and its initial preparation artifacts are retained. The approved manifest binds image and source-inventory receipts.

All40 local API requests passed functional/identity/deadline/cleanup validation. Paired native rewrite/primary serialized body hashes and call purposes match;20 distinct C1 accounting contexts remained valid/closed. No resend. Monotonic wall spans ASGI ingress to primary native-send entry; aggregate process CPU covers all worker threads in the inner clock interval. Existing rewrite Capture work remains inside the interval; primary Capture work/response parsing/final snapshot checks remain after the endpoint. No fine function/SQL/logging/SDK profiling wrappers were installed.

| Category | Median paired C1-C0 CPU (ms) | Median paired C1-C0 wall (ms) | Previous-run CPU delta (ms) | Previous-run wall delta (ms) |
|---|---:|---:|---:|---:|
| document | 1.823 | 1.103 | 2.827 | 1.932 |
| history | 4.610 | 4.176 | 3.672 | 3.617 |
| combined | 7.319 | 6.890 | 8.514 | 9.557 |
| empty | 4.135 | 3.801 | 1.346 | 1.415 |

Interpretation: this small diagnostic does not show uniform improvement. Document/combined paired deltas are lower than in the previous run, while history/empty are higher. This is not a randomized same-run old-C1/new-C1 comparison: fresh identities, host timing, scheduling, allocation and background activity differ. No difference may be assigned causally to the copy optimization, converted into a p95 correction or used to claim a gate PASS. Each category has only four measured pairs across language/path cells. Process CPU cannot be subtracted from elapsed wall to estimate DB wait. Additional candidate CPU remains evident in this run, especially combined/history; exact function-level causes are not measured here.

Network/P2: workers share the pinned network-none PostgreSQL namespace without published ports, with P2 guard and no external provider credentials/global dotenv. Network audit is absent/empty; external/provider calls zero, paid spend USD0. PostgreSQL reads/writes are local disposable fixtures only. No additional runtime/harness edits, model/threshold/accounting changes, Notion, commits or paid requests occurred during image pinning and measurement.

Evidence: plan.json, preparation.json, independent-review.json, execution-started.json, result.json, eight c0/c1 raw JSON/logs, analysis.json/analyze.py and execution-review/. The image pin/whole-app inventories/build log/49test JUnit are retained in receipt-copy-proposal/implementation/image-pin/. Final read-only database verification and distinct execution-review receipts are recorded separately; do not infer their PASS from this report.

Commands: scrubbed-environment python -m experiments.production_graduation.gate_validation.controlled_latency_aggregate (prepare); prospective manifest image amendment; readonly fixture/config verifier; same module --execute <run> once; python3 analyze.py; execution-review/verify_final_databases.py --run <run>. No new statistical gate is evaluated. CONTROLLED_G6_FAIL and paid-admission block remain unchanged. Further optimization or an official controlled G6 run requires its own supported proposal and prospective review; the copy microbenchmark alone is not sufficient.

Parent final read-only PostgreSQL verifier PASS: 20 conversations /424 messages per arm, exact original384history messages, one new user/assistant exchange per conversation, generatedUUID-only paired normalization, P3/RLS/schema/config unchanged. Verifier source and receipt retained in execution-review/. Parent executed; separate reviewer attribution remains distinct.
