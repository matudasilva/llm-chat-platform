# Aggregate diagnostic execution independent review

**DIAGNOSTIC_AGGREGATE_EXECUTION_INDEPENDENT_REVIEW_PASS**.
This closes review of the diagnostic only. Official CONTROLLED_G6_FAIL remains
unchanged; this is neither a new gate population nor a p95 correction.

Independent retained-data replay under P2 checked the frozen plan/review binding,
all source/support and eight worker hashes, sample metadata/order/deterministic
UUIDs and exact integer interval arithmetic. All40 requests succeeded:32 measured
and8 warmups,20 unique canonical candidate accounting-instance IDs. Native
serialized rewrite/primary payload hashes and call sequences match for every
paired sample, including warmups. No missing, duplicated or failed row was
excluded. Candidate raw chains were validated by the reviewed worker before row
acceptance; they are not retained and are not claimed as independently replayed.

All published category medians, ranges and16 paired sample deltas reproduce:

| Category | Median paired C1-C0 process CPU (ms) | Median paired wall (ms) |
|---|---:|---:|
| Document | 2.826514 | 1.931929 |
| History | 3.671681 | 3.616651 |
| Combined | 8.514116 | 9.557463 |
| Empty | 1.346460 | 1.414576 |

These are medians of paired deltas, not differences of medians. The descriptive
analysis uses four measured identities per category, not an inferential sample.
Process CPU includes all worker threads/background work; wall minus CPU cannot
be interpreted as SQL wait and no per-function causal share follows. The lack
of fine wrappers removes that prior instrumentation mechanism, but does not
randomize arm timing, eliminate host jitter or explain the entire official p95
regression. No normalization, subtraction or threshold waiver is justified.

The parent's separately executed read-only final verifier was inspected and its
source/receipt hash binding checked. It confirms20 conversations/424 messages per
arm: original384 history messages and exactly one complete new user/assistant
pair per conversation, P3/RLS/schema/config preservation. Only validated newly
generated message IDs are normalized across arms; history identities, sequences,
tenant/conversation, roles and contents remain checked. Reviewer did not connect
to PostgreSQL or execute Docker. No network-guard attempts are recorded.

Only independent replay/review artifacts were added. No new API requests,
diagnostic rerun, source fix, runtime optimization or paid execution was performed
by this reviewer. Next implementation or official rerun requires its own bounded
proposal and authorization; these results alone do not promise a return to+5%.
