# Independent diagnostic profile execution review

**DIAGNOSTIC_PROFILE_EXECUTION_INDEPENDENT_REPLAY_PASS — not a G6 gate.**
The official CONTROLLED_G6_FAIL remains unchanged.

Independent `verifier.py` executed under P2 without any API, Docker, database or
provider operation. It checks the exact plan/source/test/16 worker-profile file
hashes; all40 sample identities/order, 32 measured and8 warmup markers;20 unique
candidate accounting UUIDs; and paired native payload/purpose equality.

The raw tapes contain7696 events,6712 before primary and984 after. No event
crosses the cutoff. Reconstructed synchronous nesting independently per request
and thread: parent labels, inclusive/exclusive wall and thread-CPU arithmetic all
match exactly. SQL intervals are separately clipped to the preparation interval
and unioned; classification and every measured call count match analysis.json.
No inclusive-span summation, CPU/SQL addition, corrected p95 or causal percentage
is used. Request identity and phase validation are derived from frozen inputs
and actual worker cutoff timestamps.

The descriptive medians are correct: instrumented C1 application-side self CPU
is7.858660ms document,15.618204ms history,17.240448ms combined and4.031704ms empty.
Capture-exclusive medians are0.260603–0.317227ms; scope runtime and exclusive
components and SDK callback medians also reproduce. There are5432 wrapped
candidate synchronous calls before primary in16 measured requests, including1328
primary-purpose text_receipt and2152 primary-purpose digest calls. Primary
Capture remains after the endpoint and cannot directly account for that same
request's preparation duration.

These are **instrumented** CPU observations. Wrapper clock/stack/recording work
can remain inside parent self CPU; the large instrumentation asymmetry means
these numbers cannot establish exact original-runtime cost shares or justify an
app optimization by themselves. Existing controlled-G6 wall regression remains
failed independently of this diagnostic. No paid execution is unblocked.

The next-step proposal is appropriately narrower than runtime changes: approve a
separate offline aggregate CPU replay with explicitly reconstructed frozen-input
stage workloads and no per-leaf timing wrappers. Validate exact receipt semantics
and disclose reconstruction/calibration limitations. Only after that result
should one concrete observational-only diff be proposed for authorization. Do not
promise a reduction to+5%, subtract profiling costs or automatically rerun G6.

Read-only final DB verification is a separate parent-executed receipt. The first
verifier preserved exact per-arm content checks but mistakenly required equality
of new generated message UUIDs across arms. Its original source/error remains
retained. The corrected verifier normalizes only the40 newly generated message
IDs per arm after validating every original history UUID and each new user/
assistant pair. It still requires canonical unique IDs per arm, exact tenants,
conversations, roles, content, sequences, full P3/RLS/schema and config parity.
No data or production code was changed to accommodate that verifier correction.

Only independent review/verifier artifacts were added by this reviewer. No new
requests or runtime optimization were performed. See receipt.json and the
separate database-final-verification.json for their precise evidence scopes.
