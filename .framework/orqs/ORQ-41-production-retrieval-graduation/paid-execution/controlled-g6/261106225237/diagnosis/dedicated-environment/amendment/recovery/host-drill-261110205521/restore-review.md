# Independent operator-local restoration review

Result: **ADMINISTRATIVE_RESTORE_REVIEW_FINDINGS**. Static only; no host operation executed.

## RESTORE-R1 — HIGH: manual restoration cannot recover its own interruption

`restore-local.sh` exclusively creates manual-init-intent.json, then changes init.scope, exclusively creates manual-init-reset.json, unlinks the file, reloads and invokes original recovery. Re-entry always requires init.scope AllowedCPUs=8-31 and the original fragment, and again exclusively creates the same intent file. There is no state-reader/resume branch.

Reproduction by deterministic code walkthrough: terminate immediately after successful intent publication, before set-property. A rerun passes the same property checks but atomic_new(manual-init-intent.json) fails FileExistsError. Alternatively terminate after set-property reset: re-entry fails the initial AllowedCPUs=8-31 check; original watchdog/helper still rejects the transient drop-in path. A nonzero set-property after mutation or later readback/fsync/reload error has the same reachable problem. This can strand approved shared-slice restrictions while both automated and operator-local restoration refuse continuation. No live interruption was performed.

Minimum correction: read and validate an immutable manual action contract/journal under the existing maintenance lock; allow idempotent recovery of the exact three observed states (original recognized override, recognized reset override, absent override) with recorded ownership/identity witnesses. Journal each next step durably before mutation and completion afterwards. Validate exact known state before proceeding, reject unknown changes, never replay apply, and tolerate already-completed manual records only after validating their content. Include interruption/nonzero-after-mutation controls for every manual phase before asking the user to run the revised script. Keep original helper/journal immutable and finish through original recover_locked with full baseline verification and owned timer disarm.

Hash-verified helper import, sealed state/maintenance lock, exact transient-path/content checks, no-occupied-benchmark guard and final parity/delegation otherwise follow the intended narrow restoration boundary. No second confirmed B/H/M issue is reported here. Existing observed host incident is attributed to parent evidence; this reviewer did not run systemctl, Docker, SQL, sudo or privileged operations. This result neither changes helper source nor authorizes a benchmark.
