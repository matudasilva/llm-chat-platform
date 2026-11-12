# Offline aggregate CPU replay (diagnostic only)

Run: 261106172211. Not a gate; no API requests, DB service/query, provider calls, network access, or paid spend.

P3 source archive SHA-256: 0334e3af47edf9c885093a6ad061390f6f85ba62517e56b94450339950599d4f. Offline extraction yielded 2,146 chunk texts totaling 746,554 UTF-8 bytes, maximum 500 characters, matching the frozen corpus manifest. Conversation/history fixtures are the frozen profile fixtures.

Workload: 20 fixture cases across document, history, combined and empty shapes, repeated 20 times per batch (400 request-shaped workloads), five measured batches per arm. It runs the existing C1 evidence helpers through rewrite/primary prompt rendering, source receipts/projection, history reads/bounds/materialization, window packing, final combined cap, prompt mapping and rendered prompts. Retrieval/reranking and DB/API are not called. For document cases, 20 candidates and five sources are reconstructed from real P3 chunk text using deterministic lexical overlap; this is not the original hybrid retrieval ranking. The passive arm omits active request evidence state; it is not the pinned C0 image.

All active/passive rendered outputs matched exactly; receipt hash chains validated, evidence stayed valid, and configured record/byte limits were enforced. Measurements wrap whole batches with thread CPU and monotonic wall clocks; no per-operation profiler wrappers were used. They describe only this offline workload and cannot be converted into an end-to-end p95 correction.

| Arm | Workloads per batch | Median thread CPU (ms) | Median wall (ms) | CPU range (ms) |
|---|---:|---:|---:|---:|
| Passive, no active request evidence | 400 | 40.394 | 40.400 | 39.826–41.687 |
| Active C1 evidence | 400 | 554.313 | 554.373 | 553.828–558.434 |

Active evidence adds about 1.285 ms of aggregate thread CPU per reconstructed workload in this harness. This does not establish causality for the prior controlled p95 failure. The controlled run would need roughly 3.09–5.21 ms lower C1 p95 across its four cells against the frozen C0 baselines; the measurements here are CPU, not full request p95, and exclude retrieval, DB, ASGI, scheduling and provider transport. No runtime optimization is justified by this replay alone.

The historical CONTROLLED_G6_FAIL remains unchanged. Any runtime change requires a separate minimal proposal and approval, semantic/evidence validation, a fresh pinned controlled C0/C1 N=100 run in all four cells, and independent review. The live G6 absolute bounds and streaming TTFT remain separate campaign checks.
