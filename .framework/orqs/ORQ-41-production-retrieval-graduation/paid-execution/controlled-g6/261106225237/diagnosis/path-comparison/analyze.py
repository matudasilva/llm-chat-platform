"""Source normalization and aggregate local scope calibration; not a gate."""
import ast
import hashlib
import json
import statistics
import time
from contextlib import nullcontext
from pathlib import Path

from experiments.production_graduation.gate_validation.validate_g123 import check_p2
check_p2()
from experiments.production_graduation.gate_validation.transports import ScopedProvider
from app.core.observability import context_evidence as c1

OUT=Path(__file__).resolve().parent
data={a:json.loads((OUT/(a+'-source.json')).read_text()) for a in ('c0','c1')}

def observer(node):
    return isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='c1'

class RemoveObserver(ast.NodeTransformer):
    def visit_ImportFrom(self,node):
        if node.module=='app.core.observability' and any(n.asname=='c1' for n in node.names): return None
        return node
    def visit_Expr(self,node):
        return None if observer(node.value) else self.generic_visit(node)
    def visit_FunctionDef(self,node):
        node.decorator_list=[d for d in node.decorator_list if not observer(d) and not (isinstance(d,ast.Attribute) and isinstance(d.value,ast.Name) and d.value.id=='c1')]
        return self.generic_visit(node)
    visit_AsyncFunctionDef=visit_FunctionDef
    def visit_With(self,node):
        node.items=[i for i in node.items if not observer(i.context_expr)]
        return self.generic_visit(node)

comparison=json.loads((OUT/'comparison.json').read_text())
normalized={}
for name in comparison['changed_files']:
    if name=='core/observability/context_evidence.py': continue
    a=ast.parse(data['c0']['files'][name]);b=RemoveObserver().visit(ast.parse(data['c1']['files'][name]))
    normalized[name]=ast.dump(a,include_attributes=False)==ast.dump(b,include_attributes=False)
assert all(normalized.values())

# The two explicit scopes mirror rewrite and primary, but never invoke providers.
scopes={False:ScopedProvider(None,candidate=False),True:ScopedProvider(None,candidate=True)}
def workload(mode):
    active=mode in ('request_only','candidate_active')
    candidate=mode in ('candidate_passive','candidate_active')
    with c1.request_evidence('instance','correlation') if active else nullcontext():
        if mode!='request_only':
            for purpose in ('rewrite','primary'):
                token=c1._purpose.set(purpose)
                try:
                    with scopes[candidate].scope(): pass
                finally: c1._purpose.reset(token)

modes=['baseline','candidate_passive','request_only','candidate_active']
for mode in modes:
    for _ in range(100): workload(mode)
rows=[]
for batch in range(9):
    order=modes[batch%len(modes):]+modes[:batch%len(modes)]
    for mode in order:
        start=time.process_time_ns();wall=time.perf_counter_ns()
        for _ in range(1000): workload(mode)
        rows.append(dict(batch=batch,mode=mode,workloads=1000,cpu_ns=time.process_time_ns()-start,wall_ns=time.perf_counter_ns()-wall))

summary={}
for mode in modes:
    cpu=[r['cpu_ns']/r['workloads']/1e6 for r in rows if r['mode']==mode]
    summary[mode]={'median_cpu_ms':statistics.median(cpu),'range_cpu_ms':[min(cpu),max(cpu)]}
result={'status':'PATH_COMPARISON_AND_SCOPE_CALIBRATION_COMPLETE_NOT_A_GATE','normalized_ast_equal_after_observer_removal':normalized,
    'python_equal':comparison['python_equal'],'packages_equal':comparison['packages_equal'],
    'summary':summary,'batches':rows,'evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'scope_source_sha256':hashlib.sha256(Path('experiments/production_graduation/gate_validation/transports.py').read_bytes()).hexdigest(),
    'limitations':['source normalization confirms syntactic differences only; no blanket semantic proof',
        'host interpreter, no ASGI task/thread scheduling, SQL or providers',
        'scope calibration excludes payload receipts/Capture/SDK and includes full request end',
        'no subtraction from G6 p95 or prediction of a PASS'],
    'api_requests':0,'database_queries':0,'provider_calls':0,'external_calls':0,'spend_usd':'0'}
(OUT/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'ast':normalized,'summary':summary},indent=2))
