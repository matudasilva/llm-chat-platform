# Dedicated binding source validation

## Scope

Opt-in packet identity; strict profile/placement evidence; API/probe parent
arguments; pure PostgreSQL create command; preparation/execution hard barrier.
`aa_calibration.py`, resource and worker helpers remain unchanged to preserve
historical reviewed hashes. The PostgreSQL command builder is connected to the optional bound provisioner,
but preparation, execution and that provisioner each reject bound requests before
I/O: populated-slice recovery is not approved. All provisioning-command tests
replace Docker with a recording double; none creates a container.
The before/after PG hooks do not attest a not-yet-running API worker. The generic
checker can attest a running API with doubles; a real pre-admission handshake is
still part of the future lifecycle integration. Do not infer executable readiness.
No legacy manifest or approval was edited to accept changed source hashes.
Existing exact source checks still invalidate old executable receipts as intended.

## Validation history

- Focused:49 passed in1.57s, credential-free empty network namespace.
- Initial combined command:199passed/11failed in7.70s. Missing PYTHONPATH meant
  existing subprocess checks could not find the P2 guard. Failure XML retained
  as regression.xml. No source fix or test weakening for these failures.
- Corrected command below:210passed/0failed in9.63s. P2 guard loaded, audit log
  absent/empty. No external/provider operation, actual Docker or DB operation.
- Real host read-only filesystem inspection confirmed cgroup.events is absent at
  root. New fixture reproduces that layout; reader derives root population from
  task/descendant inventory and requires events for each non-root cgroup.

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 \
  APP_SETTINGS_ENV_FILE= AWS_CONFIG_FILE=/nonexistent \
  AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true \
  PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=41 \
  PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform \
  P2_NET_AUDIT_LOG=/tmp/orq41-dedicated-binding-network-complete.log \
  .venv/bin/python -m pytest -q \
  tests/experiments/test_orq41_dedicated_environment.py \
  tests/experiments/test_orq41_blocked_latency.py \
  tests/experiments/test_orq41_aa_calibration.py \
  --junitxml=.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/harness-binding/regression-complete.xml
```

No application/P5/runtime/SQL/schema/grants/model/threshold/accounting change,
no cpuset writes, service starts/stops, campaign, benchmark, Notion or commit.
G6 FAIL/paid block unchanged. Source review is separate from execution approval.

## Review remediation and final scope

Round1 found BINDING-R1: empty shared cgroups could contradict manager CPU masks,
and root mask was not pinned. Require manager/kernel agreement even when empty,
root0-31 and child-mask inclusion in its observed parent; reject duplicate tasks.
Five focused regression cases cover these contradictions. Retain round1 findings.

Final author suite:216passed, including55 new focused controls and161 existing
blocked A/A/resource controls. Independent final review is retained separately.
The existing worker measurement loop and historical helper hashes are unchanged.
Only optional controller packet/command/checker support was added. The new module
is pinned even for legacy packets because the controller imports it; unchanged
legacy protocol/resource behavior is tested, but old source-review receipts do
not authorize this modified controller. They remain immutable and fail exact
source checks; a new executable packet/source review is required later.

Exact technical files added/changed:
- experiments/production_graduation/gate_validation/blocked_latency.py (changed)
- experiments/production_graduation/gate_validation/dedicated_environment.py (new)
- tests/experiments/test_orq41_dedicated_environment.py (new)

Evidence: harness-binding/authorization.json, implementation.json, validation.md,
focused.xml, regression.xml (initial invocation failure), regression-p2.xml,
regression-final.xml, regression-complete.xml and independent review receipts.
Planning: planning-status.json and session-handoff.md only. The earlier proposal
and all historical administrative/measurement records are preserved.
