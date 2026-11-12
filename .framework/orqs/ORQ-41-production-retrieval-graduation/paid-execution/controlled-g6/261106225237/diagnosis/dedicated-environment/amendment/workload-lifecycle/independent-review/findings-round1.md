# Independent lifecycle source review — cleanup crash finding

Status: **DEDICATED_LIFECYCLE_SOURCE_REVIEW_FINDINGS**. No executable packet or live readiness is reviewed.

## LIFECYCLE-R1 — MEDIUM: crash erases cleanup failure and permits PASS

In Supervisor._recover, a graceful_stop exception sets only local errors=True. The journal retains ACTION intent but no outcome/error until RESTORE_BEGIN much later. If the process dies before that record, recovery initializes errors=False. Already-stopped services are skipped, so the previous failed/ambiguous action is forgotten and LIFECYCLE_PASS can replace the no-crash FAILED disposition.

Pure P2 reproduction retained in cleanup_error_restart.py: complete both synthetic request permits and mark API exited. PG signal sets runningFalse then raises TimeoutError (lost reply after delivery). Without interruption recover→FAILED. In the second scenario Redis stops then raises BaseException to simulate process death before RESTORE_BEGIN. Restart using the same durable journal and actual stopped-state fake evidence yields LIFECYCLE_PASS. Both branches were actually executed under unshare-rn/env-i/P2 guard and passed the counterexample assertions. No host or actual service signal occurs.

Minimum correction: durably record each action result/error before advancing, or conservatively mark any ACTION lacking a durable successful result ambiguous/failed on recovery. Persist the aggregate failure disposition across restarts, never resend an uncertain signal, and keep safe observed-empty CPU restoration separate from terminal PASS. Add exact interrupted and non-interrupted paired regression.

The previously reported namespace authentication, watchdog-health, restart head-lag routing and late drain-proof corrections were re-inspected; no regression finding is asserted for them in this round. The hard execution barrier remains. Full regression was not independently rerun after this new counterexample; author286PASS is author evidence, not a reviewer run. No source edits or host/Docker/SQL/API/provider/network operation were performed.
