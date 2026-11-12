# Optimized-image aggregate execution independent review

**DIAGNOSTIC_AGGREGATE_EXECUTION_INDEPENDENT_REVIEW_PASS**, descriptive only.
Official CONTROLLED_G6_FAIL remains unchanged; no official p95 was replaced.

Independent retained-data replay ran under P2 with no API, SQL, Docker, source
fix or external call. It checks the exact frozen plan/review/source/support
bindings, eight raw worker hashes and result/analysis hashes. All40 functional
rows pass:32 measured plus8 warmups, exact order/metadata/deterministic UUIDs,
20 unique canonical candidate accounting-instance IDs and paired serialized
rewrite/primary payload and call-purpose equality. All wall/process-CPU deltas
reproduce exactly from integer timestamps; published descriptive medians, ranges
and16 paired deltas agree. Raw candidate chains were checked by the reviewed
worker, not retained for separate post-run chain replay.

| Category | Median paired CPU C1-C0 (ms) | Median paired wall C1-C0 (ms) |
|---|---:|---:|
| Document | 1.823074 | 1.103455 |
| History | 4.610156 | 4.175962 |
| Combined | 7.319369 | 6.889512 |
| Empty | 4.135444 | 3.801063 |

Rechecked the candidate image pin:
`sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707`.
Complete parent/candidate app inventories still differ only at the approved
context_evidence.py file, hash
`32490a738e58d2499b6f3a2bac9ee961f6d060a486830752d7b5207b5398ba20`.
Their receipt/review/inventory hashes are frozen plan support files. No other
application change is inferred or excused by this diagnostic.

The parent-executed read-only final DB verifier source/receipt was inspected and
hash-bound:20 conversations and424 messages per arm, preserved384 historical
messages and exactly one complete new pair per conversation, P3/RLS/schema and
effective config preservation. Only validated generated message UUIDs normalize
across arms. Reviewer did not independently execute database operations. No
network-guard attempts are recorded and no provider/paid execution occurred.

Historical comparison with261106190648 is mixed. New C1 process-CPU medians are
approximately1.048ms higher for document and1.642ms higher for empty, and0.747ms
lower for history and0.734ms lower for combined. This is not a uniform gain.
Different fresh identities, separate arm/run times and background/host effects
prevent a causal optimization estimate. Even differences of paired C1-C0 deltas
between runs must not be presented as isolated code-effect measurements.

Each category has only four measured pairs across different language/path cells.
Aggregate process CPU includes all threads/background work; wall minus CPU is
not a wait estimate. No corrected p95, claimed satisfaction of+5%, threshold
waiver or paid-admission permission follows. No extra run was selected or
requested by review. Only this diagnostic's evidence integrity and descriptive
arithmetic pass; any subsequent official measurement needs separate authorization.
