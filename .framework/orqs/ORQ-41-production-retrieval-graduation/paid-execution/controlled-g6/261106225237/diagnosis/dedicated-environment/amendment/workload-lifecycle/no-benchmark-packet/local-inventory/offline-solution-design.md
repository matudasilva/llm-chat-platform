# Offline staging solutions — bounded design for review

Status: OFFLINE_DESIGN_ONLY; not implemented, staging/probe not authorized.
The user approved offline preparation and review after the inventory. This
increment adds no executable code and performs no live tests or host operations.
Existing 26-PASS evidence covers the adapter only, not this new design.

## 1. Controller access without changing the shared parent

Keep `/var/lib/orq41-cpuset` root:root 0700 and preserve all existing runs. Do not
use chmod/ACL on that parent, move the sealed root, make the controller root,
or expose private plan/inspect data through a world-readable copy.

A new narrowly scoped launcher is required. During separately authorized
installation it opens the **fresh run's receipts directory only**, relative to
verified directory descriptors with O_DIRECTORY|O_NOFOLLOW (O_PATH is sufficient
for the retained receipt directory descriptor). Verify device/inode, owner1000,
group1000, mode0700 and nonsymlink ancestry. Keep the descriptor open for the
entire controller lifetime. The controller passes `/proc/self/fd/<receipt_fd>`
to the unchanged synthetic controller receipt reader. That path addresses the
already-open directory without traversing the shared 0700 parent. Final receipt
components still use the reviewed O_NOFOLLOW reader and exact content checks.
No receipt symlink, copy, privileged file-read endpoint or new public mount is
needed. This is a proposed Linux descriptor-based access method, not a live proof.

Before dropping identity, the child must drop every supported capability from
the bounding set with PR_CAPBSET_DROP while it still has the required authority,
clear inheritable/ambient capabilities, and disable keep-caps. It must then clear
supplementary groups and set all real/effective/saved GIDs and UIDs to1000.
After the permanent credential drop, set PR_SET_NO_NEW_PRIVS to1. Verify through
/proc/self/status that NoNewPrivs is1 and CapInh, CapPrm, CapEff, CapBnd and CapAmb
are all zero; verify all UID/GID slots and empty supplementary groups. Any failed
operation or nonzero readback aborts before loading controller/lifecycle code.
Retain only the allowlisted receipt/control descriptors before any controller
or lifecycle module code runs. No arbitrary environment, Python search path,
repository imports or external credentials are inherited. Set cwd to `/` and
umask077. Execute only previously read and hash-verified core/controller bytes
after the drop; set the controller module's existing `life` global to that core.
This avoids reopening source paths beneath the inaccessible parent. It is new
launcher composition, not a change to reviewed lifecycle or adapter source.

The parent must pin the launcher's own bytes through a separate approved
installation manifest before executing it; the later deployment cannot
retroactively authorize a bootstrap program that already ran. Keep the existing
five-file deployment allowlist unchanged. New launcher/installer identities
also enter the plan's harness pins and independent review record.

### Persistent identity and the sealing order

A controller process must exist before its PID/starttime can enter the final
manifest. A dormant child waits on an inherited private pipe after privilege
drop; the installer records actual PID/starttime/UID/GID and verifies it directly
from `/proc`. The child survives unchanged through plan sealing and lifecycle
completion; no exec-to-shell, replacement PID or inferred inventory PID is used.

After the exclusive final plan/manifest writes and readback, the installer sends
bounded canonical plan bytes plus their pinned digest over the inherited pipe.
The child validates the digest and bound identity, then waits for the separately
authorized supervisor's trusted descriptor. EOF, a changed identity, malformed
frame or deadline expires the controller; it must not be automatically restarted
or replaced inside the same sealed run. A concrete bounded preparation lease
and shutdown policy must be part of the launcher implementation/review; the
7200s lifecycle reservation starts only through the existing supervisor.

Launching this dormant process is a **new, explicit staging-scope exception** to
the prior “no service starts” wording. It is not authorized now. The final
staging approval must name the persistent launcher unit, exact sealed command,
private transport and lease. No PostgreSQL/auxiliary/worker or supervisor starts
are allowed during this preparation phase. Do not silently broaden old approval.

### Inspection without granting Docker access to the child

Dropping supplementary groups may remove Docker socket access; retaining an
inherited Docker socket would grant excessive authority. Do neither. A future
fixed broker in the already-privileged launcher may service only an `inspect`
request for the single worker ID read from its own sealed manifest. It must
compare the entire frozen projection, apply reviewed read_state checks, and
return only running/exit_code to the child. It accepts no caller-supplied ID,
path, command, API URL or operation. It cannot start/stop/create/delete or signal
finish. Each request and process wait is bounded; uncertain results abort the
controller and leave recovery to the independent supervisor. This broker is new
privileged code and requires implementation tests and independent review before
approval. The existing read_state/projection behavior is reused unchanged.

## 2. Exclusive sealed installation transaction

The future installer must be a fixed one-run operation, not a shell dispatcher
or a chmod/copy recipe. It consumes a separately reviewed preparation manifest
with exact source hashes, destinations, identities and allowed modes. No source
or run path may be chosen through a generic user-supplied command.

1. Verify root execution, fixed state parent, nonsymlink root-owned ancestors,
   unchanged approved source bytes and empty/collision-free proposed run name.
   Use directory-relative nofollow/exclusive operations, not a check-then-copy
   sequence. Reject an existing run. Parent collision checks require authorized
   root reads; the inventory did not establish them.
2. Create only the new run and its journal/synthetic/receipts directories with
   specified ownership and modes. Fsync each directory and parent. No parent
   permission change, public lifecycle directory creation or old-run write.
3. Install exact approved launcher, adapter, bootstrap and core bytes with
   O_CREAT|O_EXCL|O_NOFOLLOW. Check regular-file type, link count1, ownership,
   modes, lengths and hashes; fsync files and parents. Do not execute repo paths.
4. Create the dormant controller as described above only under its separately
   explicit staging permission. Stage only the approved stopped containers;
   capture their actual IDs and full private projections. No credentials or
   unrestricted inspect projections may reach public review logs.
5. Use the existing offline authoring utility to bind the actual controller,
   boot, worker/sample, source and owned-container identities. Create final
   plan, manifest, deployment, source review and empty journal files exclusively.
   Separate presealed sources from final files; do not rerun the full preparation
   payload blindly over already-created files. Read back every byte/owner/mode.
6. Record a completion receipt with exact source/deployment hashes and actual
   IDs; release the child from its preparation wait only after successful
   readback. **Do not create execution-authorization.json.** Keep that operator
   authorization as a later deployment-bound action under separate approval.

Any partial failure leaves the new run and created resources for reconciliation;
no overwrite, recursive deletion, repair-by-retry, blanket kill or inferred
success. If the waiting controller has exited, the bound manifest cannot be
reused with another process. The installer must record the incomplete stage
without rewriting sealed evidence. Resource creation and retention need an
explicit disk quota/limit policy in the executable packet; available free space
alone is not a limit. This specification is not an implemented installer.

## 3. Exact worker command and mount ordering

`offline-worker-create-variants.json` refines the retained request from
`staging-packet.json` without changing that historical inventory artifact.
The strict variant explicitly sets BindOptions.CreateMountpoint=false on every
bind; the conditional legacy variant uses HostConfig.Binds instead. Neither
variant is selected or executable. Each body
must set Entrypoint exactly to [`/usr/local/bin/python3`, `-I`, `-B`] and Cmd
exactly to the three approved worker/plan/receipt arguments. The Docker CLI
entrypoint-plus-positional-flags draft is superseded. Bind the actual API request
version/transport to the installed daemon at implementation time; never guess an
API version or send the request in this offline increment. Accept exactly the
expected create success and a full returned ID, then verify the frozen inspect
projection. Timeout/ambiguous creation does not permit resending the POST.

The public directory `/run/orq41-lifecycle/<run>` must remain absent until the
unchanged host helper creates it. The worker must nevertheless exist stopped
before the supervisor validates ownership. The API draft's HostConfig.Mounts
may validate absent bind sources too early; its behavior has not been tested.
Setting CreateMountpoint=true or precreating the public directory would break
the helper's exclusive mkdir contract and is not a solution.

The smallest candidate is a **legacy HostConfig.Binds** specification with the
same three source/destination/mode pairs. Its acceptance is conditional: creation
must preserve an absent public source and the inspect projection must already
match the final expected mounts, without a subsequent container update. Starting
must occur only after the helper has created and authenticated the real public
directory. Do not start a worker if the source is missing, changed, symlinked or
has wrong ownership/mode; never rely on implicit directory creation at start.

No installed Engine source or retained runtime evidence was consulted to prove
those timing properties. Thus legacy Binds is a proposed compatibility strategy,
not a verified fix. Keep both API variants as distinct drafts; do not silently
switch between them after approval. A separately approved metadata-only create
probe (absent source beneath a fresh disposable test path, no container start)
is needed to decide it. Record source absence before/after, returned ID and exact
inspect mounts; retain the stopped test container. A source created early,
rejection, incomplete mount projection or ambiguous result fails this strategy.
No existing public lifecycle path may be used for that probe. Its exact fresh
path/name and immutable image must be frozen before requesting execution approval.

If the timing/inspect checks fail, stop. Do not change host_helper.mkdir behavior,
remove the stopped-worker precondition, fake IDs, revise reviewed lifecycle code,
or substitute a late-created worker. An explicit design amendment would then be
required. Socket/PID1/image integration still needs the separate normal trial.

## Required focused verification before implementation is accepted

New launcher/installer code, if authorized in a later increment, needs only
focused tests: nofollow/exclusive creation and partial failure, source/mode/hash
mismatch, parent0700 receipt access through a retained descriptor after privilege
drop, empty supplementary groups/no retained Docker handle, immutable controller
PID binding, bounded pipe/broker frames and timeout, foreign worker/inspect drift,
no authorization generation, and exact API Entrypoint/Cmd/mount serialization.
Use temporary fixtures and P2; mark real privilege-drop/daemon integration as
unexecuted unless separately authorized. Do not claim mocks prove kernel or
Engine behavior. Reuse previous 26 tests without presenting them as coverage of
new privileged code. No tests are run by this document-only increment.

## Approval boundary and deliverables

This design resolves the intended access and command shape on paper while
exposing the new launcher/broker and dormant-process scope explicitly. It does
not close runtime mount ordering, implementation, or live authorization gaps.
Next implement/test/review only these isolated installation/launching seams if
approved; separately freeze any metadata/image probe for live approval. Do not
mix source implementation, staging, execution and paid-admission approvals.
G6 remains FAIL; paid execution remains BLOCKED; P5 and reviewed sources remain
unchanged. No ORQ closure or execution readiness is claimed.
