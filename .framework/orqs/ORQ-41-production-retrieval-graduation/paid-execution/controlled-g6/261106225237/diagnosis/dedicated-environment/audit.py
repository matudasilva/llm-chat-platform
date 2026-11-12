"""Read host CPU configuration and retained evidence; never change host state."""
import hashlib
import json
import os
from pathlib import Path
import sys

assert 'sitecustomize' in sys.modules
assert os.environ.get('AWS_EC2_METADATA_DISABLED') == 'true'
assert all(line.split()[0] == 'lo' for line in Path('/proc/net/route').read_text().splitlines()[1:] if line.strip())
out = Path(__file__).resolve().parent
diag = out.parent
run = diag / 'stage-runs/261110181827'
review = json.loads((run / 'execution-review/receipt.json').read_text())
assert review['status'] == 'STAGE_DIAGNOSTIC_EXECUTION_REVIEW_PASS'
inventory = json.loads((diag / 'blocked-runs/261110150634/execution-review/scope-before.json').read_text())
assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest for name, digest in inventory.items())
cpus = {}
for number in (0, 2, 4, 6):
    root = Path('/sys/devices/system/cpu') / f'cpu{number}'
    cpus[str(number)] = {name: (root / 'cpufreq' / name).read_text().strip() for name in (
        'scaling_governor', 'scaling_driver', 'scaling_min_freq', 'scaling_max_freq', 'scaling_cur_freq')}
    cpus[str(number)]['siblings'] = (root / 'topology/thread_siblings_list').read_text().strip()
result = dict(status='READONLY_ENVIRONMENT_EVALUATION_COMPLETE_TARGET_UNSELECTED', cpus=cpus,
    kernel_isolated_cpus=Path('/sys/devices/system/cpu/isolated').read_text().strip(),
    protected_files_unchanged=len(inventory),
    source_review_sha256=hashlib.sha256((run / 'execution-review/receipt.json').read_bytes()).hexdigest(),
    proposal_sha256=hashlib.sha256((out / 'proposal.md').read_bytes()).hexdigest(),
    host_changes=0, new_requests=0, service_operations=0, provider_calls=0, spend_usd='0',
    causal_explanation_proven=False, target_selected=False)
(out / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
print(result['status'])
