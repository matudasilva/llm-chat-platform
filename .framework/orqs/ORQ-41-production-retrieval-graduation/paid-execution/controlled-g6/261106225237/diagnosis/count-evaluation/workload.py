import csv, hashlib, json, re, statistics, time, uuid, sys
from pathlib import Path
ROOT = Path("/home/matias/Cursor/llm-chat-platform")
sys.path.insert(0, str(ROOT))
from types import SimpleNamespace
from contextlib import contextmanager
from app.core.observability import context_evidence as c1
from app.core.domain.provider_prompt import messages_for_provider
from app.core.domain.provider import ProviderInput
from app.core.domain.types import ChatMessage
from app.core.domain.conversation_history import HistoryMessage
from app.core.domain.rag_generation import RAG_SCHEMA_VERSION, RagSource, RagGenerationContext
from app.core.domain.chat_memory import ChatMemoryContext
from app.core.domain.context_packer import pack_recent_window
from app.core.domain.added_context_budget import enforce_added_context_cap
from app.core.domain.retrieval_pipeline import _REWRITE_PROMPT

ROOT = Path('/home/matias/Cursor/llm-chat-platform')
RUN = '261106172211'
BASE = ROOT/'.framework/orqs/ORQ-41-production-retrieval-graduation'
PROFILE = BASE/'paid-execution/controlled-g6/261106130053-rev2/diagnosis/profile-runs/261106153843'
OUT = BASE/'paid-execution/controlled-g6/261106225237/diagnosis/count-evaluation'
OUT.mkdir(parents=True, exist_ok=True)

# Decode only PostgreSQL COPY text escapes; rows come from the immutable P3 archive.
def decode_copy(s):
    out=[]; i=0
    esc={'b':'\b','f':'\f','n':'\n','r':'\r','t':'\t','v':'\v','\\':'\\'}
    while i < len(s):
        if s[i] != '\\': out.append(s[i]); i+=1; continue
        i+=1
        if i >= len(s): out.append('\\'); break
        ch=s[i]
        if ch in esc: out.append(esc[ch]); i+=1
        elif ch == 'x' and i+2 < len(s): out.append(chr(int(s[i+1:i+3],16))); i+=3
        elif ch in '01234567':
            j=i
            while j < min(i+3,len(s)) and s[j] in '01234567': j+=1
            out.append(chr(int(s[i:j],8))); i=j
        else: out.append(ch); i+=1
    return ''.join(out)

texts=[]; in_copy=False
for raw in Path('/tmp/orq41-p3-chunks.sql').open(encoding='utf-8'):
    line=raw.rstrip('\n')
    if line.startswith('COPY public.chunks '): in_copy=True; continue
    if in_copy and line == r'\.': break
    if not in_copy: continue
    fields=line.split('\t')
    if len(fields) < 5 or fields[2] != 'orq37-t23': continue
    texts.append({'chunk_id': fields[0], 'document_id': fields[1], 'ordinal': int(fields[3]), 'text': decode_copy(fields[4])})
assert len(texts) == 2146, len(texts)

fixtures=json.loads((PROFILE/'fixtures.json').read_text())
query='Explain how provider abstraction separates adapters from domain services.'
tokens=set(re.findall(r'[a-z0-9]+',query.lower()))
def score(row):
    words=re.findall(r'[a-z0-9]+',row['text'].lower())
    return sum(words.count(t) for t in tokens)
ranked_rows=sorted(texts,key=lambda r:(-score(r),r['ordinal'],r['chunk_id']))[:20]
assert len(ranked_rows)==20
selected=ranked_rows[:5]
chunks=[SimpleNamespace(chunk_id=uuid.UUID(r['chunk_id']),document_id=uuid.UUID(r['document_id']),text=r['text']) for r in ranked_rows]
ranked=[SimpleNamespace(chunk=ch,rank=i+1) for i,ch in enumerate(chunks)]
sources=[RagSource(citation=f'S{i+1}',document_id=ch.document_id,chunk_id=ch.chunk_id,content=ch.text[:4000],rank=i+1,truncated=len(ch.text)>4000) for i,ch in enumerate(chunks[:5])]
source_metadata=[s.provider_dict() for s in sources]

cases=[]
for item in fixtures:
    sample=item['sample']
    messages=[HistoryMessage(sequence=i+1,role=m['role'],content=m['content']) for i,m in enumerate(item['messages'])]
    use_docs=sample['category'] in ('document','combined')
    use_history=sample['category'] in ('history','combined')
    cases.append({'sample_id':sample['sample_id'],'category':sample['category'],'request_id':uuid.UUID(sample['request_id']),'messages':messages if use_history else [],'use_docs':use_docs,'current_message':sample['message'],'fixture_query':sample['message']})

# Exact C1 receipt helpers and provider-neutral prompt renderer; no API, DB or provider calls.
@contextmanager
def local_purpose(name):
    token=c1._purpose.set(name)
    try: yield
    finally: c1._purpose.reset(token)

def workload(case, active):
    global capture
    capture=Capture()
    request=str(case['request_id'])
    def body():
        c1.bind_scope(lambda:('orq37-t23',request))
        rewrite_input=ProviderInput(request_id=case['request_id'],messages=(ChatMessage(role='system',content=_REWRITE_PROMPT),ChatMessage(role='user',content=case['current_message'])),metadata={})
        with local_purpose('rewrite'):
            with c1.invocation():
                rewrite_rendered=messages_for_provider(rewrite_input)
        if case['use_docs']:
            c1.documents('documents.retrieved',chunks)
            c1.documents('documents.selected',ranked[:5],ranked=True)
            result=SimpleNamespace(chunks=ranked)
            c1.source_projection(result,sources)
        if case['messages']:
            c1.history('window.read',case['messages'])
            c1.history('window.bounded',case['messages'])
        c1.window_materialized(SimpleNamespace(window=case['messages']))
        recent=tuple(ChatMessage(role=m.role,content=m.content) for m in case['messages'])
        packed=pack_recent_window(recent,max_chars=12000)
        memory_context=ChatMemoryContext(messages=packed.messages,truncated=packed.truncated)
        rag_context=RagGenerationContext(sources=tuple(sources) if case['use_docs'] else (),outcome='ok' if case['use_docs'] else 'empty')
        memory_context,rag_context,_=enforce_added_context_cap(memory_context=memory_context,rag_context=rag_context,current_message=case['current_message'],max_chars=12000)
        metadata={}
        if rag_context.provider_metadata: metadata.update(rag_context.provider_metadata)
        if memory_context.provider_metadata: metadata.update(memory_context.provider_metadata)
        primary_messages=tuple(memory_context.messages)+(ChatMessage(role='user',content=case['current_message']),)
        primary_input=ProviderInput(request_id=case['request_id'],messages=primary_messages,metadata=metadata)
        with local_purpose('primary'):
            with c1.invocation():
                primary_rendered=messages_for_provider(primary_input)
        return {'rewrite':[{'role':m.role,'content':m.content} for m in rewrite_rendered], 'primary':[{'role':m.role,'content':m.content} for m in primary_rendered]}
    if not active: return body(), None
    with c1.request_evidence(request,request) as state:
        result=body()
    snap=state.snapshot()
    assert snap['valid'] and snap['closed']
    prev='0'*64
    for rec in snap['records']:
        assert rec['previous']==prev
        h=rec['hash']; raw=dict(rec); raw.pop('hash')
        assert h==hashlib.sha256(c1.encoded(raw)).hexdigest()
        prev=h
    assert state.size <= c1.MAX_BYTES and state.items <= c1.MAX_ITEMS
    return result, {'snapshot':snap,'bytes':state.size,'items':state.items,'head':prev,'bodies':[b.hex() for b in capture.bodies],'sends':capture.sends}

def output_hash(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

import botocore.session, botocore.serialize
from app.core.providers.bedrock_provider import _build_payload
from experiments.production_graduation.gate_validation.capture import Capture
service=botocore.session.get_session().get_service_model('bedrock-runtime')
serializer=botocore.serialize.create_serializer(service.metadata['protocol'])
operation=service.operation_model('Converse')
model=json.loads((BASE/'environment/g123/execution-freeze/settings/c1-C1.json').read_text())['redacted_effective_settings']['bedrock_model']
def dispatch(input):
    payload=_build_payload(input=input,model=model)
    raw=serializer.serialize_to_request(payload,operation)['body']
    capture.sent(raw,adapter='bedrock',application_attempt=1,sdk_attempt=1)
    pairs=[('system',b['text']) for b in payload.get('system',[])]
    pairs += [(m['role'],''.join(b['text'] for b in m['content'])) for m in payload['messages']]
    return tuple(ChatMessage(role=role,content=text) for role,text in pairs)
messages_for_provider=dispatch
