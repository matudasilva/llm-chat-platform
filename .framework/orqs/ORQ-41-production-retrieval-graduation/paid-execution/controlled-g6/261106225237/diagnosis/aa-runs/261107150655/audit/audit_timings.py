"""Offline derived distributions; no new measurement or causal attribution."""
import hashlib,json,statistics
from pathlib import Path
OUT=Path(__file__).resolve().parent;RUN=OUT.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=json.loads((RUN/'plan.json').read_text());result=json.loads((RUN/'result.json').read_text())
assert result['plan_sha256']==sha(RUN/'plan.json')
fixtures={f['sample']['sample_id']:f for f in json.loads((RUN/'fixtures.json').read_text())}
def business(row):
 f=fixtures[row['sample_id']];s=f['sample']
 return hashlib.sha256(json.dumps(dict(category=s['category'],tenant=s['tenant_id'],message=s['message'],history=f['messages']),sort_keys=True).encode()).hexdigest()
workers={};paired={}
for cell in ('EN-json','EN-sse','ES-json','ES-sse'):
 arms={}
 for arm in ('c0','c1'):
  name=arm+'-'+cell+'.json';assert sha(RUN/name)==result['worker_receipts'][name]
  allrows=json.loads((RUN/name).read_text())['samples'];rows=[r for r in allrows if not r['warmup']];assert len(rows)==100
  arms[arm]=rows
  repeats=[]
  for slot in range(20):
   group=[r for r in rows if (int(r['sample_id'].rsplit('/',1)[1])-5)%20==slot]
   assert len(group)==5 and len({business(r) for r in group})==1
   repeats.append(dict(slot=slot,category=group[0]['category'],business_sha256=business(group[0]),durations_ms=[r['preparation_ns']/1e6 for r in group],late_minus_early_ms=(group[-1]['preparation_ns']-group[0]['preparation_ns'])/1e6))
  workers[name]=dict(iteration_medians_ms=[statistics.median(r['preparation_ns']/1e6 for r in rows if (int(r['sample_id'].rsplit('/',1)[1])-5)//20==i) for i in range(5)],
   repeats=repeats,late_minus_early_median_ms=statistics.median(r['late_minus_early_ms'] for r in repeats),
   tail_ranks95_to100=[dict(sample_id=r['sample_id'],category=r['category'],duration_ms=r['preparation_ns']/1e6) for r in sorted(rows,key=lambda x:x['preparation_ns'])[94:]])
 paired[cell]={category:dict(median_delta_ms=statistics.median((b['preparation_ns']-a['preparation_ns'])/1e6 for a,b in zip(arms['c0'],arms['c1']) if a['category']==category),
  arm_medians_ms={arm:statistics.median(r['preparation_ns']/1e6 for r in arms[arm] if r['category']==category) for arm in ('c0','c1')}) for category in ('document','history','combined','empty')}
result=dict(status='RETAINED_TIMING_AUDIT_COMPLETE',workers=workers,category_pairs=paired,source_sha256=sha(Path(__file__)),
 interpretation='Repeated business cases use fresh identities; trends and tails are descriptive, not evidence that GC or retention caused the p95 failure',api_requests=0,database_queries=0,provider_calls=0,external_calls=0)
(OUT/'timing-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print({k:round(v['late_minus_early_median_ms'],3) for k,v in workers.items()})
