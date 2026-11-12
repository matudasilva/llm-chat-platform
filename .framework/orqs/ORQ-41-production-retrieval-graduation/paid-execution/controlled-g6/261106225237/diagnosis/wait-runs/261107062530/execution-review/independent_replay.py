"""Independent raw interval/arithmetic replay; no service operation or rerun."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median
from uuid import UUID,uuid5


def union_length(spans):
    points=Counter()
    for start,end in spans:
        assert end>start
        points[start]+=1;points[end]-=1
    total=depth=0;previous=None
    for at,change in sorted(points.items()):
        if depth:total+=at-previous
        depth+=change;assert depth>=0;previous=at
    assert depth==0
    return total


def intervals(events,rid):
    expected={'sql':('start','stop'),'gc':('start','stop'),'sdk':('queued','entered','exited','returned')}
    pending={};finished=[];done=set();gc_end={}
    assert len(events)<=256
    for e in events:
        kind=e['kind'];assert kind in expected and e['request_id']==rid
        assert type(e['at_ns'])is int and e['at_ns']>=0 and type(e['thread'])is int
        if kind!='gc':assert e['context_owner']==rid
        else:
            thread,generation=e['identity'].split(':')
            assert int(thread)==e['thread'] and int(generation)in(0,1,2)
        key=kind,e['identity']
        if key not in pending:
            assert e['phase']==expected[kind][0]
            if kind!='gc':assert key not in done and type(e['identity'])is int and e['identity']>0
            if key in gc_end:
                prior_start,prior_stop=gc_end[key]
                assert e['at_ns']>=prior_stop and e['at_ns']>prior_start
            pending[key]=[]
        group=pending[key];assert e['phase']==expected[kind][len(group)]
        assert not group or e['at_ns']>=group[-1]['at_ns'];group.append(e)
        if len(group)==len(expected[kind]):
            if kind=='sdk':assert group[0]['thread']==group[3]['thread'] and group[1]['thread']==group[2]['thread']
            else:assert group[0]['thread']==group[1]['thread']
            if kind=='gc':gc_end[key]=group[0]['at_ns'],group[-1]['at_ns']
            finished.append((kind,group));done.add(key);del pending[key]
    assert not pending
    assert sum(kind=='sdk'for kind,g in finished)==2 and any(kind=='sql'for kind,g in finished)
    return finished


def main():
    from experiments.production_graduation.gate_validation.validate_g123 import check_p2
    check_p2()
    run=Path(__file__).resolve().parent.parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    plan=json.loads((run/'plan.json').read_text());result=json.loads((run/'result.json').read_text())
    approval=json.loads((run/'independent-review.json').read_text());analysis=json.loads((run/'analysis.json').read_text())
    assert result['status']=='DIAGNOSTIC_WAITS_COMPLETE' and result['not_a_gate']
    assert approval['status']=='DIAGNOSTIC_WAITS_HARNESS_REVIEW_PASS'
    assert result['plan_sha256']==approval['plan_sha256']==analysis['plan_sha256']==sha(run/'plan.json')
    assert sha(run/'protocol.md')==approval['protocol_sha256']
    for name,digest in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():assert sha(Path(name))==digest
    assert set(result['receipts_sha256'])=={f'{a}-{l}-{p}.json'for a in ('c0','c1')for l in ('EN','ES')for p in ('json','sse')}
    rows=[];native={};instances=set();event_counts=Counter();interval_counts=Counter();warmups=0;last=-1
    for block in plan['arm_cell_order']:
        arm=block['arm'];name=arm+'-'+block['cell']+'.json';assert sha(run/name)==result['receipts_sha256'][name]
        worker=json.loads((run/name).read_text());assert worker['arm']==arm and worker['config_identity']==plan['config_sha256'][arm]
        assert worker['provider_calls']==worker['external_calls']==0
        expected=[s for s in plan['samples']if s['language']+'-'+s['protocol']==block['cell']]
        assert len(worker['samples'])==len(expected)==5
        assert Counter(r['category']for r in worker['samples']if not r['warmup'])=={'combined':2,'empty':2}
        assert sum(r['warmup']for r in worker['samples'])==1
        for raw,sample in zip(worker['samples'],expected):
            assert all(raw[k]==sample[k]for k in ('sample_id','request_id','conversation_id','language','protocol','category','warmup'))
            assert raw['status']=='PASS'and raw['error']is None and raw['observer_valid']is True
            assert raw['request_id']==str(uuid5(UUID(plan['namespace']),'request/'+raw['sample_id']))
            assert raw['conversation_id']==str(uuid5(UUID(plan['namespace']),raw['sample_id']))
            assert all(type(raw[k])is int for k in ('start_ns','primary_dispatch_ns','start_cpu_ns','primary_cpu_ns','preparation_ns','process_cpu_ns'))
            a,b=raw['start_ns'],raw['primary_dispatch_ns'];assert b>=a>last;last=b
            assert raw['preparation_ns']==b-a and raw['process_cpu_ns']==raw['primary_cpu_ns']-raw['start_cpu_ns']>=0
            assert [x['purpose']for x in raw['dispatches']]==['rewrite','primary']
            native[arm,raw['sample_id']]=raw['dispatches']
            if arm=='c1':
                uid=raw['accounting_instance_id'];assert str(UUID(uid))==uid and uid not in instances;instances.add(uid)
            else:assert raw['accounting_instance_id']is None
            groups=intervals(raw['wait_events'],raw['request_id']);event_counts.update(e['kind']for e in raw['wait_events'])
            interval_counts.update(kind for kind,g in groups)
            spans={k:[]for k in ('sql','gc','sdk_queue','sdk_execution','sdk_return')};counts=dict.fromkeys(spans,0)
            for kind,group in groups:
                segments=[(kind,group[0]['at_ns'],group[-1]['at_ns'])]if kind!='sdk'else[
                    (label,group[i]['at_ns'],group[i+1]['at_ns'])for i,label in enumerate(('sdk_queue','sdk_execution','sdk_return'))]
                for label,start,end in segments:
                    start,end=max(a,start),min(b,end)
                    if end>start:spans[label].append((start,end));counts[label]+=1
            metrics={k+'_union_ns':union_length(v)for k,v in spans.items()}
            metrics.update(wall_ns=b-a,cpu_ns=raw['process_cpu_ns'],all_captured_union_ns=union_length([v for values in spans.values()for v in values]))
            assert metrics['all_captured_union_ns']<=b-a
            rows.append(dict(arm=arm,cell=block['cell'],sample_id=raw['sample_id'],category=raw['category'],warmup=raw['warmup'],counts=counts,**metrics));warmups+=raw['warmup']
    assert len(rows)==40 and warmups==8 and len(instances)==20
    assert len(native)==40
    for (arm,key),value in native.items():assert value==native['c0'if arm=='c1'else'c1',key]
    identity=lambda r:(r['arm'],r['sample_id'])
    assert {identity(r):r for r in rows}=={identity(r):r for r in analysis['rows']}
    pairs=[]
    for row in rows:
        if row['arm']!='c1'or row['warmup']:continue
        baseline=next(x for x in rows if x['arm']=='c0'and x['sample_id']==row['sample_id'])
        pairs.append(dict(sample_id=row['sample_id'],cell=row['cell'],category=row['category'],**{k:row[k]-baseline[k]for k in row if k.endswith('_ns')}))
    assert len(pairs)==16 and {p['sample_id']:p for p in pairs}=={p['sample_id']:p for p in analysis['paired_deltas']}
    for category in ('combined','empty'):
        chosen=[p for p in pairs if p['category']==category];assert len(chosen)==8
        for key in analysis['summary'][category]:
            values=[p[key]for p in chosen];assert analysis['summary'][category][key]=={'median_ms':median(values)/1e6,'range_ms':[min(values)/1e6,max(values)/1e6]}
        for arm in ('c0','c1'):
            for key,value in analysis['arm_medians_ms'][arm][category].items():
                assert median(r[key]for r in rows if r['arm']==arm and r['category']==category and not r['warmup'])/1e6==value
    first={}
    for block in plan['arm_cell_order']:first.setdefault(block['cell'],block['arm'])
    for arm in ('c0','c1'):
        chosen=[p for p in pairs if first[p['cell']]==arm];assert len(chosen)==8
        for key,value in analysis['order_medians_ms'][arm+'_first'].items():assert median(p[key]for p in chosen)/1e6==value
    dbpath=run/'execution-review/database-final-verification.json';db=json.loads(dbpath.read_text())
    assert db['plan_sha256']==sha(run/'plan.json')and db['normalized_effective_configuration_equal']
    assert db['verifier_sha256']==sha(run/'execution-review/verify_final_databases.py')
    assert all(a['conversations']==20 and a['messages']==424 for a in db['arms'])
    assert db['arms'][0]['normalized_business_projection_sha256']==db['arms'][1]['normalized_business_projection_sha256']
    audit=run/'network-audit.log';assert not audit.exists()or not audit.read_bytes()
    assert(result['request_count'],result['measured_requests'],result['warmups'],result['candidate_accounting_instances'])==(40,32,8,20)
    assert result['provider_calls']==result['external_calls']==result['paid_spend_usd']==0
    receipt={'status':'DIAGNOSTIC_WAITS_EXECUTION_INDEPENDENT_REVIEW_PASS','reviewer':'/root/packet_review','not_a_gate':True,
        'plan_sha256':sha(run/'plan.json'),'result_sha256':sha(run/'result.json'),'analysis_sha256':sha(run/'analysis.json'),
        'analyzer_sha256':sha(run/'analyze.py'),'verifier_sha256':sha(Path(__file__)),'worker_receipts':result['receipts_sha256'],
        'database_verification_sha256':sha(dbpath),'requests':40,'measured':32,'warmups':8,'candidate_accounting_instances':20,
        'event_counts':dict(event_counts),'complete_interval_counts':dict(interval_counts),'interval_validation_and_unions_independently_reconstructed':True,
        'signed_pair_summary':analysis['summary'],'order_medians_ms':analysis['order_medians_ms'],'official_g6_status':'CONTROLLED_G6_FAIL',
        'reviewer_api_calls':0,'reviewer_database_calls':0,'reviewer_docker_calls':0,'external_calls':0,'observed_guard_attempts':0,'spend_usd':'0',
        'causal_order_or_wait_share_established':False,'limitations':['Fixed source order is confounded with language/path cells','SQL helper spans and SDK helper handoffs are not all server/scheduler waits','GC tape association is process-global, not request causation','Raw candidate chains validated by reviewed worker but not retained for separate raw replay','Parent executed final read-only DB verifier; reviewer inspected source/receipt']}
    out=run/'execution-review/receipt.json';assert not out.exists();out.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items()if k not in('worker_receipts','signed_pair_summary')},indent=2))


if __name__=='__main__':main()
