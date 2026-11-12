# Normal local synthetic lifecycle trial — approval proposal

Status: PROPOSED_NOT_AUTHORIZED. Documentation only, 2026-11-12.
G6 remains FAIL; paid execution remains BLOCKED. P5 remains CLOSED.
This is one normal synthetic lifecycle case, not a benchmark or readiness claim.

## Evidence reused and remaining question

Reuse `revalidation.json`, `revalidation-p2.xml`, and `revalidation.md`: both
focused suites passed (26 tests), including adjacent pinned-core loading for
worker/controller under isolated Python; bounded independent review found no
actionable findings within preparation-only claims. No tests were repeated for
this proposal. The older 11-test result and budget-stop notes are historical.

The proposed trial would test whether the actual selected local image can run
the synthetic worker as PID1, load the pinned core, authenticate across the host
Unix socket boundary, complete exactly one synthetic slot, exit cleanly, and
allow the existing supervisor to drain and restore the exact baseline.
Offline bootstrap success does not establish any of those live properties.

## Scope and approval boundaries

One fresh run: exactly one synthetic worker, one PostgreSQL, one Redis, and one
collector, using existing local images. No application request, app import,
provider traffic, image pull/build, package installation, benchmark, campaign,
fault injection, retry, or change to reviewed lifecycle sources. Existing
containers, old sealed runs, P5, and application code are outside the change scope.

No host action is authorized by this document. Request approval first for step 1
only: a bounded read-only local inventory and preparation of the exact staging
command packet. This permits inspecting local Docker metadata and host state,
but not starting a container, executing inside an image, creating resources,
writing `/var` or `/run`, or changing systemd/CPU/power settings. If metadata
inspection needs elevated access, that permission must also be explicit.

After inventory, submit the concrete command packet for staging approval. A
staging approval must enumerate its stopped containers, private storage, image
probe if needed, root installation actions, and permitted paths. Lifecycle
execution requires a further approval bound to the actual deployment hash and
reviewed supervisor/timer commands. No approval is inferred from earlier
administrative drill permissions or from the 26-test result.

## Ordered procedure and evidence

1. **Inventory after approval.** Read existing image IDs/digests and metadata,
   candidate c0 image availability, PostgreSQL/auxiliary image availability,
   free disk, boot identity, baseline container/CPU/power state, and conflicting
   units/run paths. Inspect only the relevant baseline and image references.
   Retain a redacted inventory with timestamps and exact commands. Missing images
   stop this scope; do not pull, build, or substitute an unreviewed image.
2. **Freeze the staging packet for review.** Select a fresh unused run identifier
   and proposed private paths, exact existing image IDs, resource/placement
   settings compatible with HostBackend, and command/mount/user configuration.
   Worker command is the pinned isolated Python command from the adapter, with
   no shell wrapper; the interpreter path is not proof of its availability.
   If availability cannot be established from retained evidence, specify a
   separately approved, one-shot network-none image probe. Its success would
   establish interpreter/bootstrap availability only, not the normal trial.
   Include exact no-overwrite installation commands or a reviewed installer;
   neither exists as an executable packet in this proposal. Any required new
   code or inability to reuse reviewed interfaces requires separate scope approval.
3. **Stage only after command-packet approval.** Create the fresh stopped owned
   containers and private storage; capture full IDs and inspect projections.
   PostgreSQL uses network none; auxiliaries/worker share its namespace, with no
   published ports, external credentials, restart policy, privileged mode, or
   added capabilities. Check actual namespace settings, mount sources, UID/GID,
   command, placement, and limits against the frozen packet. Retain partial
   results on failure; no blind retry, deletion, or substitution is permitted.
4. **Bind and seal within the approved installation scope.** Record actual boot
   and controller PID/starttime/UID/GID, owned IDs, one fixed synthetic slot,
   source/review hashes and private local credentials. Render the plan, manifest,
   deployment, empty journal and adapter payloads using the existing preparation
   utility. Review actual hashes and install only into the fresh approved run
   paths with verified root-owned nonsymlink ancestry, exclusive creation,
   ownership/modes, fsync and readback. Receipt storage must be empty and writable
   by the selected worker identity. Keep credentials out of repository evidence.
   If identities change, stop and regenerate/review the binding; do not patch a
   sealed deployment in place. Execution authorization remains absent here.
5. **Review execution separately.** Present the deployment hash, exact supervisor
   and independent timer commands/identities, restoration baseline, resource
   impact, operator recovery procedure and evidence destinations. Obtain explicit
   deployment-hash-bound local-drill authorization. Preserve existing barriers;
   do not invoke a blocked benchmark prepare/provision/execute path or bypass it.
6. **Run one normal case only after execution approval.** Supervisor verifies all
   containers stopped, records durable START, arms and reads back the independent
   timer, then applies the approved CPU settings. Start PostgreSQL, auxiliaries,
   then the direct-Python PID1 worker only after readiness. Record local service
   readiness without `/chat`, actual PID1 and image identity, socket namespace
   access/peer authentication, and the single admit/consume/complete chain.
7. **Finish and restore through existing lifecycle machinery.** Retain the
   synthetic receipt, finalizer, and actual worker zero exit before controller
   finish. Verify drain, PostgreSQL client count and clean smart shutdown,
   graceful auxiliary exits, empty benchmark population, exact baseline
   restoration, terminal result and timer disarm. Preserve stopped containers
   and evidence for review; no rm/prune, force kill, manual journal edits or rerun.

Existing limits remain unchanged: 7200s nonrenewable reservation, 1s permit,
5s command, 390s drain, 30s graceful exit from acknowledgment, and 60s restoration
from durable RESTORE_BEGIN. The reservation cap is not a runtime estimate.
Unknown outcomes close admission and leave recovery to the reviewed supervisor
and operator procedure. NOT_DRAINED or incomplete restoration requires operator
reconciliation; restoration alone never establishes overall PASS.

## Inputs still missing

| Input | Required before |
| --- | --- |
| Approved local host/maintenance window, baseline and operator recovery ownership | Staging approval |
| Existing image IDs/digests, actual interpreter availability, approved image probe if needed | Frozen staging/execution packet |
| Fresh unused run ID, exact paths, resource settings, private credential handling | Staging approval |
| Exact reviewed installation and supervisor/timer commands; any needed installer work separately authorized | Corresponding host operation |
| Actual stopped container IDs/inspect projections and controller/boot identity | Final plan/manifest sealing |
| Exact source hashes, sealed deployment SHA256, readback evidence | Execution approval |
| Explicit scope-specific staging and deployment-bound execution permissions | Respective boundary |

No identifiers, image paths, deployment hashes, credentials or approvals are
invented here. Previously observed identities must be revalidated if reused.

## Acceptance and retained evidence

Retain redacted exact commands/results, source and deployment hashes, inspect
snapshots, timestamps, image/interpreter/PID1 proof, socket authentication proof,
service/timer readbacks, durable journal/head, receipts and exit states, shutdown
logs, network-isolation configuration/audit scope, and baseline restoration
comparison (files, manager and kernel state; original containers/power unchanged).
Do not claim measured zero egress from configuration alone.

The normal case is accepted only with one synthetic slot, no second admission,
valid synthetic receipt/finalizer, actual zero exits, complete drain and exact
restoration, LIFECYCLE_PASS with terminal exit code 0, and timer disarm. Missing
or ambiguous evidence leaves the case unresolved, without automatic retry.
Fault cases need separately frozen proposals. Even a successful normal trial
would not change G6 FAIL, authorize paid execution, or close ORQ-41.

## Current stop point

Documentation complete; awaiting approval for step 1 only. No inventory, image
probe, staging, installation, lifecycle run, network/provider activity, Notion
operation or commit was performed while preparing this proposal.
