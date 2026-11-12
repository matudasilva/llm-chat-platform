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
OUT = BASE/'paid-execution/controlled-g6/261106130053-rev2/diagnosis/offline-replay'/RUN
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
    return result, {'records':snap['count'],'bytes':state.size,'items':state.items,'head':prev}

def output_hash(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
# Warm-up both modes, compare all output bytes and expected inputs before timing.
for case in cases:
    plain,_=workload(case,False); observed,receipt=workload(case,True)
    assert plain==observed
    assert receipt is not None
parity=[output_hash(workload(c,False)[0]) for c in cases]
assert parity == [output_hash(workload(c,True)[0]) for c in cases]

batch_repeats=20
samples=5
results={'passive_no_request_evidence':[],'active_c1_evidence':[]}
for rep in range(samples):
    order=['passive_no_request_evidence','active_c1_evidence'] if rep%2==0 else ['active_c1_evidence','passive_no_request_evidence']
    for mode in order:
        active=mode=='active_c1_evidence'
        cpu0=time.thread_time_ns(); wall0=time.perf_counter_ns(); digest=hashlib.sha256(); n=0; recs=0; total_bytes=0
        for _ in range(batch_repeats):
            for case in cases:
                out,receipt=workload(case,active)
                digest.update(output_hash(out).encode()); n+=1
                if receipt: recs+=receipt['records']; total_bytes+=receipt['bytes']
        results[mode].append({'requests':n,'wall_ns':time.perf_counter_ns()-wall0,'thread_cpu_ns':time.thread_time_ns()-cpu0,'output_batch_sha256':digest.hexdigest(),'evidence_records':recs,'evidence_bytes':total_bytes})

report={'schema':'orq41-offline-c1-cpu-replay-v1','run_id':RUN,'not_a_gate':True,'external_calls':0,'api_requests':0,'database_queries':0,'provider_calls':0,'paid_spend_usd':'0','network_mode':'offline process; P3 dump read from local file; no service/network calls','source_identity':{'snapshot_sha256':'0334e3af47edf9c885093a6ad061390f6f85ba62517e56b94450339950599d4f','p3_content_sha256':'9fa959aeeb5d332882d61f60528eaa72468f110705c51ce05b70e213dd168506','chunks_loaded':len(texts)},'workload':{'fixture_sha256':hashlib.sha256((PROFILE/'fixtures.json').read_bytes()).hexdigest(),'fixture_cases':len(cases),'categories':sorted({c['category'] for c in cases}),'retrieved_candidates':20,'selected_sources':5,'history_messages_max':max(map(lambda c:len(c['messages']),cases)),'selection':'deterministic lexical-overlap reconstruction from frozen P3 chunks; not the original retrieval ranking','receipt_calls':'existing context_evidence helpers: request/scope, rewrite and primary invocations/prompts, retrieved/selected/projected sources, window read/bound/materialized/packed, final combined cap, prompt mapping and rendering','batch_repetitions':batch_repeats,'measured_batches_per_arm':samples},'integrity':{'passive_and_active_rendered_payloads_equal':True,'active_receipt_chains_validated':True,'observed_output_hashes':parity,'limit_bytes':c1.MAX_BYTES,'limit_items':c1.MAX_ITEMS},'measurements':results,'interpretation':'Aggregate local CPU/wall comparison of active C1 evidence versus the same provider-neutral prompt path with no request evidence context. Reconstructed retrieval selection and synthetic fixture histories are not a full API replay; timing is descriptive and cannot replace controlled G6 p95 or attribute the prior regression.'}
(OUT/'result.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
md=['# Offline aggregate CPU replay (diagnostic only)','',f"Run: `{RUN}`. Not a gate; no API, database service, provider, network or paid calls.",'',f"P3 snapshot content SHA-256: `{report['source_identity']['p3_content_sha256']}`; loaded {len(texts)} frozen chunks from the local custom dump.",'',f"Workload: {len(cases)} frozen request fixtures across {', '.join(report['workload']['categories'])}; up to 20 candidates and 5 selected source chunks. Retrieved ranking is a deterministic lexical reconstruction, not the original ranking. Existing frozen conversation histories are used.",'','The replay executes the existing C1 evidence helpers and provider-neutral prompt renderer. The passive control omits request evidence state but uses the same inputs and renderer. All rendered outputs matched exactly, active evidence chains validated, and configured receipt limits were preserved. Batch measurements are aggregate thread CPU and monotonic wall time; no per-operation instrumentation was active.','', '| Arm | Batch | Median thread CPU (ms) | Median wall (ms) | CPU range (ms) |', '|---|---:|---:|---:|---:|']
for mode,arr in results.items():
    cpus=[x['thread_cpu_ns']/1e6 for x in arr]; walls=[x['wall_ns']/1e6 for x in arr]
    md.append(f"| {mode} | {arr[0]['requests']} workloads | {statistics.median(cpus):.3f} | {statistics.median(walls):.3f} | {min(cpus):.3f}–{max(cpus):.3f} |")
md += ['', 'These figures do not establish a causal percentage of the previous p95 delta and do not predict a G6 pass. They identify aggregate cost of the active evidence path under this reconstructed workload only. A runtime optimization still requires a minimal proposal, operator approval, semantic/evidence tests, and a fresh pinned controlled C0/C1 N=100 run in all four cells with independent review. The historical `CONTROLLED_G6_FAIL` remains unchanged.', '']
(OUT/'report.md').write_text('\n'.join(md))
print(OUT)
print(json.dumps({k:[(x['thread_cpu_ns']//1000000,x['wall_ns']//1000000) for x in v] for k,v in results.items()}))
