"""Independent no-I/O replay of diagnostic timing trees and descriptive output."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from uuid import UUID


def main():
    from experiments.production_graduation.gate_validation.validate_g123 import check_p2
    check_p2()
    run = Path(__file__).resolve().parent.parent
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    plan = json.loads((run/'plan.json').read_text())
    result = json.loads((run/'result.json').read_text())
    analysis = json.loads((run/'analysis.json').read_text())
    assert result['plan_sha256'] == digest(run/'plan.json')
    assert result['status'] == 'DIAGNOSTIC_PROFILE_COMPLETE' and result['not_a_gate']
    assert (result['request_count'], result['measured_requests'], result['warmups']) == (40,32,8)
    assert result['provider_calls'] == result['external_calls'] == result['paid_spend_usd'] == 0
    for name, value in result['receipts_sha256'].items(): assert digest(run/name) == value
    for name, value in {**plan['harness_sha256'], **plan['support_files_sha256'], **plan['test_sha256']}.items():
        assert digest(Path(name)) == value
    observations = {(r['arm'],r['request_id']):r for r in analysis['requests']}
    calls = Counter(); cpu_by_label = Counter(); phases = Counter(); summaries = defaultdict(list)
    paired = {}; instances = set(); total = measured = warmups = 0
    for block in plan['arm_cell_order']:
        arm,key = block['arm'],block['arm']+'-'+block['cell']
        rows = json.loads((run/(key+'.json')).read_text())['samples']
        profile = json.loads((run/(key+'-profile.json')).read_text())
        assert profile['valid'] and profile['not_a_gate']
        expected = [s for s in plan['samples'] if s['language']+'-'+s['protocol'] == block['cell']]
        assert len(rows) == len(expected) == 5
        for row,sample in zip(rows,expected):
            assert all(row[k] == sample[k] for k in ('sample_id','language','protocol','warmup','category','request_id','conversation_id'))
            assert row['status'] == 'PASS' and row['error'] is None
            assert row['preparation_ns'] == row['primary_dispatch_ns']-row['start_ns'] >= 0
            if arm == 'c0': paired[row['sample_id']] = row['dispatches']
            else:
                instance = row['accounting_instance_id'];assert str(UUID(instance)) == instance
                assert instance not in instances;instances.add(instance)
            total += 1;measured += not row['warmup'];warmups += row['warmup']
            events = [e for e in profile['events'] if e['request_id'] == row['request_id']]
            assert events
            ancestors = {}; children = defaultdict(list)
            for thread in {e['thread_id'] for e in events}:
                stack = []
                for e in sorted((e for e in events if e['kind']=='sync' and e['thread_id']==thread),
                                key=lambda e:(e['start_ns'],-e['end_ns'])):
                    while stack and e['start_ns'] >= stack[-1]['end_ns']: stack.pop()
                    assert not stack or e['end_ns'] <= stack[-1]['end_ns']
                    ancestors[id(e)] = [p['label'] for p in stack]
                    assert e['parent_label'] == (stack[-1]['label'] if stack else None)
                    if stack: children[id(stack[-1])].append(e)
                    stack.append(e)
            cpu = Counter();wall = Counter();sql = []
            for e in events:
                phase = 'before_primary' if e['end_ns'] <= row['primary_dispatch_ns'] else 'after_primary' if e['start_ns'] >= row['primary_dispatch_ns'] else 'crosses_primary'
                assert phase == e['phase'];phases[phase] += 1
                if e['kind'] == 'sync':
                    assert e['wall_ns'] == e['end_ns']-e['start_ns']
                    assert e['self_wall_ns'] == e['wall_ns']-sum(c['wall_ns'] for c in children[id(e)])
                    assert e['self_cpu_ns'] == e['cpu_ns']-sum(c['cpu_ns'] for c in children[id(e)])
                    assert min(e['self_wall_ns'],e['self_cpu_ns']) >= 0
                    if phase != 'before_primary': continue
                    labels = ancestors[id(e)];label = e['label']
                    if label.startswith('runtime.'):
                        category = 'runtime_from_capture' if 'harness.Capture.sent' in labels else (
                            'runtime_from_scope' if label.startswith('runtime.invocation.') or any(
                                p.startswith(('harness.ScopedProvider.scope.','runtime.invocation.')) for p in labels) else 'runtime_app')
                    elif label.startswith('common.'): category = 'common'
                    elif label in ('harness.Capture.sent','harness.Tape.sent'): category = 'capture_exclusive'
                    elif label.startswith('harness.sdk.'): category = 'sdk_hook'
                    else: category = 'scope_exclusive'
                    cpu[category] += e['self_cpu_ns'];wall[category] += e['self_wall_ns']
                    if not row['warmup']:
                        labelkey = arm,e['purpose'],label;calls[labelkey] += 1;cpu_by_label[labelkey] += e['self_cpu_ns']
                else:
                    assert e['kind']=='sql_wait' and 'cpu_ns' not in e
                    start,end=max(e['start_ns'],row['start_ns']),min(e['end_ns'],row['primary_dispatch_ns'])
                    if end > start: sql.append((start,end))
            merged=[]
            for start,end in sorted(sql):
                if merged and start <= merged[-1][1]: merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
                else: merged.append((start,end))
            observed=observations[arm,row['request_id']]
            assert dict(cpu)==observed['self_cpu_ns']
            assert dict(wall)==observed['self_wall_ns_by_component_not_additive_across_threads']
            assert sum(end-start for start,end in merged)==observed['sql_union_wall_ns']
            if not row['warmup']: summaries[arm,row['category']].append(observed)
        if arm=='c1':
            for row in rows:
                baseline=next(x for x in json.loads((run/('c0-'+block['cell']+'.json')).read_text())['samples'] if x['sample_id']==row['sample_id'])
                assert baseline['dispatches']==row['dispatches']
    assert (total,measured,warmups,len(instances))==(40,32,8,20)
    for entry in analysis['summary']:
        group=summaries[entry['arm'],entry['category']];assert len(group)==entry['n']==4
        for label,value in entry['median_self_cpu_ms'].items():
            assert median(r['self_cpu_ns'].get(label,0) for r in group)/1e6==value
    assert len(analysis['before_primary_labels'])==len(calls)
    for entry in analysis['before_primary_labels']:
        key=entry['arm'],entry['purpose'],entry['label'];assert entry['count']==calls[key]
        assert entry['self_cpu_ns']==cpu_by_label[key]
    audit=run/'network-audit.log';assert not audit.exists() or not audit.read_text()
    out={'status':'DIAGNOSTIC_PROFILE_EXECUTION_INDEPENDENT_REPLAY_PASS','not_a_gate':True,
         'plan_sha256':digest(run/'plan.json'),'result_sha256':digest(run/'result.json'),
         'analysis_sha256':digest(run/'analysis.json'),'verifier_sha256':digest(Path(__file__)),
         'requests':total,'measured':measured,'warmups':warmups,'accounting_instances':len(instances),
         'profile_events':sum(phases.values()),'phases':dict(phases),'exclusive_tree_arithmetic_verified':True,
         'cpu_classification_and_sql_union_verified':True,'native_payload_parity':True,
         'observed_guard_attempts':0,'reviewer_api_calls':0,'external_calls':0,'spend_usd':'0',
         'official_g6_status':'CONTROLLED_G6_FAIL','causal_percentage_established':False}
    path=Path(__file__).with_name('receipt.json');assert not path.exists()
    path.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))


if __name__=='__main__':main()
