"""Revoke only this drill's temporary sudoers rule after verified restoration."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

HERE = Path(__file__).resolve().parent
RULE = Path('/etc/sudoers.d/orq41-cpuset-261110205521')
STATE = '/var/lib/orq41-cpuset/261110205521'
proof = json.loads((HERE / 'restoration-verification.json').read_text())
readback = json.loads((HERE / 'restored-host-readback.json').read_text())
assert proof['phase'] == 'done' and proof['final_restored'] and proof['final_disarmed']
assert hashlib.sha256((HERE / 'restored-journal.tar').read_bytes()).hexdigest() == proof['archive_sha256']
assert readback['status'] == 'RESTORED_HOST_READBACK_PASS' and all(readback['checks'].values())
result = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'rule': str(RULE), 'operations': []}
try:
    try:
        metadata = RULE.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None:
        assert stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
        assert stat.S_IMODE(metadata.st_mode) == 0o440
        for name, command in (
            ('verify_before_revocation', ['sudo', '-n', '/usr/bin/python3', '-I',
                STATE + '/helper.py', 'verify', STATE]),
            ('remove_exact_temporary_rule', ['sudo', '-n', '/usr/bin/rm', '--', str(RULE)]),
        ):
            p = subprocess.run(command, capture_output=True, text=True, timeout=30)
            result['operations'].append(dict(name=name, argv=command, returncode=p.returncode,
                                              stdout=p.stdout, stderr=p.stderr))
            if p.returncode:
                raise RuntimeError(name + ' failed; no subsequent operation attempted')
    try:
        RULE.lstat()
        raise RuntimeError('Temporary rule still present')
    except FileNotFoundError:
        result['rule_absent'] = True
    result['status'] = 'TEMPORARY_ACCESS_REVOKED' if metadata else 'TEMPORARY_ACCESS_ALREADY_ABSENT'
except Exception as error:
    result['status'] = 'TEMPORARY_ACCESS_REVOCATION_FAILED'
    result['error'] = type(error).__name__ + ': ' + str(error)
finally:
    with (HERE / 'access-revocation.json').open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result, indent=2))
raise SystemExit(0 if result.get('rule_absent') else 1)
