"""Offline descriptive replay under the prospectively frozen protocol."""
import hashlib
import json
import statistics
from pathlib import Path

from experiments.production_graduation.gate_validation.validate_g123 import check_p2
from experiments.production_graduation.gate_validation.wait_observer import validate_request_intervals

check_p2()
OUT=Path(__file__).resolve().parent
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
plan=json.loads((OUT/'plan.json').read_text())
result=json.loads((OUT/'result.json').read_text())
review=json.loads((OUT/'independent-review.json').read_text())
assert result['status']=='DIAGNOSTIC_CROSSOVER_COMPLETE'
assert result['plan_sha256']==review['plan_sha256']==sha(OUT/'plan.json')
assert review['status']=='DIAGNOSTIC_CROSSOVER_HARNESS_REVIEW_PASS'
assert review['protocol_sha256']==sha(OUT/'protocol.md')
for name,digest in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():
    assert sha(Path(name))==digest

def union(intervals):
    end=None;total=0
    for start,stop in sorted(intervals):
        if end is None or start>end:
            total+=stop-start
        elif stop>end:
            total+=stop-end
        end=max(end,stop) if end is not None else stop
    return total

rows=[]
for cell in plan['arm_cell_order']:
    name=cell['arm']+'-'+cell['cell']+'-b'+str(cell['block'])+'.json'
    assert sha(OUT/name)==result['receipts_sha256'][name]
    worker=json.loads((OUT/name).read_text())
    assert worker['config_identity']==plan['config_sha256'][cell['arm']]
    expected=[s for s in plan['samples'] if s['language']+'-'+s['protocol']==cell['cell'] and s['block']==cell['block']]
    assert len(worker['samples'])==len(expected)==4
    for row,sample in zip(worker['samples'],expected):
        assert all(row[k]==sample[k] for k in ('sample_id','request_id','conversation_id','language','protocol','category','warmup','block','case_id'))
        assert row['status']=='PASS' and row['observer_valid'] is True
        a,b=row['start_ns'],row['primary_dispatch_ns']
        assert type(a) is type(b) is int and 0<=a<=b
        assert row['preparation_ns']==b-a
        assert row['process_cpu_ns']==row['primary_cpu_ns']-row['start_cpu_ns']>=0
        groups=validate_request_intervals(row['wait_events'],row['request_id'])
        segments={k:[] for k in ('sql','gc','sdk_queue','sdk_execution','sdk_return')}
        counts={k:0 for k in segments}
        for group in groups:
            events=group['events'];kind=group['kind']
            spans=[(kind,events[0]['at_ns'],events[-1]['at_ns'])] if kind!='sdk' else [
                ('sdk_queue',events[0]['at_ns'],events[1]['at_ns']),
                ('sdk_execution',events[1]['at_ns'],events[2]['at_ns']),
                ('sdk_return',events[2]['at_ns'],events[3]['at_ns'])]
            for kind,start,stop in spans:
                start,stop=max(a,start),min(b,stop)
                if start<stop:
                    segments[kind].append((start,stop));counts[kind]+=1
        metrics={k+'_union_ns':union(v) for k,v in segments.items()}
        metrics.update(wall_ns=b-a,cpu_ns=row['process_cpu_ns'],
            all_captured_union_ns=union([span for spans in segments.values() for span in spans]))
        assert metrics['all_captured_union_ns']<=b-a
        rows.append(dict(arm=cell['arm'],cell=cell['cell'],sample_id=row['sample_id'],
            category=row['category'],block=row['block'],case_id=row['case_id'],warmup=row['warmup'],counts=counts,**metrics))
assert len(rows)==64 and sum(r['warmup'] for r in rows)==32
pairs=[]
for r in rows:
    if r['arm']!='c1' or r['warmup']: continue
    a=next(x for x in rows if x['arm']=='c0' and x['sample_id']==r['sample_id'])
    pairs.append(dict(sample_id=r['sample_id'],cell=r['cell'],category=r['category'],block=r['block'],case_id=r['case_id'],
        **{key:r[key]-a[key] for key in r if key.endswith('_ns')}))
assert len(pairs)==16
summary={}
for category in ('combined','empty'):
    selected=[r for r in pairs if r['category']==category]
    summary[category]={key:{'median_ms':statistics.median(r[key] for r in selected)/1e6,
        'range_ms':[min(r[key] for r in selected)/1e6,max(r[key] for r in selected)/1e6]}
        for key in selected[0] if key.endswith('_ns')}
arm_summary={}
for arm in ('c0','c1'):
    arm_summary[arm]={category:{key:statistics.median(r[key] for r in rows if r['arm']==arm and r['category']==category and not r['warmup'])/1e6
        for key in summary[category]} for category in ('combined','empty')}
order_summary={}
for first in ('c0','c1'):
    cells={(c['cell'],c['block']) for c in plan['arm_cell_order'][::2] if c['arm']==first}
    selected=[r for r in pairs if (r['cell'],r['block']) in cells]
    order_summary[first+'_first']={key:statistics.median(r[key] for r in selected)/1e6 for key in summary['combined']}
contrasts=[]
for cell in ('EN-json','EN-sse','ES-json','ES-sse'):
    for category in ('combined','empty'):
        by_block={p['block']:p for p in pairs if p['cell']==cell and p['category']==category}
        assert set(by_block)=={0,1} and by_block[0]['case_id']==by_block[1]['case_id']
        first={c['block']:c['arm'] for c in plan['arm_cell_order'][::2] if c['cell']==cell}
        assert set(first.values())=={'c0','c1'}
        by_first={first[b]:p for b,p in by_block.items()}
        source={k:(by_block[0][k]+by_block[1][k])/2 for k in by_block[0] if k.endswith('_ns')}
        order={k:(by_first['c0'][k]-by_first['c1'][k])/2 for k in source}
        contrasts.append(dict(cell=cell,category=category,case_id=by_block[0]['case_id'],source=source,order=order))
contrast_summary={}
for category in ('combined','empty'):
    selected=[p for p in contrasts if p['category']==category]
    contrast_summary[category]={kind:{k:{'median_ms':statistics.median(p[kind][k] for p in selected)/1e6,
        'range_ms':[min(p[kind][k] for p in selected)/1e6,max(p[kind][k] for p in selected)/1e6]}
        for k in selected[0][kind]} for kind in ('source','order')}
audit=OUT/'network-audit.log';assert not audit.exists() or not audit.read_bytes()
analysis=dict(status='DIAGNOSTIC_CROSSOVER_ANALYSIS_COMPLETE_NOT_A_GATE',plan_sha256=sha(OUT/'plan.json'),
    result_sha256=sha(OUT/'result.json'),analyzer_sha256=sha(Path(__file__)),
    rows=rows,paired_deltas=pairs,contrasts=contrasts,contrast_summary=contrast_summary,summary=summary,arm_medians_ms=arm_summary,order_medians_ms=order_summary,
    external_calls=0,provider_calls=0,paid_spend_usd='0',official_g6_status='CONTROLLED_G6_FAIL',
    interpretation='Descriptive only; overlapping unions are not additive, process CPU cannot be subtracted from wall, no causal GC/SQL/scheduling share or corrected p95.')
(OUT/'analysis.json').write_text(json.dumps(analysis,indent=2)+'\n')
print(json.dumps({'contrast_summary':contrast_summary,'summary':summary,'arm_medians_ms':arm_summary,'order_medians_ms':order_summary},indent=2))
