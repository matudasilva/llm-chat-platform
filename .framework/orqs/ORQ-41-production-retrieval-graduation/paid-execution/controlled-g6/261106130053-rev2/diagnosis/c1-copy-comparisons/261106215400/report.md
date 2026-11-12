# Direct old/new C1 comparison execution

C1_COPY_COMPARISON_COMPLETE. One operator-authorized 40-request local comparison after prospective independent review. All functional/evidence checks passed: 32 measured plus eight warmups, 40 unique valid closed candidate contexts, paired serialized rewrite/primary payloads and call-purpose parity. Both arms used full C1 Capture, application/SDK attempt tracking and invocation/accounting validation. No baseline C0 tape arm or disabled observer was used.

Image old: sha256:7417a2af20101903f3fc9326af26da074eec6dd3b90987b5b5f74c1986a58d06.
Image optimized: sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707.

Image inventories bind the only app difference to the approved context_evidence.py window-copy change. Both images share dependencies and effective configuration apart from fresh disposable DB names. Same pinned PostgreSQL/P3 corpus, 2 CPU/2 GiB limits, local provider/embedding/reranker stubs, synthetic fixture content and aggregate process-CPU/monotonic wall boundaries. Fresh matched UUIDs are shared across separate old/new DBs, disjoint from previous runs. Full JSON/SSE completion, identity, cleanup, deadline and candidate evidence validation remained active.

The final prospective arm order was counterbalanced across both language and protocol marginals: old first for EN JSON and ES SSE, optimized first for EN SSE and ES JSON. The initial order and its verification artifacts were retained before the refinement; no request had executed. Final plan/review binds the refined order and the prespecified analyzer. This is fixed counterbalancing, not randomized within-pair crossover. Each worker has a document warmup; no retry, selection of a favorable repetition or automatic resend occurred.

The table reports signed optimized-minus-old differences; negative favors optimized. CPU is aggregate process CPU, not per-function attribution or external provider time. Wall is ASGI ingress to primary native-send entry, not full-response/TTFT latency.

| Category | Pairs | Median CPU delta (ms) | CPU range (ms) | Optimized lower CPU | Median wall delta (ms) |
|---|---:|---:|---:|---:|---:|
| document | 4 | -0.078 | -0.888 to 3.480 | 2/4 | -1.697 |
| history | 4 | -2.118 | -5.886 to 3.436 | 3/4 | -2.922 |
| combined | 4 | -3.349 | -5.036 to -1.701 | 4/4 | -6.150 |
| empty | 4 | -2.969 | -5.526 to -1.614 | 4/4 | -3.078 |

Across all 16 measured pairs: median CPU delta -1.878 ms, optimized lower in 13/16; median wall delta -3.823 ms, optimized lower in 14/16. These are paired medians, not differences of arm medians.

Order strata: optimized CPU is lower in 5/8 pairs when old ran first and 8/8 when optimized ran first. Both strata have negative median CPU deltas; exact ranges/sign counts and per-cell/pair values remain in analysis.json. There is a favorable signal, especially combined cases, but category/cell interactions, host load, scheduling, allocator/GC and process background activity remain possible contributors. Empty cases also show multi-ms improvements although the copy change has little expected work there; this is evidence against assigning all observed gains to the patch. Do not estimate database wait as wall minus CPU.

The copy microbenchmark and this request comparison use different scopes; no subtraction or extrapolation is justified. Four pairs per category in one fixed-order experiment do not establish a stable gain or the +5% G6 p95 margin. Document/history include unfavorable pairs; overall ranges cross zero. The supported conclusion is favorable diagnostic observations with uncertain magnitude and causality, not a uniform gate-level performance PASS. No new performance threshold has been invented, and no official p95 is corrected or replaced. This test alone does not justify lifting the paid-admission block.

P2: workers share network-none PostgreSQL namespace, no published ports, no external provider credentials or global dotenv, local memory-only native transports and P2 network guard. Network audit is absent/empty. Forty real local API requests ran; external/provider calls and paid spend are zero. Only new isolated experiment/test modules and evidence were added; app/runtime, P5, schema/grants, model, thresholds, accounting and provider/retry behavior were not changed during this comparison. No paid campaign, Notion or commits.

Commands: receipt_copy_comparison module for preparation and --execute <this packet> once in a credential-scrubbed environment; python3 analyze.py offline; read-only prepared/final DB verifiers with --run <this packet>. Author P2 controls32/32 PASS; independent prospective controls4/4 PASS. Source/fixture/image/config/analysis identities, review bindings, all eight raw receipts and logs are retained. Final PostgreSQL verifier and distinct execution review are recorded separately; their PASS is not inferred from the worker result.

Official CONTROLLED_G6_FAIL remains unchanged. Retain the reviewed optimization as a correctness-preserving candidate; no additional runtime tuning or formal N100 rerun is executed by this comparison. A formal gate on any candidate requires its own frozen source/image/config/fixture population and independent review; small diagnostic medians cannot certify that outcome.

Parent-executed final read-only PostgreSQL verifier PASS: 20 conversations and 424 messages per arm, original 384 messages exact, one new exchange per conversation, unique generated UUIDs normalized only for paired equality. P3 content, RLS, schema and effective configuration unchanged. Source/receipt retained in execution-review/; distinct reviewer attribution is recorded separately.
