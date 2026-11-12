# Aggregate process CPU/wall diagnostic execution

Status: DIAGNOSTIC_AGGREGATE_COMPLETE. Not an official G6 run or PASS.

Operator-authorized reviewed plan was executed once. Eight cell/arm workers completed 40 local ASGI requests: 32 measured and eight document warmups. All functional checks passed. Paired serialized rewrite/primary payload hashes and call-purpose sequences match; 20 distinct C1 accounting contexts remained valid/closed/correlated. No automatic resends occurred. Raw timestamps, dispatch hashes and request IDs are retained in the eight c0/c1 receipts.

The only diagnostic measurements are aggregate monotonic wall and process CPU timestamps at ASGI ingress and primary native-send entry. Existing evidence/capture/SDK hooks remain active. No fine profiling wrappers or SQL profiling were installed. Primary Capture bookkeeping, response parsing and final snapshot validation are after the endpoint; rewrite capture and earlier preparation remain inside it.

| Category | Measured paired cases | Median paired C1 minus C0 CPU (ms) | Median paired C1 minus C0 elapsed wall (ms) |
|---|---:|---:|---:|
| document | 4 | 2.827 | 1.932 |
| history | 4 | 3.672 | 3.617 |
| combined | 4 | 8.514 | 9.557 |
| empty | 4 | 1.346 | 1.415 |

C1 uses more process CPU in 15/16 measured pairs and more elapsed wall in 13/16. The combined document/history shape has the largest paired median increment in this small diagnostic sample. This supports investigating additional CPU work in the candidate path; attributing the entire difference to database wait or scheduling is unsupported. It does not establish which function causes it, how much belongs to application versus retained harness hooks, or an optimization's effect on the original p95. Process CPU includes all threads/background work and must not be subtracted from wall to estimate waits. Four pairs per category across different language/path cells are descriptive only; the historical controlled G6 failure is unchanged.

Final read-only PostgreSQL verification PASS: 20 conversations and 424 messages per arm, exactly one new user/assistant exchange per conversation, all original 384 history messages preserved with exact UUID/content/order. New generated message UUIDs are unique; only these UUIDs are normalized for paired business equality. Corpus P3 content, RLS, schema and effective configuration remain unchanged. The parent executed the verifier; distinct reviewer attribution is recorded separately and must not be inferred from this report.

P2 workers used pinned images/resources and the network-none PostgreSQL namespace, no port exposure, no external provider credentials, no global dotenv and local memory-only native/embedding/reranker stubs. The network audit is absent/empty. Paid spend USD 0; external/provider calls zero. This is 40 real local API requests with stubbed external integrations, not a live provider campaign. No app/P5/model/threshold/accounting changes, Notion, commits or deployments.

Commands:

- Scrubbed environment: .venv/bin/python -m experiments.production_graduation.gate_validation.controlled_latency_aggregate --execute <this-directory>
- Offline analysis: python3 analyze.py
- Read-only final verification: .venv/bin/python execution-review/verify_final_databases.py --run <this-directory>

Evidence: plan.json, independent-review.json, preparation.json, execution-started.json, result.json, c0/c1 raw JSON and logs, analysis.json/analyze.py, and execution-review/database-final-verification.json. Independent final execution review is recorded separately. Existing source tests (28 author plus five distinct reviewer controls) were unchanged; no additional implementation occurred during execution.

Next proposed work, not implemented: use the combined-history CPU signal and existing source/profile evidence to propose one bounded observational-only improvement to C1 receipt construction/recording, with output/evidence equivalence proof before any app change. Do not promise a +5% result, relax thresholds, correct historical p95, or admit paid requests on this diagnostic alone.
