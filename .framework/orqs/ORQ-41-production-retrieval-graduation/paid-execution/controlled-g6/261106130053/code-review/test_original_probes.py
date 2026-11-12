import ast,asyncio,time
from pathlib import Path
from types import SimpleNamespace
import httpx
from app.core.observability import context_evidence as c1

WORKER=Path('experiments/production_graduation/gate_validation/controlled_latency_worker.py')
def rejection(states):
    tree=ast.parse(WORKER.read_text())
    condition=next(node.test for node in ast.walk(tree) if isinstance(node,ast.If) and any(isinstance(n,ast.Attribute) and n.attr=='evidence_states' for n in ast.walk(node.test)))
    return eval(compile(ast.Expression(condition),str(WORKER),'eval'),{'ARM':'c1','lifecycle':SimpleNamespace(evidence_states=states)})

def test_counterexample_actual_best_effort_observer_loss_does_not_reject(monkeypatch):
    def broken(*args,**kwargs):raise RuntimeError('controlled construction failure')
    monkeypatch.setattr(c1,'Evidence',broken)
    retained=[]
    with c1.request_evidence('instance','correlation') as state:
        assert state is None
    if state is not None:retained.append(state)
    assert retained==[]
    assert rejection(retained) is False

def test_counterexample_duplicate_valid_contexts_do_not_reject():
    assert rejection([SimpleNamespace(valid=True,closed=True),SimpleNamespace(valid=True,closed=True)]) is False

def test_counterexample_asgi_transport_timeout_argument_is_not_deadline():
    async def run():
        async def app(scope,receive,send):
            await asyncio.sleep(.03)
            await send({'type':'http.response.start','status':204,'headers':[]})
            await send({'type':'http.response.body','body':b''})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://memory') as client:
            started=time.monotonic()
            async with asyncio.timeout(1):response=await client.post('/review-probe',timeout=.001)
            assert response.status_code==204 and time.monotonic()-started>=.025
    asyncio.run(run())
