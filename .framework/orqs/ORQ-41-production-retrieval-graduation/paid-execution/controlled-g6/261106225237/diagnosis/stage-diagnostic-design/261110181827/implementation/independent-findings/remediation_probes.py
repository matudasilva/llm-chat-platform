"""Pure R1/R2 rechecks; no ASGI/provider/database operation."""
import ast,json,threading
from pathlib import Path
from types import SimpleNamespace as NS
from experiments.production_graduation.gate_validation import stage_latency_worker as w
from experiments.production_graduation.gate_validation.stage_latency_observer import validate_endpoints

def main():
 tid=threading.get_native_id();before=w.endpoint(tid);values=[]
 t=threading.Thread(target=lambda:values.append(w.endpoint(tid)));t.start();t.join(timeout=2);assert not t.is_alive();after=values[0]
 assert before['reader_native_id']==before['loop_native_id']==after['loop_native_id']==tid and after['reader_native_id']!=tid;validate_endpoints(before,after,tid)
 tree=ast.parse(Path(w.__file__).read_text());block=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)and n.name=='run_block');funcs=[n for n in block.body if isinstance(n,ast.FunctionDef)and n.name in ('read_wall','read_endpoint','sent')]
 def broken():raise RuntimeError('wall observation only')
 calls=[];current=dict(endpoint_valid=True,loop_native_id=tid,primary_ns=[],primary_counters=[],dispatches=[])
 env=dict(wall=broken,require=lambda c,m:None if c else(_ for _ in()).throw(ValueError(m)),current=current,endpoint=w.endpoint,_purpose=NS(get=lambda:'primary'),hashlib=__import__('hashlib'),original=lambda *a,**k:calls.append((a,k))or 'unchanged')
 exec(compile(ast.fix_missing_locations(ast.Module(body=funcs,type_ignores=[])),'<actualsafehookfunctions>','exec'),env)
 assert env['sent'](b'payload',adapter='bedrock')=='unchanged';assert len(calls)==1 and current['endpoint_valid']is False and current['primary_ns']==[None]
 print(json.dumps(dict(same_loop_target_actual_cross_thread=True,safe_wall_failure_delegates_once=True,service_calls=0)))
if __name__=='__main__':main()
