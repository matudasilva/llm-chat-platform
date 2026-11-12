"""Counterfactual receipt-copy evaluation; does not edit/import-replace runtime."""
import copy,difflib,hashlib,json,statistics,time,types
from pathlib import Path
from types import SimpleNamespace as NS
from app.core.observability import context_evidence as original
ROOT=Path.cwd(); ORQ=ROOT/'.framework/orqs/ORQ-41-production-retrieval-graduation'
OUT=ORQ/'paid-execution/controlled-g6/261106130053-rev2/diagnosis/receipt-copy-proposal/revision2'
OUT.mkdir(exist_ok=False)
source=ROOT/'app/core/observability/context_evidence.py'; before=source.read_text()
helper='''def _copy_window_receipts(receipts):
    # Immutable scalar fields need independent containers, not recursive copying.
    if type(receipts) is list and len({id(row) for row in receipts}) == len(receipts) and all(
        type(row) is dict and all(type(key) is str and type(value) in (str, int, bool, type(None))
                                 for key, value in row.items())
        for row in receipts
    ):
        return [row.copy() for row in receipts]
    return copy.deepcopy(receipts)


'''
after=before.replace('def window_materialized(partition):',helper+'def window_materialized(partition):')
assert before.count('copy.deepcopy(state.window)')==2 and before.count('copy.deepcopy(kept)')==1
after=after.replace('copy.deepcopy(state.window)','_copy_window_receipts(state.window)').replace('copy.deepcopy(kept)','_copy_window_receipts(kept)')
patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/app/core/observability/context_evidence.py',tofile='b/app/core/observability/context_evidence.py'))
(OUT/'candidate.patch').write_text(patch)
candidate=types.ModuleType('counterfactual_context_evidence');exec(compile(after,'<counterfactual>','exec'),candidate.__dict__)
fixtures=ORQ/'paid-execution/controlled-g6/261106130053-rev2/diagnosis/aggregate-runs/261106190648/fixtures.json'
rows=json.loads(fixtures.read_text()); histories=[r['messages'] for r in rows if r['messages']];assert len(histories)==8
checks=[]
# Exact trace/hash-chain equivalence, including truncation, cap failure, abort and bad builders.
def trace(module,messages,variant):
    values=[NS(sequence=i+1,role=v['role'],content=v['content']) for i,v in enumerate(messages)]
    old_bytes,old_items=module.MAX_BYTES,module.MAX_ITEMS
    if variant=='bytes':module.MAX_BYTES=500
    if variant=='items':module.MAX_ITEMS=3
    state=None
    try:
        with module.request_evidence('instance','correlation') as state:
            module.window_materialized(NS(window=values))
            def pack(msgs):
                kept=msgs[-2:] if variant=='truncated' else msgs
                return NS(messages=[NS(role=v.role,content=v.content[:2] if variant=='truncated' else v.content) for v in kept])
            packed=module.packed_window(pack)(values)
            memory=NS(messages=packed.messages,retrieved_events=[]);rag=NS(sources=[])
            def cap(**kwargs):return memory,rag,None
            module.final_cap(cap)(memory_context=memory,rag_context=rag,current_message='query',max_chars=12000)
            if variant=='broken':module.observe('bad',lambda _:1/0)
            if variant=='abort':raise RuntimeError('controlled abort')
    except RuntimeError:pass
    finally:module.MAX_BYTES,module.MAX_ITEMS=old_bytes,old_items
    return state.snapshot()
for history in histories:
 for variant in ('normal','truncated','bytes','items','broken','abort'):
    assert trace(original,history,variant)==trace(candidate,history,variant)
    checks.append(variant)
# Independent container alias checks, nested fallback and snapshot mutation isolation.
for value in ([{'key':'x','sha256':'abc','chars':2}], [{'nested':{'items':[1]}}], [{'role':['unexpected']}], [], [{'x':3.14}]):
    expected=copy.deepcopy(value); actual=candidate._copy_window_receipts(value)
    assert actual==expected and actual is not value
    if value:
        assert actual[0] is not value[0]
        if 'nested' in value[0]: value[0]['nested']['items'].append(2)
        else:value[0]['mutated']=True
        assert actual==expected
    checks.append('alias/fallback')
class SpecialDict(dict):pass
value=[SpecialDict(x='y')]
assert type(candidate._copy_window_receipts(value)[0]) is SpecialDict
checks.append('subclass fallback')
row={'key':'same'}; aliased=[row,row]; copied=candidate._copy_window_receipts(aliased)
assert copied==copy.deepcopy(aliased) and copied[0] is copied[1] and copied[0] is not row
checks.append('repeated row alias preservation')
for module in (original,candidate):
 with module.request_evidence('i','c') as state:
    module.window_materialized(NS(window=[NS(sequence=1,role='user',content='retained')]))
    state.window[0]['sha256']='changed'
    assert state.records[-1]['data']['items'][0]['sha256']!='changed'
 snap=state.snapshot();snap['records'][0]['data']['instance_id']='changed'
 assert state.snapshot()['records'][0]['data']['instance_id']=='i'
 checks.append('record/snapshot isolation')
# Batch clocks only, copy result validation after timing. No application/provider calls.
receipts=[[original.text_receipt(i,v['content'],role=v['role']) for i,v in enumerate(h)] for h in histories]
iterations=100; measurements={'deepcopy':[],'candidate':[]}
for repeat in range(7):
 for mode in (('deepcopy','candidate') if repeat%2==0 else ('candidate','deepcopy')):
    fn=copy.deepcopy if mode=='deepcopy' else candidate._copy_window_receipts
    cpu=time.process_time_ns();wall=time.monotonic_ns();last=None
    for _ in range(iterations):
     for data in receipts:
      for stage in range(3):last=fn(data)
    elapsed=time.monotonic_ns()-wall;cpu=time.process_time_ns()-cpu
    assert last==receipts[-1] and last is not receipts[-1]
    measurements[mode].append({'cpu_ns':cpu,'wall_ns':elapsed,'copy_operations':iterations*len(receipts)*3})
assert source.read_text()==before
result={'status':'COUNTERFACTUAL_RECEIPT_COPY_EVALUATED_NOT_IMPLEMENTED','source_sha256':hashlib.sha256(before.encode()).hexdigest(),'fixture_sha256':hashlib.sha256(fixtures.read_bytes()).hexdigest(),'checks':len(checks),'trace_pairs':len(histories)*6,'measurements':measurements,'median_cpu_ns':{m:statistics.median(r['cpu_ns'] for r in a) for m,a in measurements.items()},'limitations':['Only copy microbenchmark; not endpoint or G6 p95','Inputs from frozen history fixtures, not retained full historical evidence states','No claim that savings close +5% gate; request-level aggregate CPU contains other work'],'app_modified':False,'api_requests':0,'database_queries':0,'external_calls':0,'paid_spend_usd':'0'}
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n');(OUT/'evaluate.py').write_text(Path(__file__).read_text())
print(json.dumps({'checks':len(checks),'medians':result['median_cpu_ns'],'output':str(OUT)},indent=2))
