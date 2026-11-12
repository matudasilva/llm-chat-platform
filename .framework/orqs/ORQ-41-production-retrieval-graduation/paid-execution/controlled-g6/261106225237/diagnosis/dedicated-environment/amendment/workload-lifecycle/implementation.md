# Dedicated workload lifecycle — source implementation

The operator's `dale` approved the four decisions in `proposal.md`, recorded in
`authorization.json`. This increment implements the harness lifecycle only.
It does not authorize installation, CPU changes, disposable provisioning, a live
lifecycle drill, A/A execution, or paid traffic. The bound execution barrier stays
unconditional. This is a diagnostic subpackage, not a new ORQ phase transition.

## Source surface

- `dedicated_lifecycle.py`: serial durable admission, authenticated Unix packets,
  one-use expiring permits, journal/head recovery, exclusive recovery ownership,
  STOP, bounded drain observation, restoration and terminal receipts.
- `dedicated_lifecycle_host.py`: fixed actions against exact frozen disposable
  IDs; host peer/placement checks, one-shot watchdog, graceful service shutdown,
  clean PostgreSQL proof and an adapter to the existing restoration primitives.
- `host_helper.py`: root-sealed source/manifest/review/authorization validation.
  It cannot execute from this repository lane. No installer or general dispatcher.
- `dedicated_environment.py`: binds approved lifecycle identities and limits.
- `blocked_latency.py`: opt-in controller binding, precreated worker identity,
  short inspect polling and lifecycle completion before publishing final result.
- `blocked_latency_worker.py`: optional permits outside the original ingress/
  dispatch measurement callbacks and final evidence after resource finalizers.
- `tests/experiments/test_orq41_dedicated_lifecycle.py`: deterministic local
  state-machine, Unix socket, worker JSON/SSE and legacy-recovery-double tests.

Existing callback AST assertions still compare the original ingress and dispatch
callbacks. The permit wrapper runs before ingress; no measured time is subtracted.
The legacy unbound path retains its Docker helper. Source identities in older
review receipts describe their historical versions and have not been rewritten.

## Invariants and failure behavior

The nonrenewable window is 7200s from durable START before CPU mutation. The
independent timer uses an absolute boot-monotonic deadline, not a relative lease
reset after arming. Each permit lasts 1s; request/cleanup remain 300s/10s. STOP and
admission share one lock. A committed request can remain unresolved; it is never
resent. Controller or supervisor loss never opens another admission window.

A separate recovery lock serializes normal and watchdog recovery. An exact valid
single appended record ahead of the head is retained only during recovery; unknown
corruption fails closed. A durable RESTORE_BEGIN preserves the original 60s clock
across interruption. Drain proofs arriving after 390s cannot trigger restoration
or PASS. Service signal intents and outcomes are durable and never blindly repeated.
An intent without an outcome after a crash remains ambiguous and prevents PASS;
a later stopped process cannot erase an earlier operational error. API
workers receive no shutdown signal. PostgreSQL uses smart signal-only shutdown;
Redis uses shutdown/no-save; collector receives SIGTERM, with no forced escalation.

A failed or hanging service preserves its identity and residual state. Safe CPU
restoration may succeed while overall lifecycle remains FAILED. A sample PASS
cannot cover a failed worker finalizer: actual zero exits and finalizer receipts
are required. Timely restoration, full sample completion, owned-service exits and
baseline verification are all required for LIFECYCLE_PASS. No timer disarm can
replace that proof. Durable terminals are never rewritten.

Administrative helper SHA256
`8064e669e1921475167fb70fb73d3746cb4c034fa02fe207c7ffa749346b2be2`
is unchanged. Its restoration algorithm is reused through an adapter that delegates
watchdog ownership to the new lifecycle timer. The old administrative 300s timer
is not armed. Internal administrative DISARMED means control returned to the new
lifecycle owner; only the new owner can disarm its independent watchdog.

## Remaining execution boundaries

No installed helper, container ID manifest or executable packet was created.
A future separately reviewed packet must freeze newly allocated stopped containers,
mounts, private local credentials, root-owned deployment and controller identity,
then install/start the supervisor and initialize disposable services under its
fixed window. `build_manifest` checks the exact 32-worker/1440-slot A/A population;
creation of those containers is not performed by that pure authoring function.
The existing prepare/provision entry points still reject dedicated execution.

Before any benchmark: review the exact installation/ownership commands and obtain
separate approval for the no-benchmark lifecycle proof. That proof must exercise
real namespace, systemd, timer, owned PostgreSQL shutdown and restored-host evidence.
Only later can a fresh A/A packet and one-run authorization be considered.
Unit doubles and source review are not environment readiness or a G6 result.

The design's scheduling and filesystem limitations remain: nominal observation
bounds cannot guarantee scheduling of a starved/hung kernel process; unknown
results invalidate the trial, and NOT_DRAINED requires operator reconciliation.
No claim of interval-wide absence of hostile host administration is made.

Global state remains Implement / DECISION_FREEZE_PASS; P5 CLOSED; G6 FAIL and paid
admission BLOCKED_CONTROLLED_G6_FAIL. No app/P5/.env/model/threshold/accounting/
concurrency changes, host mutations, provider calls, downloads, Notion or commits.
