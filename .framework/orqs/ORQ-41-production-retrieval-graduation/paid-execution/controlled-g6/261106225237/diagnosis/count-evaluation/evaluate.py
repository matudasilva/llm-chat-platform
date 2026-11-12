"""Offline counterfactual only; never writes application source."""
import copy
import hashlib
import inspect
import json
import statistics
import textwrap
import time
from pathlib import Path

from experiments.production_graduation.gate_validation.validate_g123 import check_p2
check_p2()
OUT = Path(__file__).resolve().parent
ROOT = Path.cwd()
BASE = ROOT / '.framework/orqs/ORQ-41-production-retrieval-graduation'
dump = BASE / 'corpus-snapshot/orq37-t23-corpus.pgdump'
assert hashlib.sha256(dump.read_bytes()).hexdigest() == '0334e3af47edf9c885093a6ad061390f6f85ba62517e56b94450339950599d4f'
import workload as w
c1 = w.c1
original = c1.Evidence._add
source = textwrap.dedent(inspect.getsource(original))
candidate_source = source.replace('sum(count(v) for v in value)',
    'sum(count(v) for v in value if isinstance(v, (list, dict)))').replace(
    'sum(count(v) for v in value.values())',
    'sum(count(v) for v in value.values() if isinstance(v, (list, dict)))')
assert source != candidate_source
namespace = {}
exec(compile(candidate_source, '<temporary-counterfactual>', 'exec'), c1.__dict__, namespace)
candidate = namespace['_add']
(OUT / 'counterfactual.txt').write_text(candidate_source)

def run_case(method, case):
    c1.Evidence._add = method
    return w.workload(case, True)

checks = []
for case in w.cases:
    assert run_case(original, case) == run_case(candidate, case)
    checks.append('full_chain_delivery:' + case['sample_id'])

class SpecialList(list):
    pass

class SpecialDict(dict):
    pass

aliased = [1, 2]
cycle = []; cycle.append(cycle)
data_cases = [None, 7, 'á漢字', {}, [], [None, 2, 'x'],
    {'items': [{'a': 1, 'b': 'x'}, {'items': [1, 2]}]},
    {'alias': [aliased, aliased]}, SpecialList([1, {'a': [2]}]),
    SpecialDict(a=[1, SpecialDict(b=[2, 3])]), cycle,
    {'invalid_json': {1, 2}}, {'unicode': ['á漢字']}, {'large': list(range(10005))}]

def observe_data(method, data, items, size):
    c1.Evidence._add = method
    old = c1.MAX_ITEMS, c1.MAX_BYTES
    c1.MAX_ITEMS, c1.MAX_BYTES = items, size
    try:
        with c1.request_evidence('i', 'c') as state:
            c1.observe('test', lambda _: data)
        return state.snapshot(), state.size, state.items
    finally:
        c1.MAX_ITEMS, c1.MAX_BYTES = old

for i, data in enumerate(data_cases):
    for limits in [(10000, 8*1024*1024), (3, 8*1024*1024), (10000, 300)]:
        assert observe_data(original, data, *limits) == observe_data(candidate, data, *limits), (i, limits, observe_data(original, data, *limits), observe_data(candidate, data, *limits))
        checks.append(f'counter_caps_failure:{i}:{limits}')

# Check exact aggregate byte/item cap edges against the uncapped trace.
data = {'items': [1, 2, {'nested': [3]}]}
trace, byte_count, item_count = observe_data(original, data, 10000, 8*1024*1024)
for items,size in [(item_count+d,8*1024*1024) for d in (-1,0,1)] + [(10000,byte_count+d) for d in (-1,0,1)]:
    assert observe_data(original,data,items,size) == observe_data(candidate,data,items,size)
    checks.append(f'exact_cap_edge:{items}:{size}')

# Warmups retained separately; both arms run identical full observer work.
warmups=[]
for name, method in [('current',original),('candidate',candidate)]:
    start=time.process_time_ns()
    for _ in range(3):
        for case in w.cases: run_case(method,case)
    warmups.append({'arm':name,'workloads':3*len(w.cases),'cpu_ns':time.process_time_ns()-start})

rows=[]
for batch in range(9):
    order=['current','candidate'] if batch%2==0 else ['candidate','current']
    for category in ('document','history','combined','empty'):
        cases=[case for case in w.cases if case['category']==category]
        for name in order:
            method=original if name=='current' else candidate
            c1.Evidence._add=method
            cpu=time.process_time_ns();wall=time.perf_counter_ns()
            for _ in range(10):
                for case in cases: w.workload(case,True)
            rows.append({'batch':batch,'category':category,'arm':name,
                'workloads':10*len(cases),'cpu_ns':time.process_time_ns()-cpu,
                'wall_ns':time.perf_counter_ns()-wall})
c1.Evidence._add=original
summary={}
for category in ('document','history','combined','empty'):
    diffs=[]
    for batch in range(9):
        group={r['arm']:r for r in rows if r['category']==category and r['batch']==batch}
        a,b=group['current'],group['candidate'];assert a['workloads']==b['workloads']
        diffs.append({'cpu_ns_per_workload':(b['cpu_ns']-a['cpu_ns'])/a['workloads'],
            'wall_ns_per_workload':(b['wall_ns']-a['wall_ns'])/a['workloads']})
    summary[category]={key:{'median_ms':statistics.median(d[key] for d in diffs)/1e6,
        'range_ms':[min(d[key] for d in diffs)/1e6,max(d[key] for d in diffs)/1e6],
        'candidate_lower_batches':sum(d[key]<0 for d in diffs)} for key in diffs[0]}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
result={'status':'OFFLINE_COUNTER_EVALUATION_COMPLETE_NOT_A_GATE',
    'checks_passed':len(checks),'checks':checks,'warmups':warmups,'batches':rows,'summary':summary,
    'source_sha256':sha(ROOT/'app/core/observability/context_evidence.py'),
    'counterfactual_sha256':sha(OUT/'counterfactual.txt'),'evaluator_sha256':sha(Path(__file__)),
    'workload_sha256':sha(OUT/'workload.py'),'sql_sha256':sha(Path('/tmp/orq41-p3-chunks.sql')),
    'fixture_sha256':sha(w.PROFILE/'fixtures.json'),'snapshot_sha256':sha(dump),
    'runtime_modified':False,'api_requests':0,'database_queries':0,'provider_calls':0,'external_calls':0,'spend_usd':'0',
    'limitations':['reconstructed lexical P3 selection, not original retrieval ranking',
        'host interpreter, not pinned container resources',
        'aggregate full workload includes rendering, serialization, Capture, snapshot and chain validation',
        'no ASGI/DB waits or G6 p95 attribution; no inferred gate PASS']}
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'status':result['status'],'checks':len(checks),'summary':summary},indent=2))
