"""Offline rewrite capture calibration; never a G6 result."""
import contextlib, hashlib, json, statistics, time, uuid
from pathlib import Path
import botocore, botocore.session, botocore.serialize
from app.core.observability import context_evidence as evidence
from app.core.providers.bedrock_provider import _build_payload
from app.core.domain.retrieval_pipeline import _REWRITE_PROMPT
from app.core.domain.provider import ProviderInput
from app.core.domain.types import ChatMessage
from experiments.production_graduation.gate_validation.capture import Capture
from experiments.production_graduation.gate_validation.transports import Tape

ROOT=Path.cwd()
BASE=ROOT/'.framework/orqs/ORQ-41-production-retrieval-graduation'
G6=BASE/'paid-execution/controlled-g6/261106130053-rev2'
OUT=G6/'diagnosis/capture-calibration/20261106-batch-review'
OUT.mkdir(parents=True,exist_ok=False)
fixtures=G6/'fixtures.json'
plan=json.loads((G6/'plan.json').read_text())
for name in ('capture.py','transports.py','controlled_latency_worker.py'):
    key='experiments/production_graduation/gate_validation/'+name
    assert hashlib.sha256((ROOT/key).read_bytes()).hexdigest()==plan['harness_sha256'][key],key
settings=json.loads((BASE/'environment/g123/execution-freeze/settings/c1-C1.json').read_text())['redacted_effective_settings']
model=settings['bedrock_model']
service=botocore.session.get_session().get_service_model('bedrock-runtime')
serializer=botocore.serialize.create_serializer(service.metadata['protocol'])
operation=service.operation_model('Converse')
# All measured original fixture queries; serialization only, no SDK client.
rows=[r for r in json.loads(fixtures.read_text()) if not r['sample']['warmup']]
assert len(rows)==400
bodies=[]; expected=[]
for row in rows:
    query=row['sample']['message']
    pin=ProviderInput(request_id=uuid.UUID(row['sample']['request_id']),messages=(ChatMessage(role='system',content=_REWRITE_PROMPT),ChatMessage(role='user',content=query)))
    request=serializer.serialize_to_request(_build_payload(input=pin,model=model),operation)
    raw=request['body']; raw=raw.encode() if isinstance(raw,str) else bytes(raw)
    bodies.append(raw)
    expected.append([('system',_REWRITE_PROMPT),('user',query)])
(OUT/'inputs.json').write_text(json.dumps({'provenance':'reconstructed using current pinned-harness-compatible source builder and local botocore serializer, not retained historical wire bytes','model':model,'bodies':[b.decode() for b in bodies]},indent=2)+'\n')

def run(mode):
    capture=Tape() if mode=='tape' else Capture()
    active=mode=='capture_active'
    cm=evidence.request_evidence('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002') if active else contextlib.nullcontext(None)
    with cm as state:
        token=evidence._purpose.set('rewrite')
        try:
            cpu=time.thread_time_ns(); wall=time.monotonic_ns()
            for body in bodies: capture.sent(body,adapter='bedrock')
            wall=time.monotonic_ns()-wall; cpu=time.thread_time_ns()-cpu
        finally: evidence._purpose.reset(token)
    # Validation is outside both clocks. Never omit receipt or hash checks.
    assert capture.bodies==bodies and len(capture.sends)==400
    for index,(raw,send,msgs) in enumerate(zip(bodies,capture.sends,expected)):
        key='sha256' if mode=='tape' else 'payload_sha256'
        assert send[key]==hashlib.sha256(raw).hexdigest()
        if mode!='tape':
            assert send['send_ordinal']==index and send['payload_bytes']==len(raw)
            assert send['items']==[dict(key=str(i),occurrence=0,start=0,end=len(text),chars=len(text),original_chars=len(text),bytes=len(text.encode()),sha256=hashlib.sha256(text.encode()).hexdigest(),role=role) for i,(role,text) in enumerate(msgs)]
    if active:
        snapshot=state.snapshot(); assert snapshot['valid'] and snapshot['closed']
        previous='0'*64; dispatched=[]
        for index,record in enumerate(snapshot['records']):
            value={k:v for k,v in record.items() if k!='hash'}
            assert record['ordinal']==index and record['previous']==previous
            assert hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()==record['hash']
            previous=record['hash']
            if record['stage']=='transport.dispatched': dispatched.append(record)
        assert len(dispatched)==400
        for record,send in zip(dispatched,capture.sends):
            assert record['data']=={k:v for k,v in send.items() if k not in ('instance_id','correlation_id','invocation','purpose')}
        assert state.size<=evidence.MAX_BYTES and state.items<=evidence.MAX_ITEMS
    return {'batch_sends':400,'wall_ns':wall,'thread_cpu_ns':cpu}

modes=['tape','capture_passive','capture_active']
for mode in modes: run(mode)
measurements={m:[] for m in modes}
for repeat in range(9):
    order=modes[repeat%3:]+modes[:repeat%3]
    if repeat%2: order=list(reversed(order))
    for mode in order: measurements[mode].append(run(mode))
summary={mode:{'median_cpu_us_per_send':statistics.median(x['thread_cpu_ns'] for x in samples)/400/1000,'min_cpu_us_per_send':min(x['thread_cpu_ns'] for x in samples)/400/1000,'max_cpu_us_per_send':max(x['thread_cpu_ns'] for x in samples)/400/1000,'median_wall_us_per_send':statistics.median(x['wall_ns'] for x in samples)/400/1000} for mode,samples in measurements.items()}
result={'status':'CAPTURE_CALIBRATION_COMPLETE_NOT_A_GATE','fixture_sha256':hashlib.sha256(fixtures.read_bytes()).hexdigest(),'botocore_version':botocore.__version__,'model':model,'input_shape':'400 measured original fixture queries, rewrite-only, locally reconstructed serialized bodies','measurements':measurements,'summary':summary,'validation':'raw bodies, independently computed text receipts, dispatch order, observer reconciliation, hash chain and caps PASS','limitations':['one context per batch rather than per request; lifecycle setup/teardown excluded','no ASGI/DB/provider execution; rewrite-only capture, no scopes or SDK hooks timed','current host/interpreter, not pinned source container resources; not historical latency attribution','batch mean costs cannot be subtracted from historical p95 or establish gate PASS'],'g6_status_unchanged':True,'api_requests':0,'database_queries':0,'provider_calls':0,'paid_spend_usd':'0'}
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
(OUT/'calibrate.py').write_text(Path(__file__).read_text())
print(json.dumps(summary,indent=2)); print(OUT)
