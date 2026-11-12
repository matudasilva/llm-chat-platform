# Coarse-stage harness implementation validation

Operator `autorizo` approved the exact proposed four-file diagnostic, disposable
preparation and one360-request local execution contingent on source/packet reviews.
The approval receipt binds the preserved proposal, preview and design completion.

Added only `stage_latency.py`, `stage_latency_worker.py`,
`stage_latency_observer.py` and `test_orq41_stage_latency.py` at their proposed
locations. The approved blocked worker, wait observer, app and P5 remain intact.
The separate derived loop retains first endpoint wall-clock semantics, native
payload/C1 validation, full completion/quiescence and existing cleanup behavior.
It additionally retains bounded correlated stage/SQL/SDK tapes, closed C1 chains,
native dispatch corroboration, process CPU and event-loop context-switch counters.

## Validation chronology

All commands are in `commands.json`, using the pinned775 image, network-none/P2,
disabled credentials/metadata/dotenv discovery and no cache-provider writes.

- Initial focused36PASS; extended ON/OFF JSON/SSE controls44PASS.
- Initial regression289PASS.
- Independent source review found two MEDIUM diagnostic defects before any
  service preparation or experiment admission. Its exact source snapshot,
  counterexamples and findings are retained under `independent-findings/` and
  `initial-source-review/`.
- R1: ingress and SDK callback run in different threads. Read the captured
  event-loop native TID's `/proc/self/task/<TID>/status` at both endpoints,
  retaining target and reader TIDs. Exactly two counter reads/request; the
  rewrite send does not read unused counters. These endpoint reads perturb
  both modes equally in structure; their time is not subtracted or claimed
  negligible. Whole-process CPU remains explicitly all-thread CPU.
- R2: use an injected, best-effort first wall read. Clock failure marks the
  diagnostic invalid while original ASGI/capture delegation occurs exactly
  once. No global clock patch; None-safe failure rows. Validate endpoint type,
  target identity and monotonicity after each functional response/quiescence,
  before PASS or another admission. Both defects were confined to new harness
  files and did not modify runtime.
- Remediation focused64PASS and interim regression309PASS retained.
- **Frozen-source final focused64PASS and regression309PASS/0skip**, including
  the exact two-counter-read assertion, actual memory-native ON/OFF JSON/SSE
  loops, ingress/primary clock loss, decreasing/invalid endpoints, observer and
  cleanup failure, async nesting, delegation/error/cancellation identity,
  SQLAlchemy error/listener cleanup, cutoff clipping/overlap and strict plan /
  approval/review/start guards. Final reports: `focused-final.xml` and
  `regression-final.xml`. No new tests make timing-speed assertions.

The harmless existing pytest warning about `cache_dir` occurs because the cache
plugin is intentionally disabled; no repository pytest cache is written.

The505previously accepted source/configuration hashes, including app/P5/global
`.env` and unrelated user changes, remain unchanged. Local unit-control traffic
is distinct from the proposed experiment: **experiment requests0** at this
implementation-validation stage; no provisioning, provider/egress/paid calls,
new image, host tuning, campaign, G9, Notion or commit. External spendUSD0.
Global In Progress / Implement / DECISION_FREEZE_PASS; official G6FAIL and paid
block remain. Source and prepared-packet review receipts are separate evidence.
