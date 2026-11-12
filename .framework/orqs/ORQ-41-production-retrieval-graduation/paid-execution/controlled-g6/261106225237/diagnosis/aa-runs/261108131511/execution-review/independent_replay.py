"""Independent retained A/A replay; no requests or service operations."""
import json,hashlib
from pathlib import Path
from uuid import UUID,uuid5
from collections import Counter
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

def main():
 check_p2();p=Path(__file__).resolve().parent.parent;sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
 plan=json.loads((p/'plan.json').read_text());r=json.loads((p/'result.json').read_text());approval=json.loads((p/'independent-review.json').read_text())
 assert r['plan_sha256']==approval['plan_sha256']==sha(p/'plan.json');assert approval['status']=='AA_CALIBRATION_HARNESS_REVIEW_PASS';assert sha(p/'protocol.md')==approval['protocol_sha256']
 assert plan['images']['c0']==plan['images']['c1'];assert plan['full_c1_both_arms']
 for f,h in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():assert sha(Path(f))==h
 assert set(r['worker_receipts'])=={f'{a}-{l}-{q}.json'for a in ('c0','c1')for l in ('EN','ES')for q in ('json','sse')}
 def resources(a,b,cpus):
  for proof in (a,b):
   assert proof['affinity']==proof['effective_cpuset']==cpus and proof['cpu_max']=='200000 100000' and proof['topology']==plan['cpu_topology']
  assert a['cpu_stat'].keys()==b['cpu_stat'].keys()
  delta={k:b['cpu_stat'][k]-v for k,v in a['cpu_stat'].items()};assert all(v>=0 for v in delta.values());return delta
 arms={'c0':{},'c1':{}};seen=set();last=-1;resource_checks=[]
 assert len(r['postgres_cell_counters'])==8
 for i,cell in enumerate(plan['arm_cell_order']):
  arm=cell['arm'];name=arm+'-'+cell['cell'];assert sha(p/(name+'.json'))==r['worker_receipts'][name+'.json'];w=json.loads((p/(name+'.json')).read_text())
  assert w['arm']==arm and w['full_c1'] and w['config_identity']==plan['config_sha256'][arm];assert w['provider_calls']==w['external_calls']==0
  assert resources(w['resources_before'],w['resources_after'],[0,2])==w['cpu_stat_delta'];pg=r['postgres_cell_counters'][i];assert pg['cell']==name;assert resources(pg['before'],pg['after'],[4,6])==pg['delta']
  expected=[s for s in plan['samples']if s['language']+'-'+s['protocol']==cell['cell']];assert len(expected)==len(w['samples'])==105
  assert Counter(s['category']for s in expected if not s['warmup'])==dict.fromkeys(('document','history','combined','empty'),25)
  assert sum(s['warmup']for s in expected)==5
  for row,sample in zip(w['samples'],expected):
   assert all(row[k]==sample[k]for k in ('sample_id','language','protocol','warmup','category','request_id','conversation_id'))
   assert row['status']=='PASS' and row['error']is None
   for k in ('start_ns','primary_dispatch_ns','preparation_ns'):assert type(row[k])is int
   assert row['primary_dispatch_ns']>=row['start_ns']>last;last=row['primary_dispatch_ns'];assert row['preparation_ns']==row['primary_dispatch_ns']-row['start_ns']
   assert row['request_id']==str(uuid5(UUID(plan['namespace']),'request/'+row['sample_id']));assert row['conversation_id']==str(uuid5(UUID(plan['namespace']),row['sample_id']))
   uid=row['accounting_instance_id'];assert str(UUID(uid))==uid and uid not in seen;seen.add(uid)
   assert [d['purpose']for d in row['dispatches']]==['rewrite','primary'];assert row['sample_id']not in arms[arm];arms[arm][row['sample_id']]=row
  resource_checks.append(name)
 assert len(seen)==840 and all(len(a)==420 for a in arms.values())
 assert sum(x['warmup']for a in arms.values()for x in a.values())==40
 for key,a in arms['c0'].items():assert a['dispatches']==arms['c1'][key]['dispatches']
 cells=[]
 for c in r['cells']:
  vals={arm:sorted(x['preparation_ns']for x in aa.values()if x['language']==c['language']and x['protocol']==c['protocol']and not x['warmup'])for arm,aa in arms.items()}
  assert all(len(v)==100 for v in vals.values())
  for arm,label in [('c0','baseline'),('c1','candidate')]:
   for metric,index in [('p50',49),('p95',94),('p99',98),('max',99)]:assert vals[arm][index]==c[label+'_'+metric+'_ns']
  a,b=vals['c0'][94],vals['c1'][94];status='PASS'if a*100<=b*105 and b*100<=a*105 else'FAIL';assert c['status']==status and c['payload_and_call_parity'];cells.append(dict(cell=c['language']+'-'+c['protocol'],a_p95_ns=a,b_p95_ns=b,signed_percent=(b-a)*100/a,status=status))
 assert len(cells)==4 and sum(c['status']=='FAIL'for c in cells)==3;assert r['status']=='AA_CALIBRATION_FAIL'and r['request_count']==r['accounting_instances']==840 and r['not_a_gate']and r['symmetric_rule_percent']==5
 assert r['external_calls']==0 and r['spend_usd']=='0'and r['official_g6_status']=='CONTROLLED_G6_FAIL'
 dbp=p/'execution-review/database-final-verification.json';db=json.loads(dbp.read_text());assert db['plan_sha256']==sha(p/'plan.json');assert db['verifier_sha256']==sha(p/'execution-review/verify_final_databases.py');assert db['normalized_effective_configuration_equal'];assert all(a['conversations']==420 and a['messages']==10440 for a in db['arms']);assert len({a['normalized_business_projection_sha256']for a in db['arms']})==1
 audit=p/'network-audit.log';assert not audit.exists()or not audit.read_bytes()
 out=p/'execution-review/receipt.json';assert not out.exists();receipt=dict(status='AA_CALIBRATION_EXECUTION_INDEPENDENT_REPLAY_VERIFIED_FAIL',reviewer='/root/packet_review',plan_sha256=sha(p/'plan.json'),result_sha256=sha(p/'result.json'),verifier_sha256=sha(Path(__file__)),worker_receipts=r['worker_receipts'],database_verification_sha256=sha(dbp),requests=840,measured=800,warmups=40,unique_full_c1_instances=840,cells=cells,all_cpu_counter_deltas_recomputed=True,recorded_throttling_zero=all(x['delta']['nr_throttled']==x['delta']['throttled_usec']==0 for x in r['postgres_cell_counters']),reviewer_api_calls=0,reviewer_database_calls=0,reviewer_docker_calls=0,external_calls=0,spend_usd='0',official_g6_status='CONTROLLED_G6_FAIL',causal_attribution_established=False);out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(cells,indent=2));print(receipt['status'])
if __name__=='__main__':main()
