"""Independent raw-data replay; no API, Docker, database or provider operation."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median
from uuid import UUID,uuid5


def main():
    from experiments.production_graduation.gate_validation.validate_g123 import check_p2
    check_p2()
    run=Path(__file__).resolve().parent.parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    plan=json.loads((run/'plan.json').read_text());result=json.loads((run/'result.json').read_text())
    review=json.loads((run/'independent-review.json').read_text());analysis=json.loads((run/'analysis.json').read_text())
    assert result['plan_sha256']==review['plan_sha256']==analysis['plan_sha256']==sha(run/'plan.json')
    assert review['status']=='C1_COPY_COMPARISON_HARNESS_REVIEW_PASS'
    assert result['status']=='C1_COPY_COMPARISON_COMPLETE' and result['not_a_gate']
    assert sha(run/'analyze.py')==review['prespecified_analyzer_sha256']
    for name,digest in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():assert sha(Path(name))==digest
    assert set(result['receipts_sha256'])=={f'{arm}-{lang}-{p}.json'for arm in ('old','new')for lang in ('EN','ES')for p in ('json','sse')}
    assert plan['images']['old']=='sha256:7417a2af20101903f3fc9326af26da074eec6dd3b90987b5b5f74c1986a58d06'
    assert plan['images']['new']=='sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707'
    arms={'old':{},'new':{}};instances=set();count=warmups=0;last_end=-1
    for block in plan['arm_cell_order']:
        arm=block['arm'];name=arm+'-'+block['cell']+'.json'
        assert sha(run/name)==result['receipts_sha256'][name]
        worker=json.loads((run/name).read_text());assert worker['arm']==arm
        assert worker['config_identity']==plan['config_sha256'][arm]
        assert worker['provider_calls']==worker['external_calls']==0
        expected=[s for s in plan['samples']if s['language']+'-'+s['protocol']==block['cell']]
        assert len(worker['samples'])==len(expected)==5
        assert sum(r['warmup']for r in worker['samples'])==1
        assert Counter(r['category']for r in worker['samples']if not r['warmup'])==Counter(dict.fromkeys(('document','history','combined','empty'),1))
        for row,sample in zip(worker['samples'],expected):
            assert all(row[k]==sample[k]for k in ('sample_id','language','protocol','warmup','category','request_id','conversation_id'))
            assert row['request_id']==str(uuid5(UUID(plan['namespace']),'request/'+row['sample_id']))
            assert row['conversation_id']==str(uuid5(UUID(plan['namespace']),row['sample_id']))
            assert row['status']=='PASS' and row['error']is None
            assert all(type(row[k])is int for k in ('start_ns','primary_dispatch_ns','start_cpu_ns','primary_cpu_ns','process_cpu_ns','preparation_ns'))
            assert row['primary_dispatch_ns']>=row['start_ns']>last_end
            last_end=row['primary_dispatch_ns']
            assert row['preparation_ns']==row['primary_dispatch_ns']-row['start_ns']>=0
            assert row['process_cpu_ns']==row['primary_cpu_ns']-row['start_cpu_ns']>=0
            instance=row['accounting_instance_id'];assert str(UUID(instance))==instance and instance not in instances
            instances.add(instance)
            assert [d['purpose']for d in row['dispatches']]==['rewrite','primary']
            assert all(len(d['sha256'])==64 and all(c in '0123456789abcdef'for c in d['sha256'])for d in row['dispatches'])
            assert row['sample_id']not in arms[arm];arms[arm][row['sample_id']]=row
            count+=1;warmups+=row['warmup']
    assert(count,warmups,len(instances))==(40,8,40)
    assert arms['old'].keys()==arms['new'].keys()
    first={}
    for block in plan['arm_cell_order']:first.setdefault(block['cell'],block['arm'])
    assert first=={'EN-json':'old','EN-sse':'new','ES-json':'new','ES-sse':'old'}
    pairs=[]
    for key,old in arms['old'].items():
        new=arms['new'][key];assert old['dispatches']==new['dispatches']
        if old['warmup']:continue
        cell=old['language']+'-'+old['protocol']
        pairs.append({'sample_id':key,'category':old['category'],'cell':cell,'first':first[cell],
            'old_cpu_ms':old['process_cpu_ns']/1e6,'new_cpu_ms':new['process_cpu_ns']/1e6,
            'old_wall_ms':old['preparation_ns']/1e6,'new_wall_ms':new['preparation_ns']/1e6,
            'cpu_new_minus_old_ms':(new['process_cpu_ns']-old['process_cpu_ns'])/1e6,
            'wall_new_minus_old_ms':(new['preparation_ns']-old['preparation_ns'])/1e6})
    assert {p['sample_id']:p for p in pairs}=={p['sample_id']:p for p in analysis['pairs']}
    assert len(pairs)==16
    def stats(rows):
        out={'n':len(rows)}
        for kind in ('cpu','wall'):
            values=[r[kind+'_new_minus_old_ms']for r in rows]
            out[kind]={'median_new_minus_old_ms':median(values),'range_ms':[min(values),max(values)],
                'optimized_lower':sum(v<0 for v in values),'equal':sum(v==0 for v in values),'optimized_higher':sum(v>0 for v in values)}
        return out
    assert stats(pairs)==analysis['overall']
    assert {c:stats([r for r in pairs if r['category']==c])for c in ('document','history','combined','empty')}==analysis['by_category']
    assert {c:stats([r for r in pairs if r['cell']==c])for c in first}==analysis['by_cell']
    assert {a:stats([r for r in pairs if r['first']==a])for a in ('old','new')}==analysis['by_first_arm']
    assert(result['request_count'],result['measured_requests'],result['warmups'],result['candidate_accounting_instances'])==(40,32,8,40)
    assert result['provider_calls']==result['external_calls']==result['paid_spend_usd']==0
    audit=run/'network-audit.log';assert not audit.exists()or not audit.read_text()
    dbpath=run/'execution-review/database-final-verification.json';db=json.loads(dbpath.read_text())
    assert db['status']=='C1_COMPARISON_FINAL_DATABASES_READONLY_VERIFIER_PASS'and db['plan_sha256']==sha(run/'plan.json')
    assert db['verifier_sha256']==sha(run/'execution-review/verify_final_databases.py')
    assert db['normalized_effective_configuration_equal']
    assert all(a['conversations']==20 and a['messages']==424 and a['normalized_generated_message_ids']==40 for a in db['arms'])
    assert db['arms'][0]['normalized_business_projection_sha256']==db['arms'][1]['normalized_business_projection_sha256']
    receipt={'status':'C1_COPY_COMPARISON_EXECUTION_INDEPENDENT_REVIEW_PASS','reviewer':'/root/packet_review',
        'plan_sha256':sha(run/'plan.json'),'result_sha256':sha(run/'result.json'),'analysis_sha256':sha(run/'analysis.json'),
        'analyzer_sha256':sha(run/'analyze.py'),'verifier_sha256':sha(Path(__file__)),
        'worker_receipts':result['receipts_sha256'],'final_database_verification_sha256':sha(dbpath),
        'requests':40,'measured':32,'warmups':8,'candidate_accounting_instances':40,'native_payload_and_call_parity':True,
        'overall':analysis['overall'],'by_category':analysis['by_category'],'order_strata_verified':True,
        'integer_intervals_verified':True,'not_a_gate':True,'official_g6_status':'CONTROLLED_G6_FAIL',
        'reviewer_api_calls':0,'reviewer_database_calls':0,'reviewer_docker_calls':0,'observed_guard_attempts':0,
        'external_calls':0,'spend_usd':'0','causal_speedup_or_g6_margin_established':False}
    out=run/'execution-review/receipt.json';assert not out.exists();out.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items()if k not in('worker_receipts','by_category')},indent=2))


if __name__=='__main__':main()
