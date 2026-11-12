"""Read-only host proof after operator recovery. No workload or provider calls."""
import datetime
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
baseline = json.loads((HERE / 'prepared-baseline.json').read_text())['data']['baseline']
result = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'read_only': True, 'units': {}, 'watchdog': {}, 'runtime_files': {},
          'inventory': {}, 'effective_cpus': {}, 'checks': {}}


def command(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=20,
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if p.returncode:
        raise RuntimeError('Read-only command failed: ' + args[0])
    return p.stdout.strip()


names = ('AllowedCPUs', 'StartupAllowedCPUs', 'EffectiveCPUs', 'FragmentPath',
         'DropInPaths', 'ActiveState', 'ControlGroup')
for unit in ('system.slice', 'user.slice', 'machine.slice', 'init.scope', 'orq41bench.slice'):
    raw = command('/usr/bin/systemctl', 'show', *('-p' + key for key in names), unit)
    result['units'][unit] = dict(line.split('=', 1) for line in raw.splitlines())
    result['checks'][unit + '_baseline_parity'] = result['units'][unit] == baseline['units'][unit]
for unit in ('system.slice', 'user.slice', 'machine.slice', 'init.scope'):
    value = (Path('/sys/fs/cgroup') / unit / 'cpuset.cpus.effective').read_text().strip()
    result['effective_cpus'][unit] = value
    result['checks'][unit + '_kernel_cpus'] = value == '0-31'
for suffix in ('timer', 'service'):
    unit = 'orq41-cpuset-recovery-261110205521.' + suffix
    raw = command('/usr/bin/systemctl', 'show', '-pLoadState', '-pActiveState',
                  '-pSubState', '-pResult', unit)
    props = dict(line.split('=', 1) for line in raw.splitlines())
    result['watchdog'][suffix] = props
    result['checks'][suffix + '_inactive'] = props['ActiveState'] == 'inactive' and props['SubState'] == 'dead'
for path in ('/run/systemd/system/orq41bench.slice',
             '/run/systemd/system.control/user.slice.d/50-AllowedCPUs.conf',
             '/run/systemd/system.control/machine.slice.d/50-AllowedCPUs.conf',
             '/run/systemd/system.control/system.slice.d/50-AllowedCPUs.conf',
             '/run/systemd/system.control/init.scope.d/50-AllowedCPUs.conf',
             '/run/systemd/transient/init.scope.d/50-AllowedCPUs.conf'):
    try:
        os.lstat(path)
        result['runtime_files'][path] = 'PRESENT'
    except FileNotFoundError:
        result['runtime_files'][path] = 'ABSENT'
    result['checks'][path + '_absent'] = result['runtime_files'][path] == 'ABSENT'
containers = json.loads(command('/usr/bin/docker', 'inspect', 'orq41-paid-pg',
    'orq41-env-pg', 'orq41-env-redis', 'orq41-env-otel'))
result['inventory']['containers'] = [{key: row[key] for key in ('Id', 'Name', 'RestartCount')} |
    {'pid': row['State']['Pid'], 'started': row['State']['StartedAt'], 'status': row['State']['Status']}
    for row in containers]
result['inventory']['power'] = {path: Path(path).read_text().strip()
                                for path in baseline['inventory']['power']}
result['checks']['container_and_power_parity'] = result['inventory'] == baseline['inventory']
result['status'] = 'RESTORED_HOST_READBACK_PASS' if all(result['checks'].values()) else 'RESTORED_HOST_READBACK_FAILED'
with (HERE / 'restored-host-readback.json').open('x') as output:
    json.dump(result, output, indent=2)
    output.write('\n')
print(result['status'])
print('Checks:', len(result['checks']), 'passed:', sum(result['checks'].values()))
raise SystemExit(0 if all(result['checks'].values()) else 1)
