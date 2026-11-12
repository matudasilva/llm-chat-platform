#!/bin/sh
# Operator terminal only: one sealed administrative drill, no sudoers grant.
# No workload, benchmark, provider, power or container start/stop command.
set -eu
cd "$(dirname "$0")"
mkdir operator-execution-261111015223
outdir=$(pwd)/operator-execution-261111015223
set +e
sudo /bin/sh > "$outdir/drill.log" 2>&1 <<'ROOT'
set -eu
umask 077
base=/var/lib/orq41-cpuset
state=$base/261111015223
bootstrap=$base/bootstrap-8064e669.py
source=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/transient-path-remediation/admin_recovery.py
/usr/bin/python3 -I -B - <<'CHECK'
import os,stat
from pathlib import Path
for path in (Path('/var'),Path('/var/lib'),Path('/var/lib/orq41-cpuset')):
    s=path.lstat()
    assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode & 0o022
assert stat.S_IMODE(Path('/var/lib/orq41-cpuset').stat().st_mode)==0o700
CHECK
test ! -e "$state"
test ! -L "$state"
test ! -e "$bootstrap"
test ! -L "$bootstrap"
/usr/bin/install -o root -g root -m 0700 "$source" "$bootstrap"
/usr/bin/printf '%s\n' '8064e669e1921475167fb70fb73d3746cb4c034fa02fe207c7ffa749346b2be2  /var/lib/orq41-cpuset/bootstrap-8064e669.py' | /usr/bin/sha256sum --check
/usr/bin/python3 -I -B "$bootstrap" prepare "$state"
set +e
/usr/bin/python3 -I -B "$state/helper.py" apply "$state"
apply_rc=$?
# Readback only; recovery follows even when apply/readback fails.
/usr/bin/systemctl show -pTransient -pAllowedCPUs -pEffectiveCPUs -pDropInPaths -pActiveState system.slice user.slice machine.slice init.scope orq41bench.slice
readback_rc=$?
/usr/bin/python3 -I -B "$state/helper.py" recover "$state"
recover_rc=$?
/usr/bin/python3 -I -B "$state/helper.py" verify "$state"
verify_rc=$?
/usr/bin/printf 'RESULT apply=%s readback=%s recover=%s verify=%s\n' "$apply_rc" "$readback_rc" "$recover_rc" "$verify_rc"
if [ "$apply_rc" -eq 0 ] && [ "$readback_rc" -eq 0 ] && [ "$recover_rc" -eq 0 ] && [ "$verify_rc" -eq 0 ]; then
    echo ORQ41_ADMINISTRATIVE_DRILL_COMMANDS_PASS
    exit 0
fi
exit 1
ROOT
result=$?
# Archive even a failed/partial attempt; never replay its apply.
sudo /usr/bin/tar -cf - -C /var/lib/orq41-cpuset 261111015223 > "$outdir/journal.tar" 2> "$outdir/archive.stderr"
archive_rc=$?
cat "$outdir/drill.log"
printf 'drill_exit=%s archive_exit=%s\n' "$result" "$archive_rc" > "$outdir/exits.txt"
if [ "$result" -ne 0 ] || [ "$archive_rc" -ne 0 ]; then
    echo 'STOP: retain logs; do not rerun apply. Recovery must be verified before any further work.'
    exit 1
fi
echo 'Evidence saved. Independent readback/replay remains required; no benchmark readiness claimed.'
