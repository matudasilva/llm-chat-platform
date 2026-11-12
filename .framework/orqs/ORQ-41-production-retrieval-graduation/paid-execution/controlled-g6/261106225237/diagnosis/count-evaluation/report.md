# Offline item-counter evaluation

**EVALUATED_REJECTED_FOR_G6_REMEDIATION**. Author evaluation only; no new independent review is claimed. No app source was changed.

The counterfactual skips recursive calls for scalar children, which contribute zero to the original item count. It preserves recursion for lists/dictionaries, including subclasses. It is compiled into a temporary function using the same live observer globals, then installed only in the isolated evaluator process.

68 deterministic equivalence checks passed: 20 full document/history/combined/empty fixture workloads with complete snapshots, canonical chain hashes, sizes/item counts, serialized native bodies and independent Capture sends; 42 nested/scalar/alias/subclass/cycle/invalid-JSON/limit cases; six exact byte/item cap edges. Rendering and native serialization use the existing provider adapter builder and local botocore serializer without a client or provider call.

Measurement uses aggregate process CPU and monotonic wall clocks only. Nine rotated-order batches per category/arm, ten repetitions of each matching frozen case per batch: 3600 measured offline workloads total, plus 120 separate warmup workloads. Full observations, renderer, native serialization/Capture, snapshot and independent chain validation are included equally in both arms. There are no per-function clocks.

| Category | Median candidate-minus-current CPU ms/workload | Candidate lower CPU batches | Median wall delta ms/workload |
|---|---:|---:|---:|
| document | -0.002540 | 6/9 | -0.002600 |
| history | -0.039454 | 9/9 | -0.038989 |
| combined | -0.045387 | 9/9 | -0.045619 |
| empty | -0.005436 | 5/9 | -0.005734 |

The history/combined signal is favorable and repeatable in this offline sample, but the median improvement is only approximately 0.04 ms per workload. Document/empty distributions include unfavorable batches. These measurements do not justify another runtime patch, image or gate run as a remedy for the observed 0.135–3.652 ms excess over G6 cell limits. The scopes differ: no arithmetic correction, prediction of G6 p95 or causal attribution is claimed. Reject this candidate for the current remediation objective; keep the already reviewed image unchanged.

Inputs: frozen 20-case profile fixtures and P3 archive; 2146 chunks decoded with local pg_restore --data-only --table=chunks -f - under --network none --pull=never. Document ranking is the earlier deterministic lexical reconstruction, not original retrieval ranking. No SQL query, API request or provider operation ran. The temporary decoded SQL was removed after its hash was retained in result.json. Archive, fixture, source, evaluator and workload hashes are retained there.

Execution: unshare -rn env -i; absent AWS config/credentials, metadata disabled, APP_SETTINGS_ENV_FILE empty, P2 network guard and PYTHONDONTWRITEBYTECODE=1; .venv/bin/python <this directory>/evaluate.py. Audit absent/empty. External calls, provider calls and paid spend: zero. Model/threshold/accounting/P5/global phase remain unchanged. CONTROLLED_G6_FAIL and paid-admission block remain.

Preparation failures retained in this report: the first offline pg_restore invocation omitted -f and exited without DB/network access; corrected to -f -. The first equivalence run exposed an evaluator-isolation bug: compiling with copied globals hid injected limit changes from the counterfactual. Corrected to shared observer globals before any performance batches; all 68 checks then passed. No runtime bug was patched or workload replayed against an API.

The earlier coarse/fine diagnostics and this result do not establish that receipt counting explains the gate gap. Further diagnosis should examine the complete C0/C1 execution-path differences and request/context/scoping integration, rather than another small receipt-loop optimization. Such a diagnosis needs a bounded proposal; this evaluation authorizes no further execution.
