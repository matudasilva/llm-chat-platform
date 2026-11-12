# Controlled G6 revised harness independent review

**CONTROLLED_G6_HARNESS_INDEPENDENT_REVIEW_PASS** for plan
`d27e1cdabcd6bfdbf2fc43d22e510522d9c3f0f53db0bea6c14eefb7d940bee6`.
Reviewer: `/root/packet_review`, distinct from the harness author. No gate/API,
SQL, Docker operation, provider call, external connection or privileged request
was performed by this reviewer. Only review artifacts were added.

## Findings resolved

- G6-R1: the worker now requires exactly one valid, closed, current-request
  candidate context, checks its lifecycle/count/hash chain and reconciles both
  real native transport send records (rewrite then primary), including instance,
  correlation, invocation, payload and application/SDK attempt identities.
  Validation occurs after the primary-send timing endpoint, inside the request
  deadline, before PASS. Missing best-effort state cannot produce a sample PASS.
- G6-R2: an outer monotonic asyncio timeout encloses the actual ASGI request,
  response parsing, quiescence and evidence validation. A final clock comparison
  rejects CPU-only validation that crosses the 300-second limit without yielding.
  The HTTPX timeout argument is no longer the only request bound.

## Independent controls and prepared input proof

Executed the 23 existing pure controls and six new no-I/O probes under
`unshare -rn env -i` with the P2 network guard, empty settings env, absent provider
credentials and metadata discovery disabled. All 29 passed. XML: `review.xml`
and `probes.xml`. One benign pytest warning in each invocation concerns the
disabled cache plugin's `cache_dir` setting. No actual platform API was invoked.

Novel probes use the actual C1 request context and Capture with memory-only
serialized payloads: normal acceptance without mutation, dropped dispatch,
changed authoritative payload digest, wrong purpose, invalid ordinal and real
best-effort context-construction loss. All corruptions reject.

The original prepared-data verifier incorrectly normalized a nonexistent
`database_url` model-dump field. Settings actually exposes
`database_url_override`. A preserved-copy revision changes only the three-key
whitelist to `database_url_override`, `database_url_app`, `database_url_ops`
(plus reviewer attribution). The parent executed it read-only under approved P2
Docker access. Its successful hash-bound receipt proves all 420 conversations
and 9600 ordered fixture messages per arm, exact deterministic UUID/content
crosswalk, restored P3 content, applicable RLS, schema parity and effective
configuration equality after normalizing only paired database names. Full
per-arm config hashes still match the frozen plan.

Rechecked all frozen harness/support hashes and preparation/fixture bindings;
the original failed review and original plan remain preserved. This revision
uses identical untouched sample UUIDs and prepared DBs before any API sample.
No worker result files existed when the PASS receipt was issued.

## Measurement contract and limitations

The fixed population is 100 measured plus five warmups per language/path/arm:
800 measured requests and 40 warmups. Every measured cell has 25 cases in each
of document/history/combined/empty. Paired arms share sample/request/conversation
identities; exact serialized rewrite/primary payload hashes and call counts must
match. Missing, failed or duplicate samples reject; there is no best-run selector.
Nearest-rank p95 and the approved +5%/zero-baseline rules are unchanged.

Both arms timestamp at outer ASGI ingress and at entry to the memory native SDK
primary send, before Capture bookkeeping. Earlier candidate accounting work is
included. Subsequent validation is outside the measurement endpoint but remains
required for accepting the sample. This is a local controlled comparison, not
live provider latency, paid campaign evidence or proof of absolute live bounds.
R=1, fixed cell order and host jitter remain explicit limitations.

The Docker helper has a 240-second operation timeout, shorter than the worker's
300-second request ceiling. A pathological stall can therefore interrupt the
controller first; it must remain an incomplete/failed attempt with the container
preserved, never a PASS or permission to replay. This does not permit acceptance
after the request deadline or relax any gate threshold.

No BLOCKER/HIGH/MEDIUM findings remain in this reviewed prospective scope.
The independent receipt permits only the separately authorized controlled local
execution; it is not a measured G6 PASS or global decision-freeze acceptance.
