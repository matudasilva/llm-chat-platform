"""Revalidate after a metadata read failed before any admission; never send API requests."""
from pathlib import Path
from experiments.production_graduation.gate_validation import stage_latency as d
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

check_p2()
run = Path(__file__).resolve().parent.parent
plan, fixtures, prep = d.preflight(run)
resources = d.base.aa.inspect_environment(plan)
db = d.base.aa.Database(plan['containers']['postgres'])
proof = d.verify_databases(db, plan, fixtures)
d.require(proof == prep['databases'], 'Prepared data changed')
d.require(not list(run.glob('c?-*-started.json')), 'Worker was admitted')
workers = d.docker('ps', '-a', '--filter', 'name=^/orq41-stage-261110181827-c[01]-', '--format', '{{.ID}}').strip()
d.require(not workers, 'A worker container exists')
source = d.base.aa.Database(d.base.aa.SOURCE_PG)
d.require(dict(business=source.business_hash('orq41'), schema=source.schema_hash('orq41')) == prep['source_before'], 'Source state changed')
d.exclusive(run / 'execution-review/pre-admission-revalidation.json', dict(
    status='PRE_ADMISSION_METADATA_REVALIDATION_PASS', execution_marker_present=False,
    worker_markers=0, worker_containers=0, experiment_requests=0, resources=resources,
    prepared_data_equal=True, source_preserved=True, plan_sha256=d.sha_file(run / 'plan.json'),
    initial_failure_sha256=d.sha_file(run / 'execution-review/controller.stderr'),
    metadata_failure_cause='Unestablished; initial helper did not retain Docker stderr; same-P2 raw inspect subsequently succeeded',
    external_calls=0, spend_usd='0'))
print('PRE_ADMISSION_METADATA_REVALIDATION_PASS')
