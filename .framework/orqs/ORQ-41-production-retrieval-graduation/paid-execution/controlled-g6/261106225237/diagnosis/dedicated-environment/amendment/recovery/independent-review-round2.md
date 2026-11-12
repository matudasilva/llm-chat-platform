# Independent administrative recovery review — round 2

Result: **ADMINISTRATIVE_RECOVERY_REVIEW_FINDINGS**.

The original foreign-watchdog disarm defect is addressed by prospective absence checks, durable ownership token, transient-unit description/trigger/executable checks and ownership-checked disarm. Original round-1 artifacts remain unchanged.

## RECOVERY-R2 — HIGH: armed admits a missing recovery service

`admin_recovery.py:417–422`: `armed()` calls `verify_owned_watchdog()` with its default `pair_required=False`. A timer carrying the correct token and trigger is accepted when the associated service is absent, provided is-active succeeds. `apply()` trusts this result immediately before each CPU mutation. Initial `arm()` does require the pair, but subsequent admission checks do not maintain that invariant. Loss of the service after initial readback is therefore not rejected by the guard.

The retained pure `independent_missing_service.py` uses the actual `Systemd.armed` implementation, a real prepared manifest and an owned active timer with `service=None`. The only subprocess operation is replaced by an asserting fake. The method returns True. No systemctl or host operation occurs. This proves the adapter's accepted-state defect; it is not a live demonstration of systemd losing a unit.

Minimum correction: before accepting an active timer as armed for application, require its correlated recovery service and validate its exact ownership/executable. Absent units can remain tolerated when deciding that a fully absent watchdog is unarmed or when completing idempotent disarm. Do not simply require a pair for all terminal checks, which must still accept both units absent. Add tests for missing service after initial successful arming and before a later CPU operation, verifying no next mutation, plus absent-both terminal recovery and foreign/incomplete units.

## Executed validation and limits

Independently ran the frozen current 198 deterministic tests under `unshare -rn env -i`, pytest plugin autoload disabled, no app fixtures: 198 PASS in 17.62 seconds. The missing-service probe passed separately under the same isolation. XML and source hashes are retained. Reviewed current README and run-tests.sh; they correctly separate fake/source validation from future sealed privileged installation and real administrative drill.

Strict systemctl show exit-code handling can safely block discovery of a missing unit on a real deployment. That must be resolved/verified before live readiness, not waived using fake tests. It does not make this accepted-state guard correct for a backend discovery returning an absent service. No live readiness, benchmark permission, hardware exclusivity or G6 result follows from this review. No host, Docker, SQL, network/provider, API, app/P5 or source changes were performed.
