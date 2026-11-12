"""Independent retained-data replay; never starts an API or connects to a DB."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median
from uuid import UUID, uuid5


def main():
    from experiments.production_graduation.gate_validation.validate_g123 import check_p2
    check_p2()
    run=Path(__file__).resolve().parent.parent
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    plan=json.loads((run/'plan.json').read_text())
    result=json.loads((run/'result.json').read_text())
    approval=json.loads((run/'independent-review.json').read_text())
    analysis=json.loads((run/'analysis.json').read_text())
    assert result['plan_sha256']==approval['plan_sha256']==analysis['plan_sha256']==sha(run/'plan.json')
    assert approval['status']=='DIAGNOSTIC_AGGREGATE_HARNESS_REVIEW_PASS'
    assert result['status']=='DIAGNOSTIC_AGGREGATE_COMPLETE' and result['not_a_gate']
    assert analysis['status']=='AGGREGATE_DIAGNOSTIC_ANALYSIS_NOT_A_GATE'
    for name,digest in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():assert sha(Path(name))==digest
    assert set(result['receipts_sha256'])=={f'{a}-{l}-{p}.json' for a in ('c0','c1') for l in ('EN','ES') for p in ('json','sse')}
    arms={'c0':{},'c1':{}};instances=set();total=measured=warmups=0
    previous_end=-1
    for block in plan['arm_cell_order']:
        arm=block['arm'];name=arm+'-'+block['cell']+'.json'
        assert sha(run/name)==result['receipts_sha256'][name]
        worker=json.loads((run/name).read_text())
        assert worker['arm']==arm and worker['config_identity']==plan['config_sha256'][arm]
        assert worker['provider_calls']==worker['external_calls']==0
        expected=[s for s in plan['samples'] if s['language']+'-'+s['protocol']==block['cell']]
        rows=worker['samples'];assert len(rows)==len(expected)==5
        assert sum(r['warmup'] for r in rows)==1
        assert Counter(r['category'] for r in rows if not r['warmup'])==Counter(dict.fromkeys(('document','history','combined','empty'),1))
        for row,sample in zip(rows,expected):
            assert all(row[k]==sample[k] for k in ('sample_id','language','protocol','warmup','category','request_id','conversation_id'))
            assert row['request_id']==str(uuid5(UUID(plan['namespace']),'request/'+sample['sample_id']))
            assert row['conversation_id']==str(uuid5(UUID(plan['namespace']),sample['sample_id']))
            assert row['status']=='PASS' and row['error'] is None
            assert all(type(row[k]) is int for k in ('start_ns','primary_dispatch_ns','start_cpu_ns','primary_cpu_ns','process_cpu_ns','preparation_ns'))
            assert row['primary_dispatch_ns']>=row['start_ns']>previous_end
            assert row['preparation_ns']==row['primary_dispatch_ns']-row['start_ns']>=0
            assert row['process_cpu_ns']==row['primary_cpu_ns']-row['start_cpu_ns']>=0
            previous_end=row['primary_dispatch_ns']
            assert [d['purpose'] for d in row['dispatches']]==['rewrite','primary']
            assert all(len(d['sha256'])==64 and all(c in '0123456789abcdef' for c in d['sha256']) for d in row['dispatches'])
            assert row['sample_id'] not in arms[arm];arms[arm][row['sample_id']]=row
            if arm=='c1':
                instance=row['accounting_instance_id'];assert str(UUID(instance))==instance and instance not in instances
                instances.add(instance)
            else:assert row['accounting_instance_id'] is None
            total+=1;measured+=not row['warmup'];warmups+=row['warmup']
    assert (total,measured,warmups,len(instances))==(40,32,8,20)
    assert arms['c0'].keys()==arms['c1'].keys()
    for key in arms['c0']:assert arms['c0'][key]['dispatches']==arms['c1'][key]['dispatches']
    deltas=[]
    for category in ('document','history','combined','empty'):
        keys=[k for k,r in arms['c0'].items() if r['category']==category and not r['warmup']];assert len(keys)==4
        published=next(s for s in analysis['summary'] if s['category']==category)
        assert published['paired_cases']==4
        for arm in ('c0','c1'):
            for field in ('preparation_ns','process_cpu_ns'):
                values=[arms[arm][k][field]/1e6 for k in keys]
                assert published[arm+'_'+field+'_median_ms']==median(values)
                assert published[arm+'_'+field+'_range_ms']==[min(values),max(values)]
        pair={}
        for field in ('preparation_ns','process_cpu_ns'):
            values=[(arms['c1'][k][field]-arms['c0'][k][field])/1e6 for k in keys]
            assert published['paired_'+field+'_delta_median_ms']==median(values)
            pair[field]=median(values)
        deltas.append({'category':category,'cpu_delta_median_ms':pair['process_cpu_ns'],'wall_delta_median_ms':pair['preparation_ns']})
    published_pairs={p['sample_id']:p for p in analysis['paired_samples']};assert len(published_pairs)==16
    for key,a in arms['c0'].items():
        if a['warmup']:continue
        b=arms['c1'][key];p=published_pairs[key]
        assert p['category']==a['category']
        assert p['wall_delta_ms']==(b['preparation_ns']-a['preparation_ns'])/1e6
        assert p['cpu_delta_ms']==(b['process_cpu_ns']-a['process_cpu_ns'])/1e6
    assert (result['request_count'],result['measured_requests'],result['warmups'])==(40,32,8)
    assert result['provider_calls']==result['external_calls']==result['paid_spend_usd']==0
    audit=run/'network-audit.log';assert not audit.exists() or not audit.read_text()
    dbpath=run/'execution-review/database-final-verification.json';db=json.loads(dbpath.read_text())
    assert db['status']=='AGGREGATE_FINAL_DATABASES_READONLY_VERIFIER_PASS' and db['plan_sha256']==sha(run/'plan.json')
    assert db['verifier_sha256']==sha(run/'execution-review/verify_final_databases.py')
    assert db['normalized_effective_configuration_equal']
    assert all(a['conversations']==20 and a['messages']==424 and a['normalized_generated_message_ids']==40 for a in db['arms'])
    assert db['arms'][0]['normalized_business_projection_sha256']==db['arms'][1]['normalized_business_projection_sha256']
    receipt={'status':'DIAGNOSTIC_AGGREGATE_EXECUTION_INDEPENDENT_REVIEW_PASS','reviewer':'/root/packet_review',
        'plan_sha256':sha(run/'plan.json'),'result_sha256':sha(run/'result.json'),'analysis_sha256':sha(run/'analysis.json'),
        'analyzer_sha256':sha(run/'analyze.py'),'verifier_sha256':sha(Path(__file__)),
        'worker_receipts':result['receipts_sha256'],'database_verification_sha256':sha(dbpath),
        'requests':total,'measured':measured,'warmups':warmups,'candidate_accounting_instances':20,
        'native_payload_and_call_parity':True,'exact_interval_arithmetic_verified':True,'category_pair_deltas':deltas,
        'reviewer_api_calls':0,'reviewer_database_calls':0,'reviewer_docker_calls':0,'observed_guard_attempts':0,
        'external_calls':0,'spend_usd':'0','official_g6_status':'CONTROLLED_G6_FAIL','not_a_gate':True,
        'limits':['Aggregate process CPU includes all threads and background work','Descriptive N4 per category; no causal component percentage','Raw candidate chains validated by reviewed worker, not retained for independent replay','Parent executed read-only final DB verifier; reviewer inspected source/receipt']}
    out=run/'execution-review/receipt.json';assert not out.exists();out.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
