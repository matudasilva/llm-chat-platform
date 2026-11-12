"""Offline aggregate descriptive analysis; no gate decision."""
import hashlib,json,statistics
from pathlib import Path
ROOT=Path.cwd()
p=ROOT/'.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106130053-rev2/diagnosis/aggregate-runs/261106213253'
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
plan=json.loads((p/'plan.json').read_text()); result=json.loads((p/'result.json').read_text())
assert result['plan_sha256']==sha(p/'plan.json')
for name,digest in result['receipts_sha256'].items():assert sha(p/name)==digest
arms={a:[] for a in ('c0','c1')}
for arm in arms:
 for f in sorted(p.glob(arm+'-*.json')):
  doc=json.loads(f.read_text());assert doc['config_identity']==plan['config_sha256'][arm]
  arms[arm].extend(doc['samples'])
 assert len(arms[arm])==20
 for row in arms[arm]:
  assert row['status']=='PASS'
  assert row['preparation_ns']==row['primary_dispatch_ns']-row['start_ns']>=0
  assert row['process_cpu_ns']==row['primary_cpu_ns']-row['start_cpu_ns']>=0
 assert sum(r['warmup'] for r in arms[arm])==4
measured={arm:{r['sample_id']:r for r in rows if not r['warmup']} for arm,rows in arms.items()}
assert measured['c0'].keys()==measured['c1'].keys()
for key in measured['c0']:assert measured['c0'][key]['dispatches']==measured['c1'][key]['dispatches']
summary=[]
for category in ('document','history','combined','empty'):
 ids=[key for key,r in measured['c0'].items() if r['category']==category];assert len(ids)==4
 row={'category':category,'paired_cases':len(ids)}
 for arm in arms:
  for field in ('preparation_ns','process_cpu_ns'):
   values=[measured[arm][key][field]/1e6 for key in ids]
   row[arm+'_'+field+'_median_ms']=statistics.median(values)
   row[arm+'_'+field+'_range_ms']=[min(values),max(values)]
 for field in ('preparation_ns','process_cpu_ns'):
  row['paired_'+field+'_delta_median_ms']=statistics.median([(measured['c1'][key][field]-measured['c0'][key][field])/1e6 for key in ids])
 summary.append(row)
analysis={'status':'AGGREGATE_DIAGNOSTIC_ANALYSIS_NOT_A_GATE','plan_sha256':sha(p/'plan.json'),'summary':summary,'paired_samples':[{'sample_id':key,'category':measured['c0'][key]['category'],'wall_delta_ms':(measured['c1'][key]['preparation_ns']-measured['c0'][key]['preparation_ns'])/1e6,'cpu_delta_ms':(measured['c1'][key]['process_cpu_ns']-measured['c0'][key]['process_cpu_ns'])/1e6} for key in measured['c0']],'limits':['N=4 per category, descriptive only','Process CPU covers all worker threads and background activity','No causal per-function attribution or wait estimate from wall minus CPU','No p95 correction, threshold relaxation or official G6 replacement']}
(p/'analysis.json').write_text(json.dumps(analysis,indent=2)+'\n')
(p/'analyze.py').write_text(Path(__file__).read_text())
print(json.dumps(summary,indent=2))
