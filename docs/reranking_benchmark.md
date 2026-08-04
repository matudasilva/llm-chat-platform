# ORQ-22 reranking benchmark

The dataset is frozen at SHA-256
`a5a52e4e6484652edecfa871b048d646da2db2b20c51c6d17157cd23f444bdcb`.

Benchmark arms have not run. The operator's deterministic 12/60 label-sample approval is still a
hard gate. This file will be generated from persisted raw responses by
`app.scripts.run_reranking_benchmark`; conclusions will come from its paired-bootstrap table.

Pre-run Bedrock finding: 8 rapid calls throttled all tested regions; 4-second spacing with retries
still failed; approximately 15-second spacing succeeded. The AWS arm therefore runs at concurrency
1 with 15-second pacing and incremental persistence.

Qwen prerequisite status: the official model repository is Apache-2.0 and contains 1.19 GB weights
(1.21 GB repository total), but CUDA is not currently reachable from this environment. If that
remains true at execution time, the local arm will be recorded as omitted rather than replaced by a
stub.
