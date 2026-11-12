#!/bin/sh
# Run locally as matias, not through Codex. Installs bounded temporary access only.
# No CPU placement, service start, benchmark, provider or network operation.
set -eu
if [ "$(id -un)" != matias ]; then
    echo 'Run this script as matias in your local terminal.' >&2
    exit 1
fi
sudo /bin/sh <<'ROOT_INSTALL'
set -eu
umask 077
base=/var/lib/orq41-cpuset
rule=/etc/sudoers.d/orq41-cpuset-261110205521
source=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/recovery/admin_recovery.py
test ! -e "$base"
test ! -L "$base"
test ! -e "$rule"
test ! -L "$rule"
/usr/bin/mkdir -m 0700 "$base"
/usr/bin/install -o root -g root -m 0700 "$source" "$base/bootstrap-9025f392.py"
/usr/bin/printf '%s\n' '9025f3924dfcc49a6debbe82a835be0bd42e4e3eebeec9fb4f672d512742a2e6  /var/lib/orq41-cpuset/bootstrap-9025f392.py' | /usr/bin/sha256sum --check --status
/usr/bin/cat > "$base/access.sudoers" <<'RULES'
# ORQ-41 administrative drill 261110205521 only. Remove after recovery/verification.
matias ALL=(root) NOPASSWD: /usr/bin/python3 -I /var/lib/orq41-cpuset/bootstrap-9025f392.py prepare /var/lib/orq41-cpuset/261110205521
matias ALL=(root) NOPASSWD: /usr/bin/python3 -I /var/lib/orq41-cpuset/261110205521/helper.py apply /var/lib/orq41-cpuset/261110205521
matias ALL=(root) NOPASSWD: /usr/bin/python3 -I /var/lib/orq41-cpuset/261110205521/helper.py recover /var/lib/orq41-cpuset/261110205521
matias ALL=(root) NOPASSWD: /usr/bin/python3 -I /var/lib/orq41-cpuset/261110205521/helper.py verify /var/lib/orq41-cpuset/261110205521
matias ALL=(root) NOPASSWD: /usr/bin/tar -cf - -C /var/lib/orq41-cpuset 261110205521
matias ALL=(root) NOPASSWD: /usr/bin/rm -- /etc/sudoers.d/orq41-cpuset-261110205521
RULES
/usr/bin/chmod 0440 "$base/access.sudoers"
/usr/sbin/visudo -cf "$base/access.sudoers"
/usr/bin/install -o root -g root -m 0440 "$base/access.sudoers" "$rule"
/usr/sbin/visudo -cf "$rule"
/usr/bin/python3 -I - <<'SYNC'
import os
for path in ('/var/lib/orq41-cpuset/bootstrap-9025f392.py',
             '/var/lib/orq41-cpuset/access.sudoers',
             '/etc/sudoers.d/orq41-cpuset-261110205521',
             '/var/lib/orq41-cpuset', '/var/lib', '/etc/sudoers.d'):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
SYNC
echo 'ORQ41_TEMPORARY_ACCESS_INSTALLED — no CPU or service changes applied'
ROOT_INSTALL
