# Independent offline diagnosis review

**CONTROLLED_G6_OFFLINE_DIAGNOSIS_INDEPENDENT_REVIEW_PASS**.

Recomputed all 16 category medians and slower-pair counts directly from the
retained measured rows: C1 is slower in344/400 pairs (EN JSON89, EN SSE95,
ES JSON84, ES SSE76). History medians span5.812568–8.588744ms and combined
5.133363–11.666250ms; document/empty ranges also match the report.

Static timing-boundary claims are correct: the timestamp is taken before
primary Capture bookkeeping. That bookkeeping and final candidate validation
cannot directly contribute to the same request's measured interval. Rewrite
Capture processing, candidate invocation/log-handler scopes and SDK attempt hook
execute before the endpoint. Previous-request scheduling/cache/GC effects remain
possible; retained timings do not quantify their contribution. The report does
not assign causal percentages or subtract overhead from the failed gate.

The original CONTROLLED_G6_FAIL and approved +5% rule remain unchanged. Paired
input deltas are descriptive, not simultaneous randomized causal estimates.

The proposed separate32 measured plus8 warmup requests total40, use fresh
diagnostic data and require implementation/execution approval. The proposal
preserves app/P5, observers, serialization parity and official results; profiled
timings cannot replace the N100 gate. Inclusive/exclusive/thread attribution and
instrumentation cost must be verified before interpreting resulting profiles.

No new finding requiring a change to this report was identified. No profiling,
API request, SQL, Docker, external connection or source fix was performed by
review. Only independent review artifacts were written.
