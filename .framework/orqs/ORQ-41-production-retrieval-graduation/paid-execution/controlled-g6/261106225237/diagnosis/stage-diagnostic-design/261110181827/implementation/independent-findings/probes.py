"""Pure reviewed-source counterexamples: no service or request operation."""
import ast,json,threading
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from experiments.production_graduation.gate_validation import stage_latency_worker as w

def main():
 loop=threading.get_ident()
 def usage(_):
  return NS(ru_nvcsw=100 if threading.get_ident()==loop else 2,ru_nivcsw=30 if threading.get_ident()==loop else 1)
 out={}
 with patch.object(w.resource,'getrusage',usage):
  out['ingress']=w.endpoint()
  def run():out['primary_from_sdk_thread']=w.endpoint()
  t=threading.Thread(target=run);t.start();t.join(timeout=2);assert not t.is_alive()
 assert out['primary_from_sdk_thread']['voluntary']<out['ingress']['voluntary']
 tree=ast.parse(Path(w.__file__).read_text());block=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)and n.name=='run_block');sent=next(n for n in block.body if isinstance(n,ast.FunctionDef)and n.name=='sent')
 calls=[]
 def broken():raise RuntimeError('endpoint wall clock failed')
 env=dict(time=NS(monotonic_ns=broken),read_endpoint=lambda:{},_purpose=NS(get=lambda:'primary'),current=dict(primary_ns=[],primary_counters=[],dispatches=[]),hashlib=__import__('hashlib'),original=lambda *a,**k:calls.append('transport_original'))
 exec(compile(ast.fix_missing_locations(ast.Module(body=[sent],type_ignores=[])),'<actual sent callback>','exec'),env)
 try:env['sent'](b'payload')
 except RuntimeError:pass
 else:raise AssertionError('Expected unguarded observation error to escape')
 assert calls==[]
 print(json.dumps(dict(thread_counter_mismatch_reproduced=True,unguarded_wall_error_prevents_original=True,service_calls=0)))
if __name__=='__main__':main()
