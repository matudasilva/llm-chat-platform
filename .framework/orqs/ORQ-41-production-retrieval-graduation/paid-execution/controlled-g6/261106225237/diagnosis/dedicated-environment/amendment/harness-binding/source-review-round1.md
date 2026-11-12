# Independent dedicated-binding source review — round 1

Result: **DEDICATED_BINDING_SOURCE_REVIEW_FINDINGS**. Source increment only; hard execution barrier remains intact.

## BINDING-R1 — MEDIUM: contradictory kernel/systemd masks accepted

`dedicated_environment.py:168–188` validates shared systemd EffectiveCPUs and cgroup inventory independently. A shared group with populated=false/tasks=[] bypasses the housekeeping-mask check. Starting with the actual focused-test proof, set groups['/system.slice'] to effective_cpus0-31/populatedfalse/tasks[] while units['system.slice'].EffectiveCPUs remains8-31: validate_snapshot returns success. Independently set groups['/'].effective_cpus8-31 while owned descendants still have0,2/4,6: it also returns success, though descendants cannot have CPUs excluded by their root ancestor. Both pure reproductions passed under unshare -rn/env-i/P2 guard, no host operations.

Impact: the proposed strict readback validator accepts contradictory or drifted evidence instead of failing closed. The current unconditional bound execution barrier prevents live admission/provisioning, so this is a checker correctness finding, not an observed live bypass.

Minimum fix: correlate each shared and benchmark group mask with its matching unit EffectiveCPUs regardless of population, require pinned root effective0-31, and reject impossible parent/descendant mask relationships where present. Add regressions for empty shared-group drift, root mask contradiction and healthy equivalent textual masks. Keep barrier and all immutable identity checks intact.

Reviewed binding/source pins, legacy path compatibility, provision/prepare/execute barriers and pure PG command construction. The PG provisioner and API worker handshake remain deliberately unwired/blocked pending separately approved lifecycle design; this review does not mistake them for execution-ready implementation. No second confirmed B/H/M is reported in this round. No source changes, host/DB/Docker/API/provider/network operations were made. Focused independent test result is retained separately; broader author210 controls are parent-executed evidence, not an independent reviewer rerun.

Independent focused execution:49PASS in1.63s, three pytest config warnings because plugin autoload was disabled (asyncio fixture scope, asyncio_mode, timeout). XML independent-focused-round1.xml records all cases; no async cases are present in this focused module. Full regression was not independently rerun after the finding.
