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


from collections import defaultdict
import math
LABELS={'history.read','rag.total','rag.rewrite','rag.hybrid','rag.rerank','context.final_cap','provider.payload','sql.cursor'}

def chain(row):
 snap=row['c1_snapshot'];rid=row['request_id'];uid=row['accounting_instance_id'];assert snap['instance_id']==uid and str(UUID(uid))==uid and snap['correlation_id']==rid and snap['valid']is True and snap['closed']is True
 recs=snap['records'];assert len(recs)==snap['count'] and recs[0]['stage']=='request.start'and recs[-1]['stage']=='request.end'and recs[-1]['data']['outcome']=='returned'and recs[-1]['data']['valid'];prev='0'*64
 for i,r in enumerate(recs):
  assert type(r['ordinal'])is int and r['ordinal']==i and r['previous']==prev
  raw=json.dumps({k:v for k,v in r.items()if k!='hash'},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode();assert hashlib.sha256(raw).hexdigest()==r['hash'];prev=r['hash']
 assert recs[0]['data']==dict(instance_id=uid,correlation_id=rid)
 scopes=[r for r in recs if r['stage']=='scope'];assert len(scopes)==1 and scopes[0]['data']==dict(tenant_sha256=hashlib.sha256(row['tenant_id'].encode()).hexdigest(),conversation=row['conversation_id'])
 starts=[r for r in recs if r['stage']=='invocation.start'];ends=[r for r in recs if r['stage']=='invocation.end'];assert len(starts)==len(ends)==2
 assert [(r['invocation'],r['purpose'])for r in starts]==[(r['invocation'],r['purpose'])for r in ends];assert [r['purpose']for r in starts]==['rewrite','primary']and all(r['data']['outcome']=='returned'for r in ends)
 dispatched=[r for r in recs if r['stage']=='transport.dispatched'];assert len(dispatched)==len(row['native_sends'])==2
 for i,(r,send,purpose)in enumerate(zip(dispatched,row['native_sends'],('rewrite','primary'))):
  assert send['instance_id']==uid and send['correlation_id']==rid and r['invocation']==send['invocation']and r['purpose']==send['purpose']==purpose
  assert send['application_attempt']==send['sdk_attempt']==1 and send['send_ordinal']==i and send['adapter']=='bedrock'
  assert r['data']=={k:v for k,v in send.items()if k not in('instance_id','correlation_id','invocation','purpose')}
  assert row['dispatches'][i]==dict(purpose=purpose,sha256=send['payload_sha256'])
 return len(recs)

def coarse(row):
 obs=row['observation'];assert obs['valid']is True and len(obs['events'])<=128 and len(obs['wait_events'])<=256
 evs=obs['events'];by={};counts=Counter()
 for e in evs:
  assert e['request_id']==row['request_id']and e['label']in LABELS and type(e['id'])is int and e['id']>0 and e['id']not in by and type(e['thread'])is int
  assert all(type(e[k])is int and e[k]>=0 for k in('start_ns','end_ns','start_thread_cpu_ns','end_thread_cpu_ns'));assert e['end_ns']>=e['start_ns']>=row['start_ns']and e['end_thread_cpu_ns']>=e['start_thread_cpu_ns'];by[e['id']]=e;counts[e['label']]+=1
 for e in evs:
  if e['parent']is not None:
   parent=by[e['parent']];assert parent['id']<e['id']and parent['start_ns']<=e['start_ns']<=e['end_ns']<=parent['end_ns']
 assert all(counts[k]==v for k,v in {'history.read':1,'rag.total':1,'rag.rewrite':1,'rag.hybrid':1,'context.final_cap':1,'provider.payload':2}.items());assert counts['rag.rerank']in(0,1)and counts['sql.cursor']>0
 assert sorted(e['purpose']for e in evs if e['label']=='provider.payload')==['primary','rewrite']
 groups=intervals(obs['wait_events'],row['request_id'])
 a,b=row['start_ns'],row['primary_dispatch_ns']
 def clipped(evs):return[(max(a,e['start_ns']),min(b,e['end_ns']))for e in evs if min(b,e['end_ns'])>max(a,e['start_ns'])]
 cov=union_length(clipped(evs));summary=dict(coarse_union_ns=cov,uncovered_preparation_ns=b-a-cov,labels={k:dict(calls=counts[k],preparation_union_ns=union_length(clipped([e for e in evs if e['label']==k])),full_thread_cpu_ns=sum(e['end_thread_cpu_ns']-e['start_thread_cpu_ns']for e in evs if e['label']==k))for k in sorted(LABELS)})
 assert summary==row['stage_summary'];assert cov<=b-a
 return len(evs),len(obs['wait_events']),len(groups)

def delta(a,b,cpus,topology):
 for x in(a,b):assert x['affinity']==x['effective_cpuset']==cpus and x['cpu_max']=='200000 100000'and x['topology']==topology
 assert a['cpu_stat'].keys()==b['cpu_stat'].keys();d={k:b['cpu_stat'][k]-v for k,v in a['cpu_stat'].items()};assert all(v>=0 for v in d.values());return d

def main():
 from experiments.production_graduation.gate_validation.validate_g123 import check_p2
 check_p2();p=Path(__file__).resolve().parent.parent;load=lambda f:json.loads(f.read_text());sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();plan=load(p/'plan.json');result=load(p/'result.json');review=load(p/'independent-review.json');analysis=load(p/'execution-review/analysis.json')
 assert sha(p/'independent-review.json')=='e1bb42feaf025d582cb436be66b721c04b2c15e05eb1389333ac03998ea0ba1b';assert review['plan_sha256']==result['plan_sha256']==sha(p/'plan.json');assert review['fixtures_sha256']==sha(p/'fixtures.json')and review['preparation_sha256']==sha(p/'preparation.json')
 for f,h in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():assert sha(Path(f))==h
 arms={'c0':{},'c1':{}};ids=set();rawhash={};obhash={};last=-1;totals=Counter();cross_sdk=0
 for entry in plan['arm_cell_order']:
  arm=entry['arm'];key=arm+'-'+entry['cell']+'-b0';w=load(p/(key+'.json'));assert sha(p/(key+'.json'))==result['worker_receipts'][key+'.json'];rawhash[key+'.json']=sha(p/(key+'.json'));assert all(w[k]==entry[k]for k in('arm','cell','block'))and w['full_c1'];assert w['config_identity']==plan['config_sha256'][arm]and w['seed_probe']==plan['seed_probe'];assert w['provider_calls']==w['external_calls']==0
  assert delta(w['resources_before'],w['resources_after'],[0,2],plan['cpu_topology'])==w['cpu_stat_delta']
  expected=[s for s in plan['samples']if s['language']+'-'+s['protocol']==entry['cell']];assert len(expected)==len(w['samples'])==45 and [s['warmup']for s in expected]==[True]*20+[False]*25
  marker=load(p/(key+'-started.json'));assert marker['entry']==entry and marker['plan_sha256']==sha(p/'plan.json');loopid=None
  for row,sample in zip(w['samples'],expected):
   assert all(type(row[k])is type(v)and row[k]==v for k,v in sample.items());assert row['status']=='PASS'and row['error']is None
   assert row['sample_id']not in arms[arm];arms[arm][row['sample_id']]=row;uid=row['accounting_instance_id'];assert uid not in ids;ids.add(uid);totals['c1_records']+=chain(row)
   assert all(type(row[k])is int for k in('start_ns','primary_dispatch_ns','preparation_ns'));assert row['start_ns']>last and row['primary_dispatch_ns']>=row['start_ns'];last=row['primary_dispatch_ns'];assert row['preparation_ns']==last-row['start_ns']
   assert row['request_id']==str(uuid5(UUID(plan['namespace']),'request/'+row['sample_id']))and row['conversation_id']==str(uuid5(UUID(plan['namespace']),row['sample_id']))
   a,b=row['start_counters'],row['primary_counters'];tid=row['loop_native_id'];assert type(tid)is int and tid>0
   if loopid is None:loopid=tid
   assert tid==loopid and a['reader_native_id']==a['loop_native_id']==b['loop_native_id']==tid and b['reader_native_id']>0
   assert set(a)==set(b)=={'process_cpu_ns','voluntary','involuntary','loop_native_id','reader_native_id'};assert all(type(x)is int and x>=0 for c in(a,b)for x in c.values());assert all(b[k]>=a[k]for k in('process_cpu_ns','voluntary','involuntary'));assert b['reader_native_id']!=tid;cross_sdk+=1
   if arm=='c0':assert row['observation']is None and 'stage_summary'not in row
   else:
    c,ww,g=coarse(row);totals.update(coarse_events=c,wait_events=ww,wait_groups=g)
  obs=load(p/(key+'-observations.json'));assert obs['entry']==entry;obhash[key+'-observations.json']=sha(p/(key+'-observations.json'));assert delta(obs['pg_before'],obs['pg_after'],[4,6],plan['cpu_topology'])==obs['pg_delta']
  a,b=obs['host_before'],obs['host_after'];assert a['start_ns']<=a['end_ns']<w['samples'][0]['start_ns']<=w['samples'][-1]['primary_dispatch_ns']<b['start_ns']<=b['end_ns'];assert set(a['cpu_ticks'])==set(b['cpu_ticks'])=={f'cpu{i}'for i in range(8)}
  hd={k:[y-x for x,y in zip(a['cpu_ticks'][k],b['cpu_ticks'][k])]for k in a['cpu_ticks']};assert all(min(v)>=0 for v in hd.values())and hd==obs['host_delta']
  for mode in('c0','c1'):
   aa,bb=obs['db_before'][mode]['counters'],obs['db_after'][mode]['counters'];assert all(aa[k]==bb[k]for k in('datid','datname','stats_reset'));assert {k:bb[k]-aa[k]for k in obs['db_delta'][mode]}==obs['db_delta'][mode]and min(obs['db_delta'][mode].values())>=0
 assert len(ids)==360 and cross_sdk==360 and all(len(r)==180 for r in arms.values());assert len(list(p.glob('c?-*-started.json')))==8
 for key,row in arms['c0'].items():assert row['dispatches']==arms['c1'][key]['dispatches']
 assert sum(r['warmup']for a in arms.values()for r in a.values())==160
 groups=[]
 for cell in('EN-json','EN-sse','ES-json','ES-sse'):
  published=next(c for c in result['cells']if c['cell']==cell)
  for arm,mode in(('c0','off'),('c1','on')):
   rows=[r for r in arms[arm].values()if not r['warmup']and r['language']+'-'+r['protocol']==cell];assert len(rows)==25;values=sorted(r['preparation_ns']for r in rows);assert published['modes'][mode]==dict(n=25,preparation_p50_ns=values[12],preparation_p95_ns=values[23],process_cpu_values_ns=[r['primary_counters']['process_cpu_ns']-r['start_counters']['process_cpu_ns']for r in rows])
   if arm=='c1':
    for cat in('document','history','combined','empty'):
     rr=[r for r in rows if r['category']==cat];groups.append(dict(cell=cell,category=cat,n=len(rr),preparation_median_ns=median(r['preparation_ns']for r in rr),process_cpu_median_ns=median(r['primary_counters']['process_cpu_ns']-r['start_counters']['process_cpu_ns']for r in rr),uncovered_median_ns=median(r['stage_summary']['uncovered_preparation_ns']for r in rr),stage_wall_medians_ns={k:median(r['stage_summary']['labels'][k]['preparation_union_ns']for r in rr)for k in sorted(LABELS)}))
 assert groups==analysis['groups'];assert(result['request_count'],result['measured'],result['warmups'],result['accounting_instances'])==(360,200,160,360);assert result['external_calls']==result['paid_requests']==0 and result['spend_usd']=='0';assert result['status']=='STAGE_DIAGNOSTIC_COMPLETE_CAUSE_REQUIRES_REVIEW'
 final=load(p/'execution-review/final-databases-verification.json');assert final['status']=='STAGE_DIAGNOSTIC_FINAL_DATABASES_READONLY_VERIFIER_PASS'and final['verifier_sha256']==sha(p/'execution-review/verify_final_databases.py');assert final['plan_sha256']==sha(p/'plan.json')and final['original_source_preserved']and final['normalized_effective_configuration_equal'];assert all(x['conversations']==180 and x['messages']==4584 and x['original_history_messages']==4224 and x['normalized_generated_message_ids']==360 for x in final['arms']);assert len({x['normalized_business_projection_sha256']for x in final['arms']})==1
 audit=p/'network-audit.log';assert not audit.exists()or not audit.read_bytes()
 out=dict(status='STAGE_DIAGNOSTIC_INDEPENDENT_RAW_REPLAY_PASS',plan_sha256=sha(p/'plan.json'),result_sha256=sha(p/'result.json'),verifier_sha256=sha(Path(__file__)),worker_receipts=rawhash,observation_receipts=obhash,requests=360,measured=200,warmups=160,unique_c1_contexts=360,actual_cross_thread_loop_counter_targets_verified=360,totals=dict(totals),groups=groups,final_db_receipt_sha256=sha(p/'execution-review/final-databases-verification.json'),official_g6_status='CONTROLLED_G6_FAIL',causal_explanation_proven=False)
 (p/'execution-review/independent-raw-replay.json').write_text(json.dumps(out,indent=2)+'\n');print(out['status']);print(out['totals'])
if __name__=='__main__':main()
