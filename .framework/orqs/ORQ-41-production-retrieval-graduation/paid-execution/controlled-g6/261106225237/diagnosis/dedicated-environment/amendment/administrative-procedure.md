# Temporary CPU placement procedure — draft, not executed or independently reviewed

Preparation authorized; host changes and benchmark execution are not authorized.
Host inventory: systemd255, Docker systemd cgroup driver, cgroupv2. Root
system.slice/user.slice/machine.slice/init.scope have empty AllowedCPUs and
StartupAllowedCPUs, effective0–31. Record a fresh baseline immediately before
any application; abort on drift. Current user scope cannot administer cpuset.

## Exact impact requiring operator approval

Moving user.slice to8–31 also moves the editor, Codex and desktop workloads.
Moving system.slice to8–31 also restricts Docker's default scopes and the four
currently running local containers: orq41-paid-pg, orq41-env-pg,
orq41-env-redis, orq41-env-otel. It changes their effective available CPUs even
without stopping/recreating them or editing their Docker resource configuration.
This is broader than creating a benchmark slice and is NOT covered by prior
no-source/service-change permissions. Do not apply unless the operator explicitly
accepts that temporary placement impact. If those services' effective placement
must remain untouched, this procedure is blocked on this host; use another target
after approval rather than silently weakening the isolation claim.

No service stop, kill, reboot, daemon restart, power change, DB write, workload
test, container creation or production change is part of this draft application.
IRQ/kernel activity is not eliminated. Managed-workload placement is not absolute
hardware isolation, and no successful p95 outcome is promised.

## Baseline and guard, before applying

Run from an administrator-controlled session and retain stdout/stderr plus exit
codes in a new procedure evidence directory. Inspect the active cgroup hierarchy
and all root-level populated groups. Confirm CPUs0–31 and the recorded SMT
topology. Verify enough housekeeping capacity and that no new production/service
workload has appeared. Reject any unaccounted root workload or changed baseline.

```sh
systemctl show -p ControlGroup -p AllowedCPUs -p EffectiveCPUs -p StartupAllowedCPUs system.slice user.slice machine.slice init.scope
systemctl list-units --type=slice --all --no-pager
docker info --format '{{.CgroupDriver}} {{.CgroupVersion}}'
docker ps --format '{{.ID}} {{.Names}}'
```

Retain the exact pre-existing runtime drop-ins/properties for every affected
unit, their hashes, and the current power profile. Confirm that
`/run/systemd/system/orq41bench.slice` and its unit do not already exist.
Do not proceed with partial inventory. The empty original AllowedCPUs values
below are specific to the observed baseline, not a generic restoration default.

## Application commands, only after exact-impact approval and procedure review

Create only this new runtime unit; exclusive file creation must reject collision:

```sh
sudo sh -c 'set -C; cat > /run/systemd/system/orq41bench.slice <<EOF
[Unit]
Description=Temporary ORQ-41 benchmark CPU placement
[Slice]
AllowedCPUs=0-7
EOF'
sudo systemctl daemon-reload
sudo systemctl start orq41bench.slice
sudo systemctl set-property --runtime user.slice AllowedCPUs=8-31
sudo systemctl set-property --runtime machine.slice AllowedCPUs=8-31
sudo systemctl set-property --runtime system.slice AllowedCPUs=8-31
sudo systemctl set-property --runtime init.scope AllowedCPUs=8-31
```

Check every command. A nonzero exit requires restoration of already applied
steps and preserved logs, not continuing to a benchmark. No recursive manual
sysfs writes, blanket systemctl revert or broad process migration scripts.

Future NEW benchmark containers must explicitly use
`--cgroup-parent=orq41bench.slice`, API `--cpuset-cpus=0,2`, PostgreSQL
`--cpuset-cpus=4,6`, unchanged2CPU/2GiB and isolated networking. These are future
harness changes, not permission to manually start an unreviewed container.
Redis/collector/controller remain in housekeeping placement, not the benchmark
slice. Existing containers are never moved into the new benchmark slice.

## Verification before any benchmark authorization/admission

```sh
systemctl show -p ControlGroup -p AllowedCPUs -p EffectiveCPUs orq41bench.slice system.slice user.slice machine.slice init.scope
cat /sys/fs/cgroup/orq41bench.slice/cpuset.cpus.effective
cat /sys/fs/cgroup/user.slice/cpuset.cpus.effective
cat /sys/fs/cgroup/system.slice/cpuset.cpus.effective
```

Require benchmark parent0–7 and all inventoried housekeeping units8–31. Inspect
each new container's real cgroup ancestry/effective cpuset, all its threads'
allowed CPU lists, image/resource/network identities and its parent's limits.
For all inventoried unrelated user processes/threads verify no allowed CPU
intersection with0–7; account for future child units and root-level exceptions.
Snapshot-only verification does not establish interval-wide exclusivity.
Define boundary checks/drift handling in the reviewed executable harness before
running it. Report kernel/IRQ residuals separately; do not call them absent.
Missing evidence or unexpected placement means NOT READY; no request admission.

## Restoration, also on partial application failure

First settle/stop admission of any future benchmark workers; never destroy
in-flight work. Once the new benchmark slice has no descendant workload, restore
only changes made by this procedure. For this exact empty-AllowedCPUs baseline:

```sh
sudo systemctl set-property --runtime init.scope AllowedCPUs=
sudo systemctl set-property --runtime system.slice AllowedCPUs=
sudo systemctl set-property --runtime machine.slice AllowedCPUs=
sudo systemctl set-property --runtime user.slice AllowedCPUs=
sudo systemctl stop orq41bench.slice
```

Before deleting the new runtime unit, verify its path/content hash equals the
one created by this procedure and no concurrent edit occurred. Delete only that
owned runtime file, then `sudo systemctl daemon-reload`. Do not use systemctl
revert: unrelated drop-ins must survive. If runtime property files existed
before, restore their exact captured contents as part of the reviewed admin
implementation; a property readback alone is insufficient to prove file parity.
If no prior files existed, remove only the exact new owned property fragments
after validating their contents and origins. Their actual paths must be captured
from systemd's writes; do not guess or glob-delete them.

Read back original AllowedCPUs/StartupAllowedCPUs/effective placement and power
profile, compare retained drop-ins, and confirm all four original containers
still run without restart. Leave operator EPPperformance unchanged. Any restore
mismatch is cleanup FAILED with exact residuals, not automatic baseline PASS.

## Remaining gate

This draft exposes commands and impact but is not a tested administrative tool.
Its application requires explicit shared-slice impact approval and independent
review, with exact runtime property-file ownership/restoration handling ready.
No 1440-request calibration authorization follows from host setup. G6FAIL and
paid admission block remain; no app/P5/accounting/model/threshold/.env change.
