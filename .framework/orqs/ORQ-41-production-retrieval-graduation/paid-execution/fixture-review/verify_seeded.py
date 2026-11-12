"""Independent, strictly read-only verification of the seeded paid fixtures.

Execution may be delegated to the parent with approved local Docker access.
All PostgreSQL sessions are READ ONLY; no API or provider call is performed.
"""
import hashlib,json,subprocess,uuid
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path('.framework/orqs/ORQ-41-production-retrieval-graduation')
HERE=ROOT/'paid-execution'; OUT=HERE/'fixture-review/seeded-verification.json'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def docker(*args,data=None):
    result=subprocess.run(['docker','--host','unix:///var/run/docker.sock',*args],input=data,capture_output=True,timeout=120)
    if result.returncode:raise RuntimeError('Read-only verification Docker command failed: '+args[0])
    return result.stdout

def sql(query,*,container='orq41-paid-pg',database='orq41_paid'):
    # query strings below are fixed SELECT/COPY and SET LOCAL session scope only.
    return docker('exec','-i',container,'psql','-X','-q','-At','-v','ON_ERROR_STOP=1','-U','orq41owner','-d',database,
                  data=('BEGIN READ ONLY;\n'+query+'\nROLLBACK;\n').encode()).decode()
def quote(value):return "'"+value.replace("'","''")+"'"
def normalize_schema(raw):
    return b'\n'.join(line.strip() for line in raw.splitlines() if line.strip() and not line.lstrip().startswith((b'--',b'\\restrict ',b'\\unrestrict ')))
def main():
    assert not OUT.exists(),'Do not overwrite independent verification receipt'
    db=json.loads((HERE/'database.json').read_text());fixture=json.loads((HERE/'fixtures.prospective.json').read_text())
    materialization=json.loads((HERE/'materialization.json').read_text());meta=json.loads((ROOT/'corpus-snapshot/corpus-snapshot.json').read_text())
    assert sha((HERE/'fixtures.prospective.json').read_bytes())==db['fixture_file_sha256']
    assert all(sha((HERE/name).read_bytes())==digest for name,digest in materialization['files_sha256'].items())
    target=json.loads(docker('inspect','orq41-paid-pg'))[0]
    assert target['Id']==db['container_id'] and target['Image']==db['image'] and target['State']['Running']
    assert not target['HostConfig'].get('PortBindings') and not any((target['NetworkSettings'].get('Ports') or {}).values())
    accepted_pg=json.loads((ROOT/'environment/g9/runs/261105143941/manifest.json').read_text())['images']['postgres']
    assert target['Image']==accepted_pg
    assert set(target['NetworkSettings']['Networks'])=={'orq41-paid-internal'}
    network=json.loads(docker('network','inspect','orq41-paid-internal'))[0];assert network['Internal'] is True
    assert target['HostConfig']['NanoCpus']==2_000_000_000
    assert target['HostConfig']['Memory']==target['HostConfig']['MemorySwap']==2_147_483_648
    query="""SELECT json_build_object(
      'conversations',(SELECT coalesce(json_agg(row_to_json(x)),'[]'::json) FROM (SELECT id::text,tenant_id FROM conversations ORDER BY id) x),
      'messages',(SELECT coalesce(json_agg(row_to_json(x)),'[]'::json) FROM (SELECT id::text,conversation_id::text,tenant_id,role::text,content,sequence FROM messages ORDER BY sequence) x),
      'documents',(SELECT coalesce(json_agg(row_to_json(x)),'[]'::json) FROM (SELECT tenant_id,source_path,content_hash FROM documents ORDER BY tenant_id,source_path,content_hash) x),
      'chunk_counts',(SELECT coalesce(json_agg(row_to_json(x)),'[]'::json) FROM (SELECT tenant_id,count(*) AS count FROM chunks GROUP BY tenant_id ORDER BY tenant_id) x),
      'revision',(SELECT version_num FROM alembic_version));"""
    initial=sql(query);observed=json.loads(initial)
    expected={row['conversation_id']:row for row in fixture['conversations']}
    assert len(expected)==len(observed['conversations'])==168 and len(observed['messages'])==3840
    assert {row['id']:row['tenant_id'] for row in observed['conversations']}=={cid:row['tenant_id'] for cid,row in expected.items()}
    by_conv=defaultdict(list);ids=set();sequences=set()
    for row in observed['messages']:
        assert str(uuid.UUID(row['id']))==row['id'] and row['id'] not in ids;ids.add(row['id'])
        assert type(row['sequence']) is int and row['sequence']>0 and row['sequence'] not in sequences;sequences.add(row['sequence'])
        assert row['conversation_id'] in expected and row['tenant_id']==expected[row['conversation_id']]['tenant_id']
        by_conv[row['conversation_id']].append(row)
    checked=[]
    for cid,fixture_row in expected.items():
        assert str(uuid.UUID(cid))==cid
        actual=by_conv[cid]
        assert [{'role':row['role'],'content':row['content']} for row in actual]==fixture_row['messages'],cid
        assert all(a['sequence']<b['sequence'] for a,b in zip(actual,actual[1:])),cid
        checked.append({'conversation_id':cid,'messages':len(actual),'ordered_message_projection_sha256':sha(canonical(actual))})
    docs=observed['documents'];assert len(docs)==meta['identity']['documents']==124
    assert all(row['tenant_id']=='orq37-t23' for row in docs)
    fingerprint=sha('\n'.join(sorted(row['source_path']+':'+row['content_hash'] for row in docs)).encode())
    assert fingerprint==meta['identity']['content_fingerprint']==db['corpus_fingerprint']
    assert observed['chunk_counts']==[{'tenant_id':'orq37-t23','count':2146}]
    projection=sql('COPY ('+meta['identity']['snapshot_content_projection'].split('  (psql')[0]+') TO STDOUT;')
    assert sha(projection.encode())==meta['identity']['snapshot_content_sha256']==db['corpus_content_sha256']
    tenants=sorted({row['tenant_id'] for row in expected.values()});rls={}
    for tenant in tenants+['', 'orq41-review-unknown-tenant']:
        value=json.loads(sql('SET LOCAL ROLE rag_app; SET LOCAL app.tenant_id='+quote(tenant)+"; SELECT json_build_object('documents',(SELECT count(*) FROM documents),'chunks',(SELECT count(*) FROM chunks));"))
        assert value==({'documents':124,'chunks':2146} if tenant=='orq37-t23' else {'documents':0,'chunks':0})
        rls[tenant]=value
    paid_raw=docker('exec','orq41-paid-pg','pg_dump','-U','orq41owner','-d','orq41_paid','--schema-only')
    baseline_raw=docker('exec','orq41-env-pg','pg_dump','-U','orq41owner','-d','orq41','--schema-only')
    paid_schema=normalize_schema(paid_raw);baseline_schema=normalize_schema(baseline_raw)
    old_check=b"CONSTRAINT ck_usage_events_feedback CHECK (((feedback IS NULL) OR ((feedback)::text = ANY ((ARRAY['up'::character varying, 'down'::character varying])::text[]))))"
    new_check=b"CONSTRAINT ck_usage_events_feedback CHECK (((feedback IS NULL) OR ((feedback)::text = ANY (ARRAY[('up'::character varying)::text, ('down'::character varying)::text]))))"
    equivalent_cast_rewrite=False
    if paid_schema!=baseline_schema:
        assert baseline_schema.splitlines().count(old_check)==paid_schema.splitlines().count(new_check)==1
        assert baseline_schema.replace(old_check,b'EXACT_REVIEWED_FEEDBACK_CONSTRAINT')==paid_schema.replace(new_check,b'EXACT_REVIEWED_FEEDBACK_CONSTRAINT'),'Unreviewed schema/grant/policy difference'
        equivalent_cast_rewrite=True
    locale_query="SELECT json_build_object('collate',datcollate,'ctype',datctype) FROM pg_database WHERE datname=current_database();"
    locale=json.loads(sql(locale_query));assert locale==json.loads(sql(locale_query,container='orq41-env-pg',database='orq41'))
    samples=[None,'','up','down','UP','Down','up ',' down','unknown','u','down\t']
    expressions={}
    for label,container,database in [('baseline','orq41-env-pg','orq41'),('paid','orq41-paid-pg','orq41_paid')]:
        expression=sql("SELECT pg_get_expr(conbin,conrelid) FROM pg_constraint WHERE conname='ck_usage_events_feedback' AND conrelid='public.usage_events'::regclass;",container=container,database=database).strip()
        assert expression
        values=','.join('('+str(i)+','+('NULL' if value is None else quote(value))+'::varchar(8))' for i,value in enumerate(samples))
        table=json.loads(sql('SELECT json_agg(row_to_json(x)) FROM (SELECT ord,feedback,('+expression+') AS accepted FROM (VALUES '+values+') v(ord,feedback) ORDER BY ord) x;',container=container,database=database))
        assert [row['accepted'] for row in table]==[value in (None,'up','down') for value in samples]
        expressions[label]={'expression_sha256':sha(expression.encode()),'truth_table':table}
    assert expressions['baseline']['truth_table']==expressions['paid']['truth_table']
    schema_comparison={'raw_paid_sha256':sha(paid_raw),'raw_baseline_sha256':sha(baseline_raw),'normalized_paid_sha256':sha(paid_schema),'normalized_baseline_sha256':sha(baseline_schema),'exact_feedback_cast_rewrite_only':equivalent_cast_rewrite,'locale':locale,'constraint_checks':expressions}
    assert observed['revision']=='e4b7f21c9a06'
    assert sql(query)==initial,'Database changed during verification'
    assert sha(sql('COPY ('+meta['identity']['snapshot_content_projection'].split('  (psql')[0]+') TO STDOUT;').encode())==meta['identity']['snapshot_content_sha256']
    result={'status':'SEEDED_PAID_FIXTURES_INDEPENDENT_VERIFIER_PASS','verifier_author':'/root/g9_final_distinct_reviewer','executor':'parent agent with approved P2 Docker access','container_id':target['Id'],'image':target['Image'],'network_internal':True,'published_ports':False,'conversations_checked':168,'messages_checked':3840,'conversation_checks':checked,'unique_generated_message_ids':len(ids),'schema_parity':True,'normalized_schema_sha256':sha(paid_schema),'corpus_fingerprint':fingerprint,'corpus_content_sha256':sha(projection.encode()),'tenant_rls':rls,'fixture_sha256':db['fixture_file_sha256'],'verifier_sha256':sha(Path(__file__).read_bytes()),'read_only_transactions':True,'database_writes':0,'api_calls':0,'provider_calls':0,'spend_usd':'0','limitations':['Prospective fixtures do not pin individual message UUIDs; generated UUID validity/uniqueness and exact content/order/ownership were checked','Operational history tables retain existing baseline lack of RLS; rag_app documents/chunks RLS tested, no new history RLS claimed','No paid target/API/provider network or TTFT readiness certified']}
    result['schema_comparison']=schema_comparison
    OUT.write_text(json.dumps(result,indent=2)+'\n');print(result['status'], '168 conversations;3840 messages;schema/P3/RLS match')
if __name__=='__main__':main()
