# Bounded diagnostic profile — not a gate

## Scope and execution

Operator approved the exact profiling-proposal.md. Executed once against fresh diagnostic databases: 40 local ASGI requests (32 measured, eight document warmups), pinned C0/C1 source images and equal 2 CPU / 2 GiB limits. Native Bedrock generation transports, embeddings and reranking stayed in-memory/local stubs. All 40 requests succeeded; paired serialized rewrite/primary body hashes and purpose sequences are identical. All 20 candidate requests retained unique, valid closed accounting contexts and native-dispatch corroboration. No official G6 request, paid fixture or paid database was reused.

Plan SHA-256: `75943c856acd07363ad6529f4ed0e449d6aa061fdcf332a7e23968cd156f230f`. The independent pre-execution review is in independent-review.json. An initial shared-handler double-wrapping defect was corrected idempotently before any API request and covered by regression; Docker's normalized container-network identity assertion was also corrected prospectively. Original receipts and chronology are retained. Neither correction touched app/, P5 or the official gate.

## Observations

The tape retains request, thread, rewrite/primary purpose, before/after primary-send boundary, synchronous inclusive/self wall and thread CPU, call counts, and separate async SQL intervals. There are 7,696 events: 6,712 before primary send and 984 after, with zero crossing the cutoff. Only measured identities are used below; each category has four observations across language/protocol cells.

Median observed **instrumented self CPU**, milliseconds (do not add medians or treat them as uninstrumented causal effects):

| Category | C1 application-side accounting | C1 runtime called by Capture | C1 Capture exclusive | C1 runtime called by scopes | C1 scopes exclusive | C1 SDK hook |
|---|---:|---:|---:|---:|---:|---:|
| Document | 7.859 | 1.080 | 0.261 | 0.927 | 0.911 | 0.034 |
| History | 15.618 | 0.424 | 0.282 | 0.862 | 0.795 | 0.040 |
| Combined | 17.240 | 0.504 | 0.315 | 0.863 | 0.758 | 0.042 |
| Empty | 4.032 | 0.488 | 0.317 | 0.852 | 0.783 | 0.037 |

Baseline Tape exclusive CPU medians are 0.025–0.033 ms. Common payload/render/cap work is retained separately in analysis.json. SQL preparation union-wall medians range from 6.59 to 40.64 ms for C0 and 7.33 to 37.11 ms for C1; these waits are not CPU and are not additive with sync spans.

The candidate performs 5,432 wrapped synchronous calls before primary dispatch in the 16 measured requests. Primary-purpose calls include 1,328 text_receipt, 2,152 digest, and 256 each observe / Evidence.add / Evidence._add / encoded. Rewrite-purpose bookkeeping includes Capture plus its nested runtime calls. Primary Capture processing remains AFTER the endpoint. This confirms location and multiplicity of the observable work; it does not establish a percentage of the original p95 regression.

## Interpretation and limits

This profile narrows the search to C1 receipt construction/recording, especially history/combined paths, while separating the independently measured harness scopes/capture/hooks. It does **not** prove that those instrumented CPU magnitudes are the original runtime overhead. Thousands of fine-grained wrappers add timing/recording overhead which can be charged to parent self time. There is no calibration or subtraction. Four observations per category do not support an inferential gate, and SQL/host/thread scheduling remain distinct sources of wall variation.

No p95 correction, threshold relaxation, observer disabling or original FAIL replacement is allowed. The independently verified `CONTROLLED_G6_FAIL` and paid-admission block remain unchanged. No new official timing run or runtime optimization was performed.

## Validation and retained evidence

- Author P2 tests: 30/30 (seven profiling invariants plus 23 existing controlled-G6 regressions); tests.xml.
- Independent pre-execution controls: 8/8; code-review/final-tests.xml.
- Preparation: 20 conversations / 384 history messages per arm, full P3 corpus hash, equal schema/business projections and RLS; preparation.json and code-review/prepared-databases-verification.json.
- Execution: result.json; eight worker receipts and eight raw profile tapes; logs; immutable plan/fixtures and source hashes.
- Post-execution DB verification and independent attribution review: execution-review/ (recorded separately, never inferred from the controller's success).
- P2 network audit is absent/empty, all worker network namespaces share only the network-none local PostgreSQL namespace, no exposed ports, no provider credentials, external/provider calls zero, paid spend USD 0.

The module-level execution commands are `...controlled_latency_profile` (prepare), `...controlled_latency_profile --execute <this directory>` (single execution with independent receipt), and `python analyze_profile.py` (offline descriptive replay). Exact environment and constraints are frozen in plan/support hashes and review receipts. Do not rerun the execution command: the execution-started barrier rejects resends.

The first independent final-DB verifier rejected equality of newly generated message UUIDs across separate arms. These UUIDs are expected to differ. The reviewer retained that verifier, then normalized only the 40 freshly generated IDs after validating each arm's canonical uniqueness, exact conversation/tenant/order/history, and exact user/assistant suffix. Original 384 history UUIDs remain exact. The corrected read-only verifier passes with 20 conversations / 424 messages per arm, unchanged P3/RLS/schema/configuration and normalized business parity. No request was replayed and no database was modified to make the verifier pass. A CLI invocation missing `--run` also exited at argument parsing before database access; it was corrected without executing an API request.

## Next decision

See next-step-proposal.md. The smallest defensible continuation is aggregate offline CPU replay without the per-hash/per-receipt observer wrappers, followed by an exact, separately approved observational-only optimization if justified. No new API requests or app changes are authorized by this report. Retain the current official G6 FAIL throughout that investigation.
