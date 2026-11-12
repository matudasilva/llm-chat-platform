"""Capture the operator-selected host profile; read-only, no benchmark."""
import hashlib
import json
from pathlib import Path
import sys

assert 'sitecustomize' in sys.modules
out = Path(__file__).resolve().parent
cpus = {}
for c in (0, 2, 4, 6):
    p = Path('/sys/devices/system/cpu') / f'cpu{c}'
    cpus[str(c)] = {k: (p / 'cpufreq' / k).read_text().strip() for k in (
        'scaling_driver', 'scaling_governor', 'scaling_min_freq', 'scaling_max_freq',
        'energy_performance_preference')}
    cpus[str(c)]['siblings'] = (p / 'topology/thread_siblings_list').read_text().strip()
assert all(c['energy_performance_preference'] == 'performance' for c in cpus.values())
root = Path('.framework/orqs/ORQ-41-production-retrieval-graduation')
inventory = json.loads((root / 'paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261110150634/execution-review/scope-before.json').read_text())
assert all(hashlib.sha256(Path(n).read_bytes()).hexdigest() == v for n, v in inventory.items())
record = dict(status='CURRENT_HOST_SELECTED_PROFILE_CAPTURED_NOT_PINNED', cpus=cpus,
    intel_pstate_status=Path('/sys/devices/system/cpu/intel_pstate/status').read_text().strip(),
    no_turbo=Path('/sys/devices/system/cpu/intel_pstate/no_turbo').read_text().strip(),
    operator_report='Other open applications closed and power configuration changed',
    historical_epp_baseline='Not recorded; no before/after EPP change magnitude claimed',
    exclusive_cpu_reservation_verified=False, sustained_stability_verified=False,
    next_step='Prepare exact prospective environment binding and reservation/rollback profile before approval or benchmark',
    protected_files_unchanged=505, host_changes_by_agent=0, requests=0, external_calls=0,
    spend_usd='0', benchmark_authorized=False)
(out / 'profile.candidate.json').write_text(json.dumps(record, indent=2) + '\n')
print(record['status'])
