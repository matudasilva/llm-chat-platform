"""After the sole run: read-only persistence/source proof, retained-data cleanup."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

from experiments.production_graduation.gate_validation import blocked_latency as driver
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

OUT=Path(__file__).resolve().parent
RUN=OUT.parent
IMPL=driver.IMAGE_APPROVAL.parent


def main():
    check_p2()
    plan=json.loads((RUN/'plan.json').read_text())
    fixtures=json.loads((RUN/'fixtures.json').read_text())
    result=json.loads((RUN/'result.json').read_text())
    driver.validate_plan(plan,fixtures,prepared=True)
    assert driver.sha_file(RUN/'plan.json')==result['plan_sha256']
    assert result['request_count']==1440 and len(result['worker_receipts'])==32
    states={}
    for entry in plan['arm_cell_order']:
        key=f'{entry["arm"]}-{entry["cell"]}-b{entry["block"]}'
        info=json.loads(driver.docker('inspect','orq41-blocked-'+plan['run_id']+'-'+key.lower()))[0]
        assert info['Image']==plan['images'][entry['arm']]
        assert not info['State']['Running'] and info['State']['ExitCode']==0
        assert not info['State']['OOMKilled'] and info['RestartCount']==0
        states[key]=dict(id=info['Id'],image=info['Image'],exit_code=0,running=False,oom=False,restarts=0)
    before=json.loads((RUN/'database-final-verification.json').read_text())
    db=driver.aa.Database(plan['containers']['postgres'])
    after=dict(databases=driver.verify_databases(db,plan,fixtures,final=True),database_writes=0)
    assert before==after, 'Final persisted projection drifted after worker shutdown'
    counts={arm:driver.readonly(db,database,'SELECT (SELECT count(*) FROM conversations),'
        '(SELECT count(*) FROM messages),(SELECT count(*) FROM usage_events),'
        '(SELECT count(*) FROM rag_request_metrics);').strip()
        for arm,database in plan['databases'].items()}
    wrapper=IMPL/'prepare_environment.py'
    spec=importlib.util.spec_from_file_location('retained_source_identity',wrapper)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=module.source_identity()
    assert source==json.loads((IMPL/'source-environment-after.json').read_text())
    scope=json.loads((OUT/'scope-before.json').read_text())
    assert all(driver.sha_file(driver.ROOT/name)==value for name,value in scope.items())
    for audit in (RUN/'network-audit.log',OUT/'host-network-audit.log'):
        assert not audit.exists() or audit.stat().st_size==0
    driver.write_json(OUT/'postflight.json',dict(status='POSTRUN_READONLY_PERSISTENCE_SOURCE_PASS',
        checked_at=datetime.now(timezone.utc).isoformat(),plan_sha256=driver.sha_file(RUN/'plan.json'),
        persistence=after,descriptive_counts_conversations_messages_usage_metrics=counts,
        all_32_workers_exited_once_without_oom=states,existing_source_business_schema_identity=source,
        existing_source_unchanged=True,protected_source_config_files_unchanged=len(scope),
        source_changes=0,api_requests=0,provider_calls=0,external_calls=0,spend_usd='0',
        attribution='Parent execution of previously reviewed final-projection verifier; no new performance trial'))
    cleanup={}
    for role in ('collector','redis','postgres'):
        name=plan['containers'][role]
        assert name=='orq41-blocked-'+plan['run_id']+'-'+role
        driver.docker('stop','--time','10',name)
        info=json.loads(driver.docker('inspect',name))[0]
        assert not info['State']['Running']
        cleanup[role]=dict(name=name,id=info['Id'],running=False,data_retained=True)
    assert json.loads(driver.docker('inspect',driver.aa.SOURCE_PG))[0]['State']['Running']
    driver.write_json(OUT/'cleanup.json',dict(status='OWN_SERVICES_STOPPED_DATA_AND_MARKERS_RETAINED',
        services=cleanup,workers_exited=32,containers_removed=0,databases_dropped=0,
        existing_source_postgres_running=True,no_resume=True,automatic_resends=0))
    print('POSTFLIGHT_PASS; own services stopped; all data/markers retained')


if __name__=='__main__':
    main()
