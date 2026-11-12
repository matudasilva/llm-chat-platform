"""Pure prospective plan generation and strict image-mismatch reproduction.

No service operation, database access, API request or performance observation.
The candidate intentionally remains non-executable with the existing harness.
"""
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from experiments.production_graduation.gate_validation import blocked_latency as driver
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

OUT=Path(__file__).resolve().parent
ROOT=Path.cwd()
ORQ=ROOT/'.framework/orqs/ORQ-41-production-retrieval-graduation'
DIAG=ORQ/'paid-execution/controlled-g6/261106225237/diagnosis'
PIN=DIAG/'blocked-runs/261109162430/execution-review/lexical-image-pin/261110135233'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name,value):
    with (OUT/name).open('x') as handle:
        handle.write(json.dumps(value,indent=2)+'\n')


def uuid_values(value, keys=('request_id','conversation_id')):
    found=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if key in keys and isinstance(item,str):
                try:
                    found.add(str(UUID(item)))
                except ValueError:
                    pass
            found.update(uuid_values(item,keys))
    elif isinstance(value,list):
        for item in value:
            found.update(uuid_values(item,keys))
    return found


def main():
    check_p2()
    baseline=json.loads((OUT/'scope-before.json').read_text())
    assert all(sha(ROOT/name)==digest for name,digest in baseline.items())
    pin=json.loads((PIN/'receipt.json').read_text())
    completion=json.loads((PIN/'completion.json').read_text())
    assert pin['status']==completion['status']=='LEXICAL_SQL_LOCAL_IMAGE_PINNED'
    assert all(sha(PIN/name)==digest for name,digest in completion['artifacts_sha256'].items())
    assert pin['source_sha256']==sha(ROOT/'app/core/providers/pgvector_store.py')
    namespace=uuid4()
    reference,fixtures=driver.make_plan(namespace,OUT.name)
    driver.validate_plan(reference,fixtures,prepared=False)
    assert reference['images']==dict.fromkeys(driver.ARMS,pin['parent_image_id'])
    candidate=copy.deepcopy(reference)
    candidate['images']=dict.fromkeys(driver.ARMS,pin['image_id'])
    changed=[key for key in reference if reference[key]!=candidate[key]]
    assert changed==['images']
    try:
        driver.validate_plan(candidate,fixtures,prepared=False)
    except ValueError as exc:
        rejected=str(exc)
        assert rejected=='Frozen plan drift: images'
    else:
        raise AssertionError('The current harness unexpectedly accepted an unapproved image')
    samples=candidate['samples']
    assert len(samples)==len(fixtures)==720
    assert sum(not sample['warmup'] for sample in samples)==400
    assert sum(sample['warmup'] for sample in samples)==320
    assert sum(len(fixture['messages']) for fixture in fixtures)==17280
    assert len(candidate['arm_cell_order'])==32
    newids=uuid_values(samples)
    assert len(newids)==1440
    catalog=[]
    for path in sorted((ORQ/'paid-execution/controlled-g6').rglob('plan.json')):
        historical=json.loads(path.read_text())
        oldids=uuid_values(historical)
        assert not oldids & newids, 'Candidate IDs overlap a historical plan'
        assert historical.get('namespace')!=str(namespace)
        assert historical.get('run_id')!=OUT.name
        catalog.append(dict(path=str(path.relative_to(ORQ)),sha256=sha(path),ids_compared=len(oldids)))
    cell_details={}
    for cell in driver.CELLS:
        selected=[sample for sample in samples if sample['language']+'-'+sample['protocol']==cell]
        measured=[sample for sample in selected if not sample['warmup']]
        assert len(selected)==180 and len(measured)==100
        assert Counter(sample['category'] for sample in measured)==dict.fromkeys(driver.CATEGORIES,25)
        assert set(Counter(sample['case_id'] for sample in measured).values())=={5}
        first=Counter(next(entry['arm'] for entry in candidate['arm_cell_order']
                           if entry['cell']==cell and entry['block']==block) for block in range(4))
        assert first==dict.fromkeys(driver.ARMS,2)
        for block in range(4):
            rows=[sample for sample in selected if sample['block']==block]
            assert [sample['warmup'] for sample in rows]==[True]*20+[False]*25
            assert Counter(sample['category'] for sample in rows[:20])==dict.fromkeys(driver.CATEGORIES,5)
        cell_details[cell]=dict(measured_per_arm=100,warmups_per_arm=80,first_position_per_arm=dict(first),
                               measured_per_category=dict(Counter(sample['category'] for sample in measured)))
    assert candidate['config_sha256']=={} and candidate['normalized_config_sha256'] is None
    assert candidate['seed_probe'] is None
    write('plan.parent-reference.json',reference)
    write('plan.candidate.json',candidate)
    write('fixtures.candidate.json',fixtures)
    write('historical-freshness.json',dict(namespace=str(namespace),candidate_ids=len(newids),
        historical_plans=catalog,overlap=0,services_or_requests=0))
    write('strict-image-reproduction.json',dict(status='EXISTING_GUARD_REJECTION_REPRODUCED',
        reference_plan_accepted=True,candidate_plan_accepted=False,error=rejected,
        changed_top_level_fields=changed,expected_images=reference['images'],proposed_images=candidate['images'],
        prepared_flag=False,docker_calls=0,database_calls=0,api_requests=0))
    write('image-identity-amendment.json',dict(status='PROPOSED_AWAITING_OPERATOR_APPROVAL',
        executable=False,base_contract_sha256=driver.CONTRACT_SHA256,
        image_pin_receipt=str((PIN/'receipt.json').relative_to(ROOT)),image_pin_receipt_sha256=sha(PIN/'receipt.json'),
        source_patch_review_sha256=pin['source_patch_review_sha256'],approved_adapter_sha256=pin['source_sha256'],
        parent_images=reference['images'],proposed_images=candidate['images'],
        candidate_plan_sha256=sha(OUT/'plan.candidate.json'),fixtures_sha256=sha(OUT/'fixtures.candidate.json'),
        protocol_changes=[],measurement_changes=[],threshold_changes=[],business_case_changes=[],
        app_p5_provider_changes=False,execution_authorized=False))
    write('environment-requirements.json',dict(status='REQUIRED_NOT_PROVISIONED',
        expected_containers=candidate['containers'],expected_databases=candidate['databases'],
        postgres_image=candidate['postgres_image'],auxiliary_images=candidate['auxiliary_images'],
        resources=candidate['resources'],expected_locale=candidate['database_locale'],
        expected_schema_sha256=candidate['source_schema_sha256'],
        expected_corpus_fingerprint=driver.load_contract()['identities']['corpus_fingerprint'],
        expected_corpus_content_sha256=driver.load_contract()['identities']['corpus_content_sha256'],
        conversations_per_arm=720,history_messages_per_arm=17280,final_messages_per_arm=18720,
        analyze_tables=list(driver.TABLES),runtime_plan_cache_mode='auto',
        fallback='Unset/None',routing='static',shadow=False,pythonhashseed='41',
        otlp_endpoint='http://127.0.0.1:4318/v1/traces',external_credentials=False,
        config_probes='PENDING: require actual future image/environment evidence',
        readiness='PENDING: do not claim source/corpus/config/resources ready from historical receipts',
        source_database_reads_writes_performed=0,container_database_allocation_performed=False))
    assert all(sha(ROOT/name)==digest for name,digest in baseline.items())
    write('validation.json',dict(status='PROSPECTIVE_AA_MANIFEST_VALIDATED_NOT_EXECUTABLE',
        validated_at=datetime.now(timezone.utc).isoformat(),script_sha256=sha(Path(__file__)),
        reference_plan_accepted=True,new_image_rejected_fail_closed=True,
        exact_candidate_delta=['images.c0','images.c1'],cells=cell_details,
        future_request_count=1440,future_measured_count=800,future_warmup_count=640,
        future_worker_count=32,concurrency=1,attempts=1,repetitions=1,
        expected_history_messages_per_arm=17280,unique_preview_request_conversation_ids=len(newids),
        historical_plans_checked=len(catalog),historical_id_overlap=0,
        source_config_files_unchanged=len(baseline),benchmark_measurements=0,
        docker_calls=0,database_calls=0,api_requests=0,provider_calls=0,external_calls=0,spend_usd='0',
        unresolved=['Explicit approval of image-only binding amendment',
                    'Minimal strict harness support with deterministic tests and source review',
                    'Fresh disposable preparation and actual config/seed/resource/data evidence',
                    'Exact final executable packet independent review and separate execution authorization'],
        official_g6_status='CONTROLLED_G6_FAIL',paid_admission='BLOCKED_CONTROLLED_G6_FAIL'))
    print('PROSPECTIVE_AA_MANIFEST_VALIDATED_NOT_EXECUTABLE')
    print('1440 future local requests; image-only amendment required; no service/request executed')


if __name__=='__main__':
    main()
