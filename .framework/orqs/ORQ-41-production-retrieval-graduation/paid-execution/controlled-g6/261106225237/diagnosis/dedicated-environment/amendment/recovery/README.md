# Bounded CPU-placement administrative recovery

This helper remediates ADMIN-R1/R2; it is not a benchmark launcher, environment
readiness claim, or G6 result. Do not execute the superseded manual draft.
The operator's existing shared-slice impact approval remains valid. This work
only implements/tests/reviews recovery; it does not apply CPU placement.

## Supported boundary

Only the observed empty AllowedCPUs/StartupAllowedCPUs/no-drop-in baseline is
supported, with effective CPUs 0-31 and an inactive, unconfigured benchmark slice.
All five controlled runtime files must be absent. Existing overrides, changed
preservation witnesses, unknown manager/file state, occupied benchmark descendants
or malformed journals stop automation. No foreign files are overwritten/deleted.
No governor/EPP, container, application, DB, P5, threshold or budget changes exist.

The five fixed apply operations are one runtime unit creation/start and the four
approved AllowedCPUs assignments. Each write-ahead journal index resolves to the
immutable action contract (fixed path, absent before-state, expected bytes/reset).
Hash-linked records are atomically published with file/directory fsync; incomplete
pending files are never interpreted as committed intent. No apply replay exists.
A whole-operation maintenance lock serializes this helper across run directories.

Completed file readbacks bind device/inode/owner/mode until the next owned mutation.
An outstanding mutation intent accepts only fixed before/after/reset states; under
this maintenance boundary another root administrator must not concurrently write
the same property, including identical bytes. Hostile root modification of a
sealed journal/helper is outside the model. Unknown changes fail closed and need
manual reconciliation; they are not repaired speculatively.

## Session-independent recovery

Preparation and arming require absence of BOTH watchdog timer and service. A
durable per-run token binds their transient descriptions; trigger and fixed
helper ExecStart are checked before accepting arming or stopping a timer. An
unknown homonym remains untouched, including an ambiguous creation failure. Every
pre-mutation arming check requires BOTH units, including the service executable;
only terminal recovery/disarm tolerates already absent owned units.

Before the first CPU/unit mutation, a systemd transient timer/service is armed:
300 seconds, AccuracySec=1s, service Restart=on-failure/RestartSec=10s, unlimited
start retries. It invokes the root-owned sealed helper using Python isolated mode,
not workspace code. Commands have bounded timeouts; the apply loop stops starting
new operations 60 seconds before lease expiry. No lease extension is implemented.
The service retries lock contention rather than depending on the initiating shell.

Recovery validates intent/operation order and current state, restores only the
owned changes in reverse order, refuses to stop an occupied benchmark slice, and
survives a second interruption. Final daemon-reload occurs after ALL file removal;
file/manager/effective CPU and original container identity/restart/power parity
must pass before RESTORED. Only then may the timer be disarmed. A repeated recover
verifies parity and performs no further changes. Do not manually disarm on failure.

This administrative drill admits no workloads. Future benchmark admission/drain
integration is separate and remains blocked. The transient timer survives session
loss/SIGKILL, not a reboot. Runtime changes disappear on reboot, while persistent
state prevents a new preparation until explicit recovery verifies parity; changed
container/reboot witnesses require manual reconciliation. There is no auto-apply.

## Root installation / later host validation (NOT executed)

After independent source review, an administrator must verify the exact reviewed
helper SHA256, copy it to a root-owned staging file, verify that copy again, and
run that sealed staging copy with Python `-I`. Never execute a writable workspace
helper as root. `/var/lib/orq41-cpuset` must be root-owned mode0700, on persistent
local storage, with non-writable, non-symlink root-owned ancestors. `prepare` fsyncs
the ancestry and installs a per-run immutable helper/baseline/action contract.

Prepare accepts only `/var/lib/orq41-cpuset/<12-digit-run-id>` and refuses existing
or unrecovered runs. Use the installed run's helper.py for all later actions:
`apply`, `recover`, `verify` (verify means restored baseline, not applied placement).
Sealing checks owner/mode/path and helper hash. No deployment/application commands
were executed as part of the deterministic correction. Live timer creation,
systemd255's exact generated fragment bytes/path, actual cpusets, root exceptions
and restoration must be validated in an administrative-only drill before any
benchmark readiness claim. A byte/path mismatch aborts apply and leaves recovery
blocked on that precise unknown state; it does not grant permission to delete it.

## Validation

Run `sh run-tests.sh` from this directory (or pass its full repository path).
The script uses `unshare -rn`, a scrubbed environment and no app pytest fixtures.
Only a fake backend/temp files are used. Earlier XML receipts are retained,
including the second draft's test-message mismatch (53 PASS/1 FAIL), corrected
by expecting the new earlier ownership guard. No host/systemctl/Docker commands,
provider calls, DB connections, benchmark requests or paid spend occur in tests.
