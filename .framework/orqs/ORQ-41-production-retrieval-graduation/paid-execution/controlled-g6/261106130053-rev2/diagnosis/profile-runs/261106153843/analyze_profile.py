"""Descriptive, non-overlapping synchronous self CPU; never recalculates G6."""
import hashlib,json,statistics
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def union(intervals):
    total=0;last=None
    for start,end in sorted(intervals):
        if last is None or start>last: total+=end-start;last=end
        elif end>last: total+=end-last;last=end
    return total

def component(event,events):
    label=event['label']
    if label.startswith('runtime.'):
        enclosing=[e['label'] for e in events if e['kind']=='sync' and e['thread_id']==event['thread_id'] and
                   e['start_ns']<=event['start_ns'] and e['end_ns']>=event['end_ns'] and e is not event]
        if 'harness.Capture.sent' in enclosing: return 'runtime_from_capture'
        if label.startswith('runtime.invocation.') or any(e.startswith(('harness.ScopedProvider.scope.','runtime.invocation.')) for e in enclosing): return 'runtime_from_scope'
        return 'runtime_app'
    if label.startswith('common.'): return 'common'
    if label in ('harness.Capture.sent','harness.Tape.sent'): return 'capture_exclusive'
    if label.startswith('harness.sdk.'): return 'sdk_hook'
    return 'scope_exclusive'

def main():
    plan=json.loads((ROOT/'plan.json').read_text());result=json.loads((ROOT/'result.json').read_text())
    assert result['not_a_gate'] and result['request_count']==40
    rows=[];calls=Counter();labelcpu=Counter();threadrows=[]
    for block in plan['arm_cell_order']:
        key=block['arm']+'-'+block['cell'];worker=json.loads((ROOT/(key+'.json')).read_text())
        profile=json.loads((ROOT/(key+'-profile.json')).read_text());assert profile['valid']
        assert hashlib.sha256((ROOT/(key+'-profile.json')).read_bytes()).hexdigest()==result['receipts_sha256'][key+'-profile.json']
        for sample in worker['samples']:
            events=[e for e in profile['events'] if e['request_id']==sample['request_id']]
            before=[e for e in events if e['kind']=='sync' and e['phase']=='before_primary']
            cpu=Counter();wall=Counter()
            for e in before:
                assert e['start_ns']>=sample['start_ns'] and e['end_ns']<=sample['primary_dispatch_ns']
                c=component(e,events);cpu[c]+=e['self_cpu_ns'];wall[c]+=e['self_wall_ns']
                if not sample['warmup']:
                    calls[(block['arm'],e['purpose'],e['label'])]+=1
                    labelcpu[(block['arm'],e['purpose'],e['label'])]+=e['self_cpu_ns']
            sql=[(max(e['start_ns'],sample['start_ns']),min(e['end_ns'],sample['primary_dispatch_ns'])) for e in events if e['kind']=='sql_wait' and e['start_ns']<sample['primary_dispatch_ns'] and e['end_ns']>sample['start_ns']]
            rows.append(dict(arm=block['arm'],cell=block['cell'],category=sample['category'],warmup=sample['warmup'],request_id=sample['request_id'],
                preparation_ns=sample['preparation_ns'],self_cpu_ns=dict(cpu),self_wall_ns_by_component_not_additive_across_threads=dict(wall),sql_union_wall_ns=union(sql)))
            for thread in sorted({e['thread_id'] for e in before}):
                group=[e for e in before if e['thread_id']==thread]
                threadrows.append(dict(arm=block['arm'],request_id=sample['request_id'],thread_id=thread,call_count=len(group),self_cpu_ns=sum(e['self_cpu_ns'] for e in group),self_wall_ns=sum(e['self_wall_ns'] for e in group)))
    summary=[]
    for arm in ('c0','c1'):
        for category in ('document','history','combined','empty'):
            group=[r for r in rows if r['arm']==arm and r['category']==category and not r['warmup']];assert len(group)==4
            components=sorted({k for r in group for k in r['self_cpu_ns']})
            summary.append(dict(arm=arm,category=category,n=4,median_preparation_ms=statistics.median(r['preparation_ns'] for r in group)/1e6,
                median_sql_union_ms=statistics.median(r['sql_union_wall_ns'] for r in group)/1e6,
                median_self_cpu_ms={k:statistics.median(r['self_cpu_ns'].get(k,0) for r in group)/1e6 for k in components}))
    output=dict(not_a_gate=True,summary=summary,requests=rows,threads=threadrows,
        before_primary_labels=[dict(arm=k[0],purpose=k[1],label=k[2],count=v,self_cpu_ns=labelcpu[k]) for k,v in sorted(calls.items())],
        limitations=['Observed instrumented workload only; no causal percent or uninstrumented correction',
        'Self excludes wrapped synchronous children on the same thread; wrapper overhead can remain in parents',
        'Async SQL waits are separate union intervals; never sum with CPU or inclusive spans',
        'Four measured identities per category across cells, not an inferential population',
        'Runtime called by Capture/scopes is reported separately from domain/middleware runtime',
        'Official CONTROLLED_G6_FAIL and paid admission block remain unchanged'])
    (ROOT/'analysis.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
