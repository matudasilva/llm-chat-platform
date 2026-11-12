# Bounded administrative recovery remediation

Operator approval of temporary shared-slice CPU impact is recorded and remains
valid. No additional approval of that same impact is required. Host application
remains conditional on a technically reviewed, recoverable procedure. The manual
draft must not be executed while its recovery findings remain open.

## Exact necessary change surface

Implement a small host-administration helper and deterministic tests in this
environment evidence lane, outside app/, P5 and the benchmark runner. It must
support explicit prepare/apply/verify/restore/recover operations, not a general
command executor. Allow only the approved four AllowedCPUs properties and the
owned orq41bench.slice runtime unit. No benchmark, power write, service restart,
container migration/deletion, schema or runtime change.

## Durable baseline and per-operation journal

Before the first host write, create a private owned state directory on persistent
storage outside /run, with exclusive creation/locking and a fixed run identity.
Capture unit properties, FragmentPath/DropInPaths, exact existing runtime file
bytes/mode/owner/identity, effective cpusets, container identities/restart counts,
power profile and the approved action sequence. Refuse a changed inventory or
unknown existing override. fsync files and parent directories. Baseline failure
means zero host writes.

Before each mutation, append+fsync an INTENT containing its fixed allowed target,
before identity/hash and expected new bytes/value. Execute only that action,
then read back manager properties, effective cpuset and actual fragment paths/
content, append+fsync VERIFIED. Do not infer no mutation from a command's nonzero
exit or missing VERIFIED record. A write/verify/fsync error stops the apply path
and enters recovery; it never admits benchmark requests.

Before the first mutation, arm a separately privileged recovery service/watchdog
that survives loss of the modifying shell/agent session. Bind it to the root-owned
baseline/journal and fixed allowlist; verify that it is armed. Its lease, expiry,
drain policy and explicit disarm conditions must be reviewed prospectively.
Do not kill or destroy in-flight benchmark descendants on lease expiry: stop
admission, reconcile/drain, and report failed recovery if safe restoration cannot
complete. Normal shell traps alone do not handle SIGKILL or session loss.

For systemd255's runtime property implementation, verify its actual controlled
drop-in location and content against the fixed allowed property. Keep the exact
before snapshot even when absent. Do not guess the path after a crash or discover
ownership by glob deletion. Upstream unit.c writes drop-in priority50; local
runtime paths/content must still match the reviewed implementation and baseline.

## Recovery after exception, process death or restart

Acquire the same exclusive lock and validate the journal/hash/operation order
and baseline before any recovery mutation. Enumerate both VERIFIED and outstanding
INTENT records. Compare actual state with the exact before/expected-after states;
restore owned after states to before in reverse operation order. If actual state
matches neither, leave it untouched, fail closed and report the precise conflict.
Never treat an outstanding INTENT as proof that no host write happened.

Record/fsync restoration intentions and results as well; recovery must be
idempotent after a second interruption. Restore only approved owned changes;
preserve operator EPP and unrelated concurrent modifications. Refuse automatic
application replay or a new run from a partially recovered state. Do not stop an
occupied benchmark slice or discard its descendant workload: report NOT DRAINED.

## Complete final restoration barrier

After restoring/removing the owned runtime fragments and benchmark unit, perform
an explicit final systemctl daemon-reload. Then verify captured file parity,
manager AllowedCPUs/StartupAllowedCPUs, actual effective cpusets and original
container running/restart identities. Only that final barrier permits RESTORED.
Property reset followed by later file deletion without another reload is not
sufficient. Any mismatch leaves RECOVERY_FAILED with durable residual-state
evidence; do not claim baseline recovery from a command exit0 alone.

## Focused deterministic acceptance controls

Use temporary directory, fake systemd/filesystem and injected failures only:
baseline/fsync failure before writes; crash before/after every mutation and before
VERIFIED; nonzero command that already mutated; atomic file replacement; failure
during restoration and repeated recovery; corrupt/truncated journal; duplicate or
unknown operation; replaced/symlinked owned path; changed foreign fragment;
partial/new unit creation; occupied benchmark slice; manager/property/effective-
CPU mismatch; final reload missing/failing; unrelated drop-ins preserved; original
containers not stopped/restarted; successful exact baseline/file/property parity.
No host mutation is needed to prove these recovery transitions.

Complete source/procedure re-review before any authorized host application.
The shared-slice impact approval remains valid throughout this bounded work;
the1440-request A/A and paid campaign remain unauthorized/blocked.
