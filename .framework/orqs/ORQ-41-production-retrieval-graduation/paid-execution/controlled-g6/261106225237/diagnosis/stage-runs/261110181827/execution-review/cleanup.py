"""Stop only this settled diagnostic's services; retain every container/data/marker."""
from pathlib import Path
import json
from experiments.production_graduation.gate_validation import stage_latency as d
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

check_p2()
run = Path(__file__).resolve().parent.parent
plan = d.read(run / 'plan.json')
d.require(d.read(run / 'result.json')['request_count'] == 360, 'Incomplete experiment')
d.require(d.read(run / 'execution-review/final-databases-verification.json')['original_source_preserved'], 'Final proof absent')
workers = {}
for entry in plan['arm_cell_order']:
    key = f'{entry["arm"]}-{entry["cell"]}-b0'
    name = 'orq41-stage-' + plan['run_id'] + '-' + key.lower()
    info = json.loads(d.docker('inspect', name))[0]
    d.require(not info['State']['Running'] and info['State']['ExitCode'] == 0
        and not info['State']['OOMKilled'] and info['RestartCount'] == 0, 'Worker not settled')
    workers[name] = dict(exit_code=0, restarts=0, running=False)
services = {}
for kind in ('collector', 'redis', 'postgres'):
    name = plan['containers'][kind]
    d.require(name.startswith('orq41-stage-' + plan['run_id'] + '-'), 'Foreign service')
    d.docker('stop', '--time', '10', name)
    info = json.loads(d.docker('inspect', name))[0]
    d.require(not info['State']['Running'], 'Own service did not stop')
    services[name] = dict(running=False, data_retained=True, image=info['Image'])
source = json.loads(d.docker('inspect', d.base.aa.SOURCE_PG))[0]
d.require(source['State']['Running'], 'Source PostgreSQL stopped')
d.exclusive(run / 'execution-review/cleanup.json', dict(status='OWN_SERVICES_STOPPED_DATA_RETAINED',
    workers=workers, services=services, source_postgres_running=True, containers_removed=0,
    databases_dropped=0, markers_removed=0, extra_requests=0))
print('OWN_SERVICES_STOPPED_DATA_RETAINED')
