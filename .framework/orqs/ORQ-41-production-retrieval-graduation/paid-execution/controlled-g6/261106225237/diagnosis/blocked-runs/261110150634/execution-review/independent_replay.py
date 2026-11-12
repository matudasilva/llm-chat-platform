"""Pure independent raw blocked A/A replay; never service operations."""
import json,hashlib,math
from pathlib import Path
from uuid import UUID,uuid5
from collections import Counter
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

def main():
 check_p2();p=Path(__file__).resolve().parent.parent;sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();load=lambda f:json.loads(f.read_text())
 plan=load(p/'plan.json');result=load(p/'result.json');review=load(p/'independent-review.json')
 assert review['status']=='BLOCKED_AA_HARNESS_REVIEW_PASS'and sha(p/'independent-review.json')=='9783d238f83f37b55abb7f72f41db20643ddb504e6777a1bcbbe4ffe3fba5d0c'
 assert review['plan_sha256']==result['plan_sha256']==sha(p/'plan.json');assert review['fixtures_sha256']==sha(p/'fixtures.json');assert review['preparation_sha256']==sha(p/'preparation.json')
 for f,h in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():assert sha(Path(f))==h
 assert load(p/'execution-authorization.json')['plan_sha256']==load(p/'execution-started.json')['plan_sha256']==sha(p/'plan.json')
 assert plan['images']['c0']==plan['images']['c1'];assert len(plan['samples'])==720 and len(plan['arm_cell_order'])==32
 def delta(a,b,cpus):
  for x in(a,b):assert x['affinity']==x['effective_cpuset']==cpus and x['cpu_max']=='200000 100000'and x['topology']==plan['cpu_topology']
  assert a['cpu_stat'].keys()==b['cpu_stat'].keys();d={k:b['cpu_stat'][k]-v for k,v in a['cpu_stat'].items()};assert all(v>=0 for v in d.values());return d
 arms={'c0':{},'c1':{}};ids=set();last=-1;observations={};rawhash={};throttles=[]
 assert len(result['observations'])==32
 for ei,e in enumerate(plan['arm_cell_order']):
  key=f"{e['arm']}-{e['cell']}-b{e['block']}";name=key+'.json';w=load(p/name);assert sha(p/name)==result['worker_receipts'][name];rawhash[name]=sha(p/name)
  assert all(w[k]==e[k]for k in('arm','cell','block'));assert w['full_c1']and w['config_identity']==plan['config_sha256'][e['arm']]and w['seed_probe']==plan['seed_probe'];assert w['provider_calls']==w['external_calls']==0
  assert delta(w['resources_before'],w['resources_after'],[0,2])==w['cpu_stat_delta'];throttles.append(('api',key,w['cpu_stat_delta']['nr_throttled'],w['cpu_stat_delta']['throttled_usec']))
  expected=[s for s in plan['samples']if s['language']+'-'+s['protocol']==e['cell']and s['block']==e['block']];assert len(expected)==len(w['samples'])==45;assert [x['warmup']for x in expected]==[True]*20+[False]*25
  marker=load(p/(key+'-started.json'));assert marker['entry']==e and marker['plan_sha256']==sha(p/'plan.json')
  for row,s in zip(w['samples'],expected):
   assert all(type(row[k])is type(v)and row[k]==v for k,v in s.items());assert row['status']=='PASS'and row['error']is None
   assert row['sample_id']not in arms[e['arm']];arms[e['arm']][row['sample_id']]=row
   uid=row['accounting_instance_id'];assert str(UUID(uid))==uid and uid not in ids;ids.add(uid)
   assert row['request_id']==str(uuid5(UUID(plan['namespace']),'request/'+row['sample_id']));assert row['conversation_id']==str(uuid5(UUID(plan['namespace']),row['sample_id']))
   assert all(type(row[k])is int for k in('start_ns','primary_dispatch_ns','preparation_ns'));assert row['start_ns']>last and row['primary_dispatch_ns']>=row['start_ns'];last=row['primary_dispatch_ns'];assert row['preparation_ns']==row['primary_dispatch_ns']-row['start_ns'];assert [x['purpose']for x in row['dispatches']]==['rewrite','primary'];assert all(len(x['sha256'])==64 and int(x['sha256'],16)>=0 for x in row['dispatches'])
  ob=load(p/(key+'-observations.json'));assert ob==result['observations'][ei]and ob['entry']==e;observations[key+'-observations.json']=sha(p/(key+'-observations.json'))
  pg=delta(ob['pg_before'],ob['pg_after'],[4,6]);assert pg==ob['pg_delta'];throttles.append(('pg',key,pg['nr_throttled'],pg['throttled_usec']))
  a,b=ob['host_before'],ob['host_after'];assert a['start_ns']<=a['end_ns']<=b['start_ns']<=b['end_ns'];assert set(a['cpu_ticks'])==set(b['cpu_ticks'])=={f'cpu{i}'for i in range(8)}
  hd={}
  for k in a['cpu_ticks']:
   aa,bb=a['cpu_ticks'][k],b['cpu_ticks'][k];assert len(aa)==len(bb)>=8;hd[k]=[y-x for x,y in zip(aa,bb)];assert all(v>=0 for v in hd[k])
  assert hd==ob['host_delta'];assert all(set(h['reported_frequency_khz'])=={'0','2','4','6'}and all(v>0 for v in h['reported_frequency_khz'].values())for h in(a,b))
  for arm in('c0','c1'):
   a,b=ob['db_before'][arm]['counters'],ob['db_after'][arm]['counters'];assert all(a[k]==b[k]for k in('datid','datname','stats_reset'));dd={k:b[k]-a[k]for k in ob['db_delta'][arm]};assert all(v>=0 for v in dd.values())and dd==ob['db_delta'][arm]
   for state in('db_before','db_after'):assert len(ob[state][arm]['maintenance'])==7
 assert len(ids)==1440 and all(len(a)==720 for a in arms.values());assert len(result['worker_receipts'])==32
 assert len(list(p.glob('c?-*-started.json')))==32
 for k,a in arms['c0'].items():assert a['dispatches']==arms['c1'][k]['dispatches']
 assert sum(r['warmup']for a in arms.values()for r in a.values())==640
 def quant(values,q):return sorted(values)[max(0,math.ceil(len(values)*q)-1)]
 cells=[];blocks=[]
 for cell in('EN-json','EN-sse','ES-json','ES-sse'):
  vals={arm:[x['preparation_ns']for x in rows.values()if not x['warmup']and x['language']+'-'+x['protocol']==cell]for arm,rows in arms.items()};assert all(len(v)==100 for v in vals.values())
  for arm in arms:
   rows=[x for x in arms[arm].values()if not x['warmup']and x['language']+'-'+x['protocol']==cell];assert Counter(x['category']for x in rows)==dict.fromkeys(('document','history','combined','empty'),25);assert set(Counter(x['case_id']for x in rows).values())=={5}
  c=next(c for c in result['cells']if c['cell']==cell)
  for arm,v in vals.items():
   for k,q in(('p50',.5),('p95',.95),('p99',.99),('max',1)):assert c[arm+'_'+k+'_ns']==quant(v,q)
  a,b=quant(vals['c0'],.95),quant(vals['c1'],.95);status='PASS'if a*100<=b*105 and b*100<=a*105 else'FAIL';assert status==c['status'];cells.append(dict(cell=cell,a_p95_ns=a,b_p95_ns=b,signed_percent=(b-a)*100/a,status=status))
  for block in range(4):
   first=next(e['arm']for e in plan['arm_cell_order']if e['cell']==cell and e['block']==block)
   for arm in arms:
    ds=[x['preparation_ns']for x in arms[arm].values()if not x['warmup']and x['language']+'-'+x['protocol']==cell and x['block']==block];assert len(ds)==25;blocks.append(dict(cell=cell,block=block,arm=arm,first=first==arm,n=25,p50_ns=quant(ds,.5),p95_ns=quant(ds,.95),max_ns=max(ds)))
 assert blocks==result['descriptive_blocks'];assert result['status']=='AA_CALIBRATION_FAIL'and sum(c['status']=='FAIL'for c in cells)==2;assert(result['request_count'],result['measured'],result['warmups'],result['accounting_instances'])==(1440,800,640,1440)
 assert result['external_calls']==result['paid_requests']==0 and result['spend_usd']=='0';final=load(p/'database-final-verification.json');assert sha(p/'database-final-verification.json')==result['final_database_receipt_sha256'];assert all(x['conversations']==720 and x['messages']==18720 and x['generated_message_ids']==1440 for x in final['databases']);assert len({x['normalized_business_sha256']for x in final['databases']})==1
 assert not(p/'network-audit.log').exists()or not(p/'network-audit.log').read_bytes()
 baseline=load(p/'execution-review/scope-before.json')
 for f,h in baseline.items():assert sha(Path(f))==h
 receipt=dict(status='BLOCKED_AA_EXECUTION_INDEPENDENT_REPLAY_VERIFIED_FAIL',reviewer='/root/packet_review',plan_sha256=sha(p/'plan.json'),fixtures_sha256=sha(p/'fixtures.json'),prospective_review_sha256=sha(p/'independent-review.json'),result_sha256=sha(p/'result.json'),verifier_sha256=sha(Path(__file__)),worker_receipts=rawhash,observation_receipts=observations,cells=cells,requests=1440,measured=800,warmups=640,unique_c1_instances=1440,all_resource_host_database_deltas_independently_recomputed=True,throttling_deltas=throttles,protected_files_independently_rehashed=len(baseline),parent_post_execution_proof_pending=True,final_database_receipt_sha256=sha(p/'database-final-verification.json'),reviewer_api_calls=0,reviewer_database_calls=0,reviewer_docker_calls=0,external_provider_calls=0,spend_usd='0',official_g6_status='CONTROLLED_G6_FAIL',new_blocker_high_medium_findings=[])
 out=p/'execution-review/independent-replay.json';out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(cells,indent=2));print(receipt['status'])
if __name__=='__main__':main()
