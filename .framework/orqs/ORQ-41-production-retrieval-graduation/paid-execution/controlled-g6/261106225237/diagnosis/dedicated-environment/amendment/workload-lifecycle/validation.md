# Workload lifecycle — author validation

Source-only validation; no systemd/Docker/DB operations and no host reservation.
All state-machine/host operations use deterministic doubles. JSON/SSE worker
integration uses a local ASGI stub. Unix IPC tests use AF_UNIX, not external TCP.

Latest author regression: **290 passed**, 0 failed/errors/skips, 13.478s.
Receipt: `regression-final.xml`. Independent review is recorded separately.

Exact command, from repository root (sandbox escalation permits local AF_UNIX;
`unshare -rn` still creates an empty network namespace and `env -i` removes credentials):

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 \
  APP_SETTINGS_ENV_FILE= AWS_CONFIG_FILE=/nonexistent \
  AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true \
  PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=41 \
  PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform \
  P2_NET_AUDIT_LOG=/tmp/orq41-lifecycle-final.log \
  .venv/bin/python -m pytest -q \
  tests/experiments/test_orq41_dedicated_lifecycle.py \
  tests/experiments/test_orq41_dedicated_environment.py \
  tests/experiments/test_orq41_blocked_latency.py \
  tests/experiments/test_orq41_aa_calibration.py \
  --junitxml=.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/workload-lifecycle/regression-final.xml
```

Coverage includes: STOP versus pending permit; lost acknowledgments; duplicate/
expired permits; wrong PID/starttime/run/worker; root socket identity and namespace
credentials; controller/boot/timer loss; late health checks; worker >240s; timeout
without cancellation; no forced API/PG kill; foreign child and active clients;
auxiliary shutdown failure; failed finalizer; JSON/SSE worker boundaries; head lag,
corruption, truncation, symlink and fsync failure; concurrent recovery; interrupted
restoration with its original clock; late drain proof; immediate recovery after
publication failure. The frozen population check proves 1440 slots/640 warmups,
not 1440 executed requests. No performance result is inferred from these tests.

Earlier observations retained, not erased:
- `focused-initial.xml`: 33 pass / 1 failure, AF_UNIX send denied by outer sandbox.
  Same credential-empty P2 command with sandbox escalation: `focused-p2.xml`, 34 pass.
- `regression-round1.xml`: 252 pass / 1 failure, original callback AST differed.
  Implementation moved the admission check into an outer wrapper; the contract
  assertion was preserved. No measurement callback assertion was weakened.
- `focused-round2.xml`: 50 pass; `regression-round3.xml`: 277 pass;
  `regression-round4.xml`: 286 pass.
- Independent LIFECYCLE-R1 reproduced cleanup-error loss across a crash.
  `ACTION_RESULT` now persists success/failure; an outcome-less intent is ambiguous
  and prevents PASS even after a later zero exit. Two regressions retain errors
  across restart and prove no repeated signal. Historical finding receipt retained.
- Independent preliminary review identified namespace peer authentication,
  watchdog-presence checking, finalizer exit accounting, head-lag routing and late
  drain proof issues. All were corrected in source and covered by focused tests;
  final independent review remains a separate receipt, not an author assertion.

`scope-check.json`: 505 protected files compared with the prior snapshot; only the
approved blocked controller/worker changed. Four stage diagnostic files match.
App/P5 and helper8064 match. The final P2 egress audit contains zero bytes/events.
No external/provider calls or spending; USD0. No live readiness claim.

A separate read-only P2 precondition capture is retained as `p2-validation.json`:
credential variables absent, sitecustomize guard loaded, no IPv4 routes and only
loopback IPv6 entries. The initial capture assertion incorrectly required the
IPv4 header line; this kernel returns an empty file for the isolated namespace.
Inspection identified that difference; the capture now rejects data routes while
accepting either empty/header-only output. No test, network guard or host command
was weakened, and no connection was attempted by this capture.

The author additionally reproduced a late-exit variant of LIFECYCLE-R1 in
`late-outcome-reproduction2.xml`: signal acknowledged, exit observed after30s,
then crash before restoration could erase the late outcome. Success is now durable
only after timely exit observation; a third regression retains that failure.
`late-outcome-reproduction.xml` is an earlier negative control where an unresolved
second-service signal already prevented PASS. Both receipts are retained.

Final regression also tests the approved30s graceful observation interval from
the signal acknowledgment, constrained by390s total; command duration is not
silently subtracted from that observation allowance. Historical rounds5/6 retain
288/289 passes before this final boundary test.
