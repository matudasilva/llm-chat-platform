"""Offline, prespecified paired descriptive analysis. Negative favors optimized C1."""
import hashlib,json,statistics
from pathlib import Path
P=Path(__file__).resolve().parent
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
plan=json.loads((P/'plan.json').read_text());result=json.loads((P/'result.json').read_text())
assert result['status']=='C1_COPY_COMPARISON_COMPLETE' and result['plan_sha256']==sha(P/'plan.json')
for name,digest in result['receipts_sha256'].items(): assert sha(P/name)==digest
arms={arm:[] for arm in ('old','new')}
for arm in arms:
 for f in sorted(P.glob(arm+'-*.json')):
  d=json.loads(f.read_text());assert d['arm']==arm and d['config_identity']==plan['config_sha256'][arm]
  arms[arm].extend(d['samples'])
 assert len(arms[arm])==20 and sum(r['warmup'] for r in arms[arm])==4
 for r in arms[arm]:
  assert r['status']=='PASS'
  assert r['preparation_ns']==r['primary_dispatch_ns']-r['start_ns']>=0
  assert r['process_cpu_ns']==r['primary_cpu_ns']-r['start_cpu_ns']>=0
instances=[r['accounting_instance_id'] for rows in arms.values() for r in rows]
assert len(set(instances))==40 and all(instances)
indexed={arm:{r['sample_id']:r for r in rows} for arm,rows in arms.items()}
assert indexed['old'].keys()==indexed['new'].keys()
for key in indexed['old']: assert indexed['old'][key]['dispatches']==indexed['new'][key]['dispatches']
order={cell:next(x['arm'] for x in plan['arm_cell_order'] if x['cell']==cell) for cell in {x['cell'] for x in plan['arm_cell_order']}}
pairs=[]
for key,old in indexed['old'].items():
 if old['warmup']:continue
 new=indexed['new'][key];cell=old['language']+'-'+old['protocol']
 pairs.append({'sample_id':key,'category':old['category'],'cell':cell,'first':order[cell],'old_cpu_ms':old['process_cpu_ns']/1e6,'new_cpu_ms':new['process_cpu_ns']/1e6,'old_wall_ms':old['preparation_ns']/1e6,'new_wall_ms':new['preparation_ns']/1e6,'cpu_new_minus_old_ms':(new['process_cpu_ns']-old['process_cpu_ns'])/1e6,'wall_new_minus_old_ms':(new['preparation_ns']-old['preparation_ns'])/1e6})
assert len(pairs)==16

def summarize(rows):
 out={'n':len(rows)}
 for measure in ('cpu','wall'):
  values=[r[measure+'_new_minus_old_ms'] for r in rows]
  out[measure]={'median_new_minus_old_ms':statistics.median(values),'range_ms':[min(values),max(values)],'optimized_lower':sum(v<0 for v in values),'equal':sum(v==0 for v in values),'optimized_higher':sum(v>0 for v in values)}
 return out
report={'status':'C1_COMPARISON_DESCRIPTIVE_ANALYSIS_NOT_A_GATE','plan_sha256':sha(P/'plan.json'),'pairs':pairs,'overall':summarize(pairs),'by_category':{c:summarize([r for r in pairs if r['category']==c]) for c in ('document','history','combined','empty')},'by_cell':{c:summarize([r for r in pairs if r['cell']==c]) for c in sorted(order)},'by_first_arm':{a:summarize([r for r in pairs if r['first']==a]) for a in ('old','new')},'limits':['fixed counterbalanced order, not randomized','four pairs per category, one attempt','CPU includes all process threads/background activity','not a G6 p95 or uniform benefit certification']}
(P/'analysis.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'overall':report['overall'],'by_category':report['by_category'],'by_first_arm':report['by_first_arm']},indent=2))
