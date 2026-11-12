# Independent administrative recovery review — round 1

Result: **ADMINISTRATIVE_RECOVERY_REVIEW_FINDINGS**. No host application is approved by this review.

## RECOVERY-R1 — MEDIUM: foreign watchdog is stopped after rejected collision

`admin_recovery.py:375` rejects an already-active timer, but `apply` has already appended ARM_INTENT and catches this rejection by calling `recover_locked` (lines 243–258). Recovery has no CPU intents, executes FINAL_RELOAD, and unconditionally calls `disarm` (lines 298–301), whose line 385 stops the timer solely by name. Neither baseline nor manifest establishes timer/service ownership. A direct recover of a PREPARED state has the same problem. Checking `is-active` is not a transient-unit identity contract.

The retained `independent_timer_collision.py` injects only a fake backend, with the production arm precondition restored (the author's Fake.arm omits it). A foreign active timer exists before prepare; apply raises `Existing recovery timer`, yet the timer becomes inactive, backend calls are exactly `reload, disarm`, and the durable journal reaches done. No host commands are executed. This violates the fixed owned-mutation boundary and could disable another recovery mechanism. No CPU mutation occurs in this particular reproduction.

Minimum correction: capture absence of both prospective timer and service in preparation/admission; bind an immutable unique ownership token and exact recovery service/timer contract to durable state. Validate observed ownership before accepting arming and before stopping anything. Recover ambiguous systemd-run failures only when readback proves an owned transient unit; leave unknown units untouched and report conflict. Tests must include active timer, inactive pre-existing timer, existing service, creation nonzero before/after mutation, wrong token/ExecStart/trigger, and missing/changed units. Do not weaken the runtime-file safety checks.

## Verification and limits

Independent static review covered the current journal/action contract, witnesses, reverse restoration, fake failure matrix and sealed CLI. Independently reran all 190 deterministic controls under `unshare -rn env -i`, no pytest plugins or app fixtures; 190 passed (17.69 seconds), XML retained as independent-round1-tests.xml. The separate counterexample also passed under the same network namespace/scrubbed-environment boundary. Source was not modified. No systemctl, Docker, SQL, API, provider, host writes or benchmarks were executed. All effects are fake state/temp files.

No second confirmed B/H/M finding is reported in this round. Passing fake controls does not validate real systemd fragment format, timer creation, privileged deployment, host recovery, hardware exclusivity, environment readiness or performance. Those remain separate prerequisites. Existing shared-slice impact approval is acknowledged; it does not waive this technical ownership defect. App/P5/harness/model/thresholds are unchanged.

Test provenance: the independent 190-test run used the test source hash `a0e21aa483dd040fcbac7865d3101f5107b7c6502fa6eaa5676377b62c81c2d1` observed immediately around execution. The author subsequently appended three adapter controls; current test hash is `c55ed2b5faf0f72a222bece48e7b502c252f9885588a079237f633124e82d104`. Those three additions were not independently rerun. The reviewed production helper hash remained unchanged.
