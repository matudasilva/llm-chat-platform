"""One pinned source arm, real local PostgreSQL and memory-only native transports."""
import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
from .controlled_latency import SAMPLES,WARMUPS
from .local_api import install
from .transports import Reply,Tape,native_provider,_purpose

OUT=Path(os.environ['G6_RUN_DIR']);ARM=os.environ['G6_ARM'];CELL=os.environ['G6_CELL']

async def main():
    from .validate_g123 import check_p2,config_identity
    check_p2()
    from app.main import app
    from app.core.settings import settings
    if settings.ebm25_enabled or not settings.chat_rag_augmentation_enabled or not settings.conversation_history_enabled:
        raise ValueError('Controlled core vector changed')
    plan=json.loads((OUT/'plan.json').read_text())
    if config_identity(settings)!=plan['config_sha256'][ARM]: raise ValueError('Controlled settings drift')
    samples=[s for s in plan['samples'] if s['language']+'-'+s['protocol']==CELL]
    if len(samples)!=SAMPLES+WARMUPS: raise ValueError('Incomplete worker cell')
    current={};capture=Tape()
    if ARM=='c1':
        from .capture import Capture
        capture=Capture()
    original=capture.sent
    def sent(body,**kwargs):
        at=time.monotonic_ns()
        raw=body.encode() if isinstance(body,str) else bytes(body)
        purpose=_purpose.get()
        if purpose=='primary': current['primary_ns'].append(at)
        current['dispatches'].append({'purpose':purpose,'sha256':hashlib.sha256(raw).hexdigest()})
        return original(body,**kwargs)
    capture.sent=sent
    replies={'rewrite':Reply(''), 'evaluator':Reply('[]'), 'primary':Reply('Controlled local response.')}
    provider,close=native_provider('bedrock',capture,replies)
    provider._cfg=replace(provider._cfg,model=settings.bedrock_model,timeout_s=settings.provider_timeout_s,max_attempts=settings.bedrock_max_attempts)
    asgi,lifecycle,scoped=install(app,provider=provider,candidate=ARM=='c1',cache_namespace='orq41:g123:'+plan['run_id']+':'+ARM+':')
    async def ingress(scope,receive,send):
        if scope.get('path')=='/chat': current['start_ns']=time.monotonic_ns()
        await asgi(scope,receive,send)
    rows=[]
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ingress),base_url='http://local') as client:
                for sample in samples:
                    current.clear();current.update(primary_ns=[],dispatches=[])
                    replies['rewrite']=Reply(sample['message'])
                    status='FAIL';error=None
                    try:
                        response=await client.post('/chat',json={'message':sample['message'],'conversation_id':sample['conversation_id'],'stream':sample['protocol']=='sse'},headers={'X-Request-ID':sample['request_id'],'X-Tenant-ID':sample['tenant_id']},timeout=30)
                        if response.status_code!=200: raise ValueError('Controlled HTTP failure')
                        if sample['protocol']=='json':
                            terminal=response.json()
                            if terminal.get('status')!='success': raise ValueError('Controlled JSON failure')
                        else:
                            from .validate_g123 import parse_sse
                            parsed=parse_sse(response.content)
                            if parsed[-1][0]!='done' or parsed[-1][1].get('status')!='success': raise ValueError('Controlled SSE failure')
                            terminal=parsed[-1][1]
                        if terminal.get('request_id')!=sample['request_id'] or terminal.get('conversation_id')!=sample['conversation_id']:
                            raise ValueError('Controlled response identity mismatch')
                        await lifecycle.quiesce(asyncio.get_running_loop().time()+10)
                        if len(current['primary_ns'])!=1 or [x['purpose'] for x in current['dispatches']]!=['rewrite','primary']:
                            raise ValueError('Ambiguous controlled dispatches')
                        if ARM=='c1' and any(not state.valid for state in lifecycle.evidence_states):
                            raise ValueError('Invalid candidate evidence')
                        status='PASS'
                    except Exception as exc:
                        error=type(exc).__name__+': '+str(exc)[:100]
                    rows.append({key:sample[key] for key in ('sample_id','language','protocol','warmup','category')} | {
                        'request_id':sample['request_id'],'conversation_id':sample['conversation_id'],
                        'status':status,'error':error,'start_ns':current.get('start_ns'),
                        'primary_dispatch_ns':current['primary_ns'][0] if len(current['primary_ns'])==1 else None,
                        'preparation_ns':current['primary_ns'][0]-current['start_ns'] if len(current['primary_ns'])==1 else None,'dispatches':list(current['dispatches'])})
                    if status != 'PASS':
                        break
                    # Release harness retention only after quiescence; never alter app state or persisted data.
                    capture.bodies.clear();capture.sends.clear();lifecycle.evidence_states.clear()
        result={'arm':ARM,'samples':rows,'config_identity':config_identity(settings),'provider_calls':0,'external_calls':0}
        (OUT/(ARM+'-'+CELL+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    finally:
        await scoped.quiesce();await close()

if __name__=='__main__': asyncio.run(main())
