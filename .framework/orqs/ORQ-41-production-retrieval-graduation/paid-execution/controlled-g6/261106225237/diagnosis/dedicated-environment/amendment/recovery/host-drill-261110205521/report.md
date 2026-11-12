# Administrative drill: failed attempt, verified operator recovery, access revoked

**ADMINISTRATIVE_DRILL_FAILED_BASELINE_RESTORED_ACCESS_REVOKED**.
Independent retained-file restoration review: **RESTORATION_FINAL_EVIDENCE_REVIEW_PASS**.

The host is restored to the sealed baseline. This does not make the original
administrative drill PASS or establish environment readiness. Immutable helper9025
still has ADMIN-LIVE-R1 HIGH (wrong runtime path assumption for transient init.scope).
Do not rerun apply, installer or incident restore scripts from this closed run.

## Observed result

- Real sealed verify returned VERIFY_PASS after operator restoration and again
  immediately before access revocation.
- Final journal:51 valid hash-linked records, phase done, RESTORED then DISARMED;
  original16 records retained byte-identically. Apply indices0-3 had verification;
  index4 changed init.scope but failed readback. Manual durable init restore
  records reconcile that historical pending intent before the remaining reverse
  recovery. No application replay or new run occurred.
- Real readbacks18/18 PASS: four AllowedCPUs/StartupAllowedCPUs empty, kernel
  cpuset.cpus.effective0-31, original unit properties/drop-ins; benchmark slice
  inactive; all six controlled/observed runtime files absent, including the actual
  /run/systemd/transient/init.scope.d/50-AllowedCPUs.conf. Watchdog timer/service
  inactive/dead/not-found. This is inactivity proof, not automatic recovery PASS.
- Four pre-existing containers retain exact IDs, PIDs, start times, running status
  and RestartCount0. Governor/EPP profile unchanged.
- The exact temporary rule /etc/sudoers.d/orq41-cpuset-261110205521 was deleted
  after final verification; rm exit0 and lstat absence recorded. Root-owned
  helper/baseline/journal and known bytecode quarantine remain as evidence. The
  retained access.sudoers copy in private /var/lib is not an active sudoers rule.
- 505 protected files and4 stage technical files retain their earlier hashes.
  No app/runtime/P5/benchmark harness/model/threshold/accounting/schema/.env edit,
  restart, new container, benchmark request, provider call or paid spend. No Notion
  or commit. Host administrative actions used explicit authorization and local
  sudo; they are not claimed as P2 sandbox tests or campaign execution evidence.

## Failures retained and boundaries

The real apply failed because init.scope is Transient=yes, so systemd255 writes
its override in /run/systemd/transient instead of the assumed system.control
location. The watchdog/helper rejected the unrecognized path and could not
complete recovery. All four units remained temporarily restricted to8-31 until
the scoped operator recovery; the benchmark slice was empty throughout observations.

The first local restore import generated __pycache__, which the unchanged sealed
check correctly rejected before CPU restoration. The corrected script disables
bytecode before import and moves only the exact known root-owned bytecode artifact
into quarantine outside the sealed state, preserving evidence. Unknown bytes,
metadata, symlinks or collisions are rejected. Earlier failed scripts, archives,
review findings and commands remain retained. The helper source/seal guard was
never relaxed or modified during this drill/recovery.

The operator executed the corrected local recovery. Independent proof binds the
manual init reset/removal/final reload and the original helper's reverse recovery,
full baseline parity and disarming. Recovery PASS closes the host restoration
incident; it does not close the helper path defect or change the failed experiment.

## Validation commands and evidence

- Exact sealed prepare command: `sudo -n /usr/bin/python3 -I /var/lib/orq41-cpuset/bootstrap-9025f392.py prepare /var/lib/orq41-cpuset/261110205521` → PREPARED_NOT_APPLIED.
- Unprivileged `python3 -I execute-drill.py` on the host → FAILED, retained
  execution.json contains exact apply/recover/verify argv, returncodes and errors.
- Operator-local `sh restore-local.sh` → reported success, independently confirmed
  by sealed verify, root journal and actual post-recovery host state.
- Exact sealed verify: `sudo -n /usr/bin/python3 -I /var/lib/orq41-cpuset/261110205521/helper.py verify /var/lib/orq41-cpuset/261110205521` → VERIFY_PASS.
- Exact archive: `sudo -n /usr/bin/tar -cf - -C /var/lib/orq41-cpuset 261110205521` → preserved restored-journal.tar.
- Host read-only `python3 -I capture-restored.py` →18/18 PASS.
- Host `python3 -I revoke-access.py` → VERIFY_PASS, exact own-rule removal and
  absence; TEMPORARY_ACCESS_REVOKED.
- Correction validation from prior turn:11 focused author +11 independent tests
  PASS and212/212 helper/seal regression PASS under unshare -rn/env -i/no provider
  credentials. Those tests were not rerun after restoration because technical
  source was unchanged. This turn used offline archive replay and host readbacks.
- Distinct reviewer independently replayed51 records and manual records, checked
 18 readbacks and exact revocation receipts, and issued restoration review PASS.
  Reviewer made zero live host operations.

## Remaining next step

Propose the smallest administrative-only correction: capture per-unit Transient
state and freeze its exact supported runtime fragment path BEFORE apply, then use
that bound path for admission/readback/snapshot/recovery. Keep strict allowlists,
byte checks, locking, fsync, seal validation and no apply replay. Add transient and
non-transient path/crash controls and obtain independent source review before a
fresh administrative-only drill with a new identity. No new helper revision,
root grant or drill is implemented/authorized by this restoration closure.

Global In Progress / Implement / DECISION_FREEZE_PASS, P5 CLOSED, G6 FAIL and
paid admission BLOCKED_CONTROLLED_G6_FAIL remain unchanged. Environment not READY.
Task provider spend:USD0; zero benchmark/campaign requests or provider calls.

## Exact affected repository artifacts

Only planning/evidence artifacts in this ORQ were affected; unrelated dirty files
were preserved. The administrative scripts below run outside app/ and P5.

- `.framework/orqs/ORQ-41-production-retrieval-graduation/planning-status.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/session-handoff.md`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/administrative-status.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/access-review.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/access-review.md`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/access-revocation.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/apply.log`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/authorize-local.sh`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/capture-restored.py`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/execute-drill.py`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/execution.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/failed-journal.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/final-journal.tar`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/preflight.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/prepared-baseline.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/prepared.tar`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/recover.log`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restoration-final-review.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restoration-final-review.md`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restoration-scope-check.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restoration-verification.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restore-local.seal-failed.sh`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restore-local.sh`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restore-review-round2.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restore-review-round2.md`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restore-review-round3.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restore-review-round3.md`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restore-review.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restore-review.md`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restored-host-readback.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/restored-journal.tar`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/revoke-access.py`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/seal-failure-inventory.json`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/seal-failure-journal.tar`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/seal-independent-tests.xml`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/seal-regression.xml`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/seal-remediation.md`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/seal-tests.xml`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/test_restore_seal.py`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/verify.log`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/report.md`
- `.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/host-drill-261110205521/completion.json`
