"""Offline descriptive analysis only. Does not alter gate populations or results."""
import hashlib,json,statistics
from collections import Counter
from pathlib import Path
RUN=Path(__file__).resolve().parent.parent
result=json.loads((RUN/'result.json').read_text())
for name,digest in result['worker_receipts'].items():
    assert hashlib.sha256((RUN/name).read_bytes()).hexdigest()==digest

def quantile(values,p):
    return sorted(values)[(p*len(values)+99)//100-1]

cells=[]
for language in ('EN','ES'):
 for protocol in ('json','sse'):
    arms={a:json.loads((RUN/f'{a}-{language}-{protocol}.json').read_text())['samples'] for a in ('c0','c1')}
    measured={a:[x for x in rows if not x['warmup']] for a,rows in arms.items()}
    paired={a:{x['sample_id']:x for x in rows} for a,rows in measured.items()}
    assert len(paired['c0'])==len(paired['c1'])==100 and paired['c0'].keys()==paired['c1'].keys()
    tail={}
    for arm,rows in measured.items():
        ordered=sorted(rows,key=lambda x:x['preparation_ns'])
        tail[arm]={'p95_sample':{k:ordered[94][k] for k in ('sample_id','category','preparation_ns')},
                   'top6_categories':dict(Counter(x['category'] for x in ordered[94:]))}
    groups=[]
    for category in ('document','history','combined','empty'):
        matching=[x for x in measured['c0'] if x['category']==category]
        deltas=[(paired['c1'][x['sample_id']]['preparation_ns']-x['preparation_ns'])/1e6 for x in matching]
        groups.append({'category':category,'n_pairs':len(deltas),'median_observed_pair_delta_ms':statistics.median(deltas),
                       'candidate_slower_pairs':sum(x>0 for x in deltas)})
    repeats=[]
    for repeat in range(5):
        values={arm:[x['preparation_ns'] for x in rows if (int(x['sample_id'].rsplit('/',1)[1])-5)//20==repeat] for arm,rows in measured.items()}
        assert all(len(v)==20 for v in values.values())
        repeats.append({'repeat_position':repeat,'n_per_arm':20,
                        **{arm+'_median_ms':statistics.median(v)/1e6 for arm,v in values.items()}})
    cells.append({'language':language,'protocol':protocol,'tail':tail,'categories':groups,'repeat_positions':repeats})
out={'status':'OFFLINE_DESCRIPTIVE_DIAGNOSIS','gate_unchanged':result['status'],'cells':cells,
     'limitations':['Posthoc strata are not new gates','Arms are separate processes, not temporally simultaneous pairs','No per-function timing was retained; these deltas do not establish causal attribution','No subtraction or reweighting of the approved p95 population'],
     'new_requests':0,'source_changes':False,'external_calls':0,'spend_usd':'0'}
(RUN/'diagnosis/offline-analysis.json').write_text(json.dumps(out,indent=2)+'\n')
for cell in cells:
 print(cell['language'],cell['protocol'],[(x['category'],round(x['median_observed_pair_delta_ms'],2),x['candidate_slower_pairs']) for x in cell['categories']], 'tails', {a:v['top6_categories'] for a,v in cell['tail'].items()})
