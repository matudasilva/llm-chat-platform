# No-benchmark lifecycle packet — preparation

Status: PREPARED_BLOCKED_ON_DRILL_ADAPTER. Documentation only, not an executable
packet or live approval. Source review remains PASS. Global Implement /
DECISION_FREEZE_PASS; P5 CLOSED; G6 FAIL; paid admission blocked.

## Verified boundary

The seven reviewed technical files still match source-review.json. Reuse its
290 author tests and four narrow independent controls; no repeated suite here.
The independent IPC rerun remains uncompleted, as already disclosed.

There is no production-ready synthetic lifecycle driver or sealed installer.
`dedicated_lifecycle.build_manifest` requires 32 workers and 1440 A/A slots;
`validate_manifest` accepts a nonempty synthetic schedule but does not author it.
`dedicated_environment.execution_barrier` unconditionally rejects bound execution;
prepare/provision/execute must remain blocked. `host_helper.py` explicitly supports
local-drill authorization but supplies neither installation nor a synthetic worker.
Using the benchmark worker or fabricating A/A receipts would violate this scope.
These are packet dependencies, not newly reproduced source safety findings.

## Smallest proposed next increment — requires approval

Add a separate no-benchmark controller/worker and offline packet authoring utility
under this directory, plus focused tests. Reuse the reviewed Supervisor, Client,
HostBackend and helper without changing them or removing execution barriers.
One synthetic worker and one owned PostgreSQL, Redis and collector per case;
no app import, /chat, benchmark sample, latency metric or provider invocation.
Synthetic receipts must identify themselves explicitly and cannot count toward
A/A, G6 or paid campaign evidence. Any inability to use the existing interfaces
without changing reviewed source must be reported before extending this increment.

The new worker must run as the container's actual PID1, use the existing Unix
protocol, complete one fixed synthetic slot, close its resources, write the existing
finalizer receipt and exit zero. The controller must wait for that actual exit
before finish. No forged finalization or manual journal edits. Its source, mounts,
command and receipt must be pinned alongside the existing sources.

First implement/test/review this adapter offline under P2; do not provision or
install during that increment. Then freeze the commands and obtain a separate
live staging authorization. Finally bind actual IDs/controller identity, review
the deployment hash and obtain live execution authorization. Implementation-only
approval does not substitute for either host action authorization.

## Prospective first live case (normal path only)

1. Read-only inventory: existing images, free disk, baseline CPU/power/container
   identities, boot ID, absence of conflicting units/journals. No image pulls.
2. Under separate staging approval, allocate fresh stopped containers/private
   storage only. Freeze full IDs and inspect projections. PostgreSQL uses network
   none; others join its namespace; no published ports, external credentials,
   restart policy, privileged mode or added capabilities. Existing resources stay
   untouched. Record any partial staging result; do not blindly retry or delete.
3. Pin existing image IDs: worker uses candidate c0 image, PostgreSQL and auxiliary
   images from the reviewed plan. API/PG placement and memory/CPU limits must match
   HostBackend exactly. No speculative image IDs, PIDs or container IDs in a packet.
4. Freeze a fresh run ID, boot/controller PID/starttime/UID/GID, synthetic schedule,
   local-only credentials, mounts, commands and all source/evidence hashes. Review
   root installation commands, ancestry/modes, fsync and no-overwrite behavior.
   Credentials remain private and must not enter review logs or this repository.
5. Seal root deployment and journal; bind the separate execution authorization to
   the deployment SHA256. Install only reviewed code into the new run directory.
   Existing sealed helpers/drills remain immutable. No generic sudo dispatcher.
6. Start the supervisor as its own systemd unit. It must validate all containers
   stopped, durably START, arm/read back the independent timer, then apply CPU
   changes. Only after successful readiness start PostgreSQL, auxiliaries and
   synthetic worker in that order. Prove local service readiness without /chat.
7. Worker uses one serial synthetic permit; controller retains receipt and actual
   exit/finalizer proof, then sends finish. Reuse normal recovery: drained clients,
   smart PostgreSQL shutdown, graceful auxiliaries, benchmark populated0, exact
   baseline restoration, terminal receipt and timer disarm.
8. Preserve stopped containers and evidence. No rm/prune, force kill, retries,
   implicit rerun or automatic deletion of disposable databases.

Limits remain 7200s nonrenewable reservation, 1s permit, 5s command, 390s drain,
30s graceful exit from acknowledgment, 60s restoration from durable RESTORE_BEGIN.
No change to existing 300s/10s request semantics; no request runs in this drill.
Unknown failure stops admission and retains residuals. NOT_DRAINED requires
operator reconciliation. Restoration alone does not imply overall PASS.

## Acceptance and retained evidence

Require actual host Unix peer authentication across container namespaces; pinned
placement; independent systemd timer identity/deadline; synthetic admit/consume/
complete chain; no second admission; finalizer plus zero exits; PostgreSQL client
count and clean shutdown; populated0; baseline file/manager/kernel parity;
original containers and power unchanged; LIFECYCLE_PASS and terminal exit code0.
Retain commands, redacted configuration, inspect snapshots, journal/head, source
hashes, timestamps, timer/service readbacks, logs and restoration report.
No external/provider traffic is permitted. Record network namespace isolation
and actual audit scope; do not infer observed zero egress merely from intent.

Controller loss, supervisor interruption, expiry and injected cleanup failure
require separately frozen cases/expected terminals after the normal case. Never
claim the normal case proves all live fault paths. Reuse existing P2 fault evidence
without presenting it as live execution. No benchmark authorization follows from
any lifecycle PASS.

## Missing identities and explicit decisions

Missing by design before live staging: fresh run ID, container IDs/projections,
controller/boot identity at execution, private paths, concrete deployment SHA and
live authorization. Missing implementation: synthetic driver/authoring/installer
with independent source review. Thus no executable commands are published here.

Requested next approval: implement only that isolated adapter and installer
preparation, with focused P2 tests and independent review. No reviewed source
changes, host operations, benchmark, downloads or paid calls. Expected provider
cost USD0; live wall time is not estimated from the 7200s safety cap.
