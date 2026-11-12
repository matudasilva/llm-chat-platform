"""Pure amendment consistency checks; no benchmark or host mutation."""
import hashlib
import json
from pathlib import Path
import sys

assert 'sitecustomize' in sys.modules and not sys.flags.optimize
out = Path(__file__).resolve().parent
diag = out.parent.parent
c = json.loads((out / 'contract.proposed.json').read_text())
assert c['proposal_sha256'] == hashlib.sha256((out / 'proposal.md').read_bytes()).hexdigest()
base = diag / 'measurement-amendment/contract.json'
assert c['base_contract_sha256'] == hashlib.sha256(base.read_bytes()).hexdigest()
assert c['requests'] == 4 * 4 * 2 * (20 + 25) == 1440
assert c['measured'] == 4 * 4 * 2 * 25 == 800
assert c['warmups'] == 4 * 4 * 2 * 20 == 640
assert c['p95_index'] == 94 and c['symmetric_limit_percent'] == 5
assert c['executions'] == c['concurrency'] == 1
assert not any(c[k] for k in ('host_changes_authorized', 'harness_implementation_authorized', 'benchmark_authorized',
                              'reservation_proven', 'restoration_procedure_ready'))
assert c['api_cpus'] == [0, 2] and c['postgres_cpus'] == [4, 6]
assert set(c['housekeeping_cpus']).isdisjoint(c['smts_reserved_for_interference_control'])
assert set(c['housekeeping_cpus']) | set(c['smts_reserved_for_interference_control']) == set(range(32))
for cpu, values in c['power_profile']['cpus'].items():
    p = Path('/sys/devices/system/cpu') / f'cpu{cpu}/cpufreq'
    for key, expected in values.items():
        if key != 'siblings':
            assert (p / key).read_text().strip() == expected
inventory = json.loads((diag / 'blocked-runs/261110150634/execution-review/scope-before.json').read_text())
assert all(hashlib.sha256(Path(n).read_bytes()).hexdigest() == digest for n, digest in inventory.items())
source = json.loads((diag / 'stage-diagnostic-design/261110181827/implementation/source-review.json').read_text())
assert all(hashlib.sha256(Path(n).read_bytes()).hexdigest() == digest for n, digest in source['technical_files_sha256'].items())
result = dict(status='AMENDMENT_CONSISTENCY_VALIDATION_PASS', previous_sources_unchanged=505,
              stage_technical_files_unchanged=4, requests_executed=0, host_changes=0,
              external_provider_calls=0, spend_usd='0', environment_readiness='BLOCKED_PENDING_RESERVATION_PROCEDURE')
(out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
print(result['status'])
