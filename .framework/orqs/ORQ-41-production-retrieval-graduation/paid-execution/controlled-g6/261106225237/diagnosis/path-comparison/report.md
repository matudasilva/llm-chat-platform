# C0/C1 execution-path comparison

Status: PATH_COMPARISON_COMPLETE_NOT_A_GATE. Author analysis only. No runtime/harness implementation change, new API request or gate rerun.

## Immutable source evidence

compare.py reads Python sources and installed dependency metadata from the two exact G6 images using Docker --network none --pull=never and a standard-library-only command. It imports no app modules or lifespan. Kernel isolation of the host command uses unshare -rn. Python versions and all installed package names/versions match. Nine Python source files differ, as retained in comparison.json and images.diff. Eight existing files add only C1 imports, decorators, observation calls and the request context manager; the ninth is the observer itself. Removing exactly those additions produces equal ASTs for all eight existing files. This is a syntactic check of the frozen code, not a blanket proof of observational safety under every possible failure.

No added SQL query, changed provider/retry contract, retrieval algorithm or persistence branch was found in these image differences. Routes, ChatService, database/provider implementation and retry-summary seam are byte-identical across these images. Differences between observer activity and the frozen C0 code remain real workload differences, not dependency drift.

## Harness path inventory

Both arms install the same LocalASGI request/task tracking, observed database sessions/transactions, local retrieval ports, deterministic native response transport, ScopedProvider queue/backpressure and scope wrapper. C1 additionally retains the Evidence request object; ScopedProvider.scope installs purpose/application-attempt/invocation accounting; native_provider adds the SDK attempt hook; rewrite Capture parses/hashes and records its serialized body before the primary-send timing boundary. Primary Capture and final snapshot/validation occur after that boundary. C0 uses Tape. These asymmetries are existing approved harness behavior. The current record provides no basis for deleting them or correcting p95 by subtracting an estimate.

## Aggregate scope calibration

analyze.py calibrates the actual scope context managers without calling providers: nine rotated batches of 1000 complete two-scope cycles per arm, 100 warmups per arm. P2 network namespace/guard, scrubbed credentials and empty dotenv are used. Process CPU and monotonic wall are sampled only at batch boundaries. Median CPU per cycle:

| Mode | CPU ms |
|---|---:|
| Baseline scopes, no C1 context | 0.001591 |
| Candidate scopes, no active C1 context | 0.018072 |
| C1 request context only | 0.009446 |
| C1 context plus two candidate scopes | 0.050296 |

This calibration excludes payload receipts/Capture/SDK and ASGI/SQL/thread scheduling; it includes full context teardown beyond the gate's primary-send endpoint. It cannot establish an end-to-end bound or be subtracted from G6. It does not justify scope-only tuning as a remedy for millisecond-scale gate gaps.

## Retained G6 tail

Offline tail-analysis.json sorts the existing 100 measured rows per arm/cell, excluding warmups. Ranks 95 through 100 contain 23 combined cases out of 24 candidate observations. Candidate-minus-baseline paired median preparation differences (ms) are:

| Cell | Document | History | Combined | Empty |
|---|---:|---:|---:|---:|
| EN JSON | 2.459 | 3.807 | 6.790 | 0.232 |
| EN SSE | 4.211 | 5.893 | 5.137 | 2.018 |
| ES JSON | 1.263 | 7.941 | 7.726 | 3.064 |
| ES SSE | 4.492 | 8.906 | 7.008 | 1.740 |

These are descriptive paired medians from the one frozen run, not per-stage causal attribution or differences between arm medians. They focus the remaining question on combined-history/document preparation and interaction with asynchronous work. No fresh request was needed for this finding.

## Recommended bounded next step — approval required

Prepare a separate diagnostic of 40 local requests (32 measured plus eight warmups), balanced across EN/ES and JSON/SSE, with two combined and two empty measured cases per cell/arm. Use fresh paired fixtures and unchanged full evidence, native payload parity, pinned images/config and P2. Freeze the plan and independently review it before execution. Do not change the official gate or p95 rule.

Collect only aggregate ingress-to-primary-send process CPU/wall plus bounded GC collection intervals, SQL await intervals and native SDK thread handoff/entry timestamps. All instrumentation belongs to the isolated diagnostic worker, equally applied to both arms; no app or official G6 worker change. Retain thread/request correlation and distinguish overlapping intervals; do not subtract all-thread CPU from wall to invent wait time or add nested/overlapping durations. The intent is to distinguish allocation/GC pauses, SQL/scheduling effects and preparation CPU without the thousands of fine helper wrappers that perturbed the earlier profile. No observer disabling, missing receipts or selective samples may produce success. If measurement cannot correlate safely, mark it inconclusive.

This proposal remains unimplemented and unexecuted. The only supported current conclusion is that source/dependency drift and basic scope entry/exit do not explain the observed gap on the available evidence. C1 receipt work interacting with allocation/scheduling remains a hypothesis.

## Validation and disposition

Read-only image comparison, eight AST equalities, 36 retained aggregate calibration batches and retained 840-row descriptive tail analysis. Audit absent/empty; zero external/provider calls, API requests, SQL queries or spend. No new independent review is claimed. All scripts/data are retained in this directory. CONTROLLED_G6_FAIL, paid-admission block, global Implement / DECISION_FREEZE_PASS, model, accounting and thresholds remain unchanged. No app/P5 edits, campaign, Notion or commits.
