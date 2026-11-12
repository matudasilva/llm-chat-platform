"""Parent local metadata/READONLY readiness; no application/provider requests."""
import json
from pathlib import Path
from experiments.production_graduation.gate_validation import stage_latency as d
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

check_p2()
run = Path(__file__).resolve().parent
plan, fixtures, prep = d.read(run / 'plan.json'), d.read(run / 'fixtures.json'), d.read(run / 'preparation.json')
d.require(not (run / 'execution-started.json').exists(), 'Already admitted')
d.validate_plan(plan, fixtures, prepared=True)
d.hashes_match(plan)
d.require(d.source_review() == prep['source_review_sha256'], 'Source review changed')
resources = d.base.aa.inspect_environment(plan)
d.base.check_local_services(plan, Path(prep['private_state']) / 'c0.env')
services = {}
for name in plan['containers'].values():
    info = json.loads(d.docker('inspect', name))[0]
    services[name] = dict(image=info['Image'], running=info['State']['Running'],
        network=info['HostConfig']['NetworkMode'], ports=info['HostConfig'].get('PortBindings'),
        cpu_quota=info['HostConfig']['NanoCpus'], memory_bytes=info['HostConfig']['Memory'])
source = d.base.aa.Database(d.base.aa.SOURCE_PG)
source_after = dict(business=source.business_hash('orq41'), schema=source.schema_hash('orq41'))
d.require(source_after == prep['source_before'], 'Source environment changed')
receipt = dict(status='STAGE_DIAGNOSTIC_LOCAL_READINESS_PASS', services=services,
    postgres_resources=resources, source_before=prep['source_before'], source_after=source_after,
    plan_sha256=d.sha_file(run / 'plan.json'), source_review_sha256=d.source_review(),
    read_only_verifier_sha256=d.sha_file(run / 'independent-audit/verify_prepared_databases.py'),
    read_only_receipt_sha256=d.sha_file(run / 'independent-audit/prepared-databases-verification.json'),
    local_readiness_ports=[5432, 6379, 4318], experiment_requests=0, external_calls=0, spend_usd='0')
d.exclusive(run / 'readiness.json', receipt)
print(receipt['status'])
