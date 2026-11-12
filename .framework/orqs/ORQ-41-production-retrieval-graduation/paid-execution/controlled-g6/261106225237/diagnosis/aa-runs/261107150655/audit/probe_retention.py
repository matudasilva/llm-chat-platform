"""No API/SQL/provider calls: demonstrate retained completed-task context."""
import asyncio,gc,hashlib,json,weakref
from pathlib import Path
from app.core.observability import context_evidence as c1
from experiments.production_graduation.gate_validation.local_api import Lifecycle,_request
from experiments.production_graduation.gate_validation.validate_g123 import check_p2
check_p2()
async def main():
 lifecycle=Lifecycle();refs=[];rows=[]
 async def child():
  assert c1._current.get() is not None
 async def one(index):
  token=_request.set({})
  try:
   with c1.request_evidence('instance-'+str(index),'request-'+str(index)) as state:
    c1.observe('probe',lambda _:dict(items=[dict(key=str(i),sha256='a'*64) for i in range(48)]))
    with lifecycle.track_tasks():task=asyncio.create_task(child())
    await task
   lifecycle.evidence_states.append(state)
   await lifecycle.quiesce(asyncio.get_running_loop().time()+1)
   refs.append(weakref.ref(state))
   assert task.done() and task.get_context().get(c1._current) is state
   lifecycle.evidence_states.clear()
  finally:_request.reset(token)
 for index in range(8):
  await one(index);await asyncio.sleep(0);gc.collect()
  rows.append(dict(logical_iterations=index+1,completed_tasks_retained=len(lifecycle.tasks),
   evidence_states_list=len(lifecycle.evidence_states),live_evidence_objects=sum(r() is not None for r in refs)))
 assert rows[-1]['live_evidence_objects']==rows[-1]['completed_tasks_retained']==8
 lifecycle.tasks.clear();await asyncio.sleep(0);gc.collect()
 released=sum(r() is not None for r in refs)
 assert released==0
 result=dict(status='COMPLETED_TASK_CONTEXT_RETENTION_REPRODUCED',iterations=rows,
  live_evidence_after_releasing_completed_tasks=released,api_requests=0,database_queries=0,
  provider_calls=0,external_calls=0,source_sha256=hashlib.sha256(Path('/app/experiments/production_graduation/gate_validation/local_api.py').read_bytes()).hexdigest(),
  limitation='Demonstrates harness retention after successful quiescence; not a causal latency attribution or a G6 rerun')
 Path('/audit/retention.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
asyncio.run(main())
