"""One authorized administrative drill, via the exact sealed helper commands.

Run unprivileged on the host. Root mutations remain inside reviewed helper.py.
No workload, network, provider, database, power or benchmark command exists here.
"""
import datetime
import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
STATE = '/var/lib/orq41-cpuset/261110205521'
HELPER = ['sudo', '-n', '/usr/bin/python3', '-I', STATE + '/helper.py']
result = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'requests': 0, 'provider_calls': 0, 'spend_usd': '0', 'operations': []}
start = time.monotonic()


def call(name, argv, binary=False):
    then = time.monotonic()
    item = {'name': name, 'argv': argv, 'elapsed_start_s': then - start}
    result['operations'].append(item)
    try:
        with (HERE / (name + ('.tar' if binary else '.log'))).open('xb') as output:
            proc = subprocess.run(argv, stdout=output, stderr=subprocess.PIPE, timeout=180)
        item.update(returncode=proc.returncode, stderr=proc.stderr.decode(errors='replace'))
        return proc.returncode == 0
    except Exception as error:
        item.update(error=type(error).__name__ + ': ' + str(error))
        return False
    finally:
        item['duration_s'] = time.monotonic() - then


def archive(name):
    return call(name, ['sudo', '-n', '/usr/bin/tar', '-cf', '-', '-C',
                       '/var/lib/orq41-cpuset', '261110205521'], binary=True)


try:
    applied = call('apply', HELPER + ['apply', STATE])
    result['applied'] = applied
    if applied:
        call('applied-units', ['/usr/bin/systemctl', 'show', '-pAllowedCPUs',
             '-pStartupAllowedCPUs', '-pEffectiveCPUs', '-pFragmentPath', '-pDropInPaths',
             '-pActiveState', '-pControlGroup', 'system.slice', 'user.slice',
             'machine.slice', 'init.scope', 'orq41bench.slice'])
        call('applied-watchdog', ['/usr/bin/systemctl', 'show', '-pLoadState',
             '-pDescription', '-pTransient', '-pExecStart', '-pTriggers',
             '-pActiveState', '-pTimersMonotonic', '-pRestart', '-pRestartUSec',
             'orq41-cpuset-recovery-261110205521.timer',
             'orq41-cpuset-recovery-261110205521.service'])
        archive('applied-journal')
finally:
    # An ambiguous apply outcome must still enter recovery; never retry apply.
    result['recovered'] = call('recover', HELPER + ['recover', STATE])
    result['verified'] = call('verify', HELPER + ['verify', STATE])
    archive('final-journal')
    result['duration_s'] = time.monotonic() - start
    result['status'] = ('ADMINISTRATIVE_DRILL_COMMANDS_PASS'
                        if result.get('applied') and result['recovered'] and result['verified']
                        and all(op.get('returncode') == 0 for op in result['operations'])
                        else 'ADMINISTRATIVE_DRILL_FAILED')
    with (HERE / 'execution.json').open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result, indent=2))

raise SystemExit(0 if result['status'] == 'ADMINISTRATIVE_DRILL_COMMANDS_PASS' else 1)
