"""Independent pre-execution DB/config proof. Parent executes approved P2 Docker.

Only READ ONLY SELECT/COPY and transaction-local role/tenant context. Config
containers import settings under network none, never app lifespan or API calls.
"""
import argparse,hashlib,json,subprocess,tempfile,uuid
from collections import defaultdict, Counter
from pathlib import Path
ROOT=Path.cwd();ORQ=ROOT/'.framework/orqs/ORQ-41-production-retrieval-graduation';PG='orq41-env-pg'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def docker(*args,data=None):
 r=subprocess.run(['docker','--host','unix:///var/run/docker.sock',*args],input=data,capture_output=True,timeout=180)
 if r.returncode:raise RuntimeError('Independent read-only Docker failure: '+args[0])
 return r.stdout
def sql(db,query):return docker('exec','-i',PG,'psql','-X','-q','-At','-v','ON_ERROR_STOP=1','-U','orq41owner','-d',db,data=('BEGIN READ ONLY;\n'+query+'\nROLLBACK;').encode()).decode()
def quote(s):return "'"+s.replace("'","''")+"'"
def normalized(raw):return b'\n'.join(x.strip() for x in raw.splitlines() if x.strip() and not x.lstrip().startswith((b'--',b'\\restrict ',b'\\unrestrict ')))
def readonly(container,database,query):
 return docker('exec','-i',container,'psql','-X','-q','-At','-v','ON_ERROR_STOP=1','-U','orq41owner','-d',database,data=('BEGIN READ ONLY;\n'+query+'\nROLLBACK;').encode()).decode()
def constraint_proof(plan):
 old=b"CONSTRAINT ck_usage_events_feedback CHECK (((feedback IS NULL) OR ((feedback)::text = ANY ((ARRAY['up'::character varying, 'down'::character varying])::text[]))))"
 new=b"CONSTRAINT ck_usage_events_feedback CHECK (((feedback IS NULL) OR ((feedback)::text = ANY (ARRAY[('up'::character varying)::text, ('down'::character varying)::text]))))"
 source=normalized(docker('exec','orq41-env-pg','pg_dump','-U','orq41owner','-d','orq41','--schema-only'))
 checks={};samples=[None,'','up','down','UP','Down','up ',' down','unknown','u','down\t']
 for label,container,database in [('source','orq41-env-pg','orq41'),*[(arm,plan['containers']['postgres'],db) for arm,db in plan['databases'].items()]]:
  schema=normalized(docker('exec',container,'pg_dump','-U','orq41owner','-d',database,'--schema-only'))
  assert schema.splitlines().count(old)+schema.splitlines().count(new)==1
  assert source.replace(old,new)==schema.replace(old,new),'Unreviewed schema difference'
  locale=json.loads(readonly(container,database,"SELECT json_build_object('encoding',pg_encoding_to_char(encoding),'collate',datcollate,'ctype',datctype,'provider',datlocprovider,'icu_locale',daticulocale) FROM pg_database WHERE datname=current_database();"))
  assert locale==plan['database_locale']
  expr=readonly(container,database,"SELECT pg_get_expr(conbin,conrelid) FROM pg_constraint WHERE conname='ck_usage_events_feedback' AND conrelid='public.usage_events'::regclass;").strip()
  vals=','.join('('+str(i)+','+('NULL' if v is None else quote(v))+'::varchar(8))' for i,v in enumerate(samples))
  truth=json.loads(readonly(container,database,'SELECT json_agg(row_to_json(x)) FROM (SELECT ord,feedback,('+expr+') AS accepted FROM (VALUES '+vals+') v(ord,feedback) ORDER BY ord) x;'))
  assert [x['accepted'] for x in truth]==[v in (None,'up','down') for v in samples]
  roles=readonly(container,database,"SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname IN ('rag_app','chat_ops') ORDER BY rolname;").strip().splitlines()
  assert roles==['chat_ops|f|f','rag_app|f|f']
  checks[label]=dict(raw_normalized_schema_sha256=sha(schema),locale=locale,expression_sha256=sha(expr.encode()),truth_table=truth,role_capabilities=roles)
 assert checks['source']['truth_table']==checks['c0']['truth_table']==checks['c1']['truth_table']
 return checks
def protocol_proof(run,plan,fixtures,cases):
 assert plan['schema']=='orq41-blocked-aa-v1' and plan['mode']=='aa_full_c1_both_arms' and plan['full_c1_both_arms'] is True
 assert plan['images']['c0']==plan['images']['c1'] and plan['concurrency']==plan['sample_attempts']==plan['repetitions']==1
 assert len(plan['arm_cell_order'])==32 and len(plan['samples'])==720
 assert not (run/'execution-started.json').exists() and not (run/'execution-authorization.json').exists()
 contract=json.loads((ORQ/'paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/contract.json').read_text())
 assert sha((ORQ/'paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/contract.json').read_bytes())==plan['amendment_sha256']
 order=[];cells=[]
 for cell in ('EN-json','EN-sse','ES-json','ES-sse'):
  lang,protocol=cell.split('-');rows=[x for x in plan['samples'] if x['language']==lang and x['protocol']==protocol]
  assert len(rows)==180 and Counter(x['category'] for x in rows if not x['warmup'])==dict.fromkeys(('document','history','combined','empty'),25)
  expected_cases=[x['case_id'] for x in cases if x['language']==lang]
  assert Counter(x['case_id'] for x in rows if not x['warmup'])==dict.fromkeys(expected_cases,5)
  occurrences=Counter();first=Counter()
  for b in range(4):
   block=[x for x in rows if x['block']==b];assert len(block)==45 and [x['warmup'] for x in block]==[True]*20+[False]*25
   assert Counter(x['case_id'] for x in block[:20])==dict.fromkeys(expected_cases,1)
   for j,row in enumerate(block[20:]):
    cat=contract['categories'][(b+j)%4];assert row['category']==cat and row['ordinal']==j
    assert row['case_id']==contract['case_order_by_language_category'][lang][cat][occurrences[cat]%5];occurrences[cat]+=1
   for j,row in enumerate(block[:20]):
    cat=contract['categories'][j%4];assert row['ordinal']==j and row['category']==cat and row['case_id']==contract['case_order_by_language_category'][lang][cat][j//4]
   arms=['c0' if label=='A' else 'c1' for label in contract['block_arm_order'][cell][b]];first[arms[0]]+=1
   order.extend(dict(arm=arm,cell=cell,block=b) for arm in arms)
  assert first==dict(c0=2,c1=2)
  cells.append(dict(cell=cell,measured_per_arm=100,warmups_per_arm=80,category_measured=dict.fromkeys(contract['categories'],25),first_blocks=dict(first)))
 assert order==plan['arm_cell_order']
 old_requests=set();old_conversations=set();histories=0
 for file in (ORQ/'paid-execution').rglob('plan.json'):
  if file.resolve()==(run/'plan.json').resolve():continue
  data=json.loads(file.read_text());samples=data.get('samples',[])
  if not isinstance(samples,list):continue
  histories+=1
  for row in samples:
   if isinstance(row,dict):
    if isinstance(row.get('request_id'),str):old_requests.add(row['request_id'])
    if isinstance(row.get('conversation_id'),str):old_conversations.add(row['conversation_id'])
 assert not old_requests & {x['request_id'] for x in rows_of_plan(plan)}
 assert not old_conversations & {x['conversation_id'] for x in rows_of_plan(plan)}
 return dict(cells=cells,total_future_requests=1440,total_measured=800,total_warmups=640,historical_manifests_checked=histories,all720request_and_conversation_UUIDs_fresh=True,application_requests=0)
def rows_of_plan(plan):return plan['samples']
def preparation_proof(plan,prep):
 tables=['alembic_version','chunks','conversations','documents','messages','rag_request_metrics','usage_events'];proof=[]
 settings_query="SELECT json_object_agg(name,setting ORDER BY name) FROM pg_settings WHERE name LIKE 'autovacuum%' OR name='default_statistics_target' OR category LIKE 'Query Tuning%';"
 source_settings=json.loads(readonly('orq41-env-pg','orq41',settings_query))
 for row in prep['analyses']:
  assert row['database'] in plan['databases'].values()
  assert row['statements']==['ANALYZE "public"."'+table+'";' for table in tables]
  actual=json.loads(sql(row['database'],"SELECT json_object_agg(relname,last_analyze::text) FROM pg_stat_user_tables WHERE schemaname='public';"))
  assert set(actual)==set(tables) and all(actual.values()) and actual==row['completion']
  cfg=json.loads(sql(row['database'],settings_query));assert cfg==row['settings']==source_settings
  proof.append(dict(database=row['database'],table_inventory=tables,last_analyze=actual,settings_sha256=sha(json.dumps(cfg,sort_keys=True).encode()),analyze_reexecuted=False))
 assert len(proof)==2
 return proof

def main(run):
 global PG
 run=Path(run);plan=json.loads((run/'plan.json').read_text());prep=json.loads((run/'preparation.json').read_text());fixtures=json.loads((run/'fixtures.json').read_text());cases=json.loads((ORQ/'paid-execution/cases.json').read_text())['cases'];meta=json.loads((ORQ/'corpus-snapshot/corpus-snapshot.json').read_text());out=run/'independent-audit/prepared-databases-verification.json'
 PG=plan['containers']['postgres']
 assert not out.exists()
 assert prep['plan_sha256']==sha((run/'plan.json').read_bytes()) and prep['fixtures_sha256']==sha((run/'fixtures.json').read_bytes())
 assert plan['support_files_sha256'][str((ORQ/'paid-execution/cases.json').relative_to(ROOT))]==sha((ORQ/'paid-execution/cases.json').read_bytes())
 for name,digest in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():assert sha((ROOT/name).read_bytes())==digest,name
 assert len(plan['samples'])==len(fixtures)==720
 expected={}
 for fixture,sample in zip(fixtures,plan['samples']):
  assert fixture['sample']==sample
  cid=sample['conversation_id'];assert cid==str(uuid.uuid5(uuid.UUID(plan['namespace']),sample['sample_id']))
  assert sample['request_id']==str(uuid.uuid5(uuid.UUID(plan['namespace']),'request/'+sample['sample_id']))
  match=[c for c in cases if all(c[k]==sample[k] for k in ('language','category','tenant_id','message'))];assert len(match)==1
  assert match[0]['history']==fixture['messages'] and match[0]['case_id']==sample['case_id']
  expected[cid]=fixture
 assert len(expected)==720
 pg=json.loads(docker('inspect',PG))[0];assert pg['Image']==plan['postgres_image'] and pg['HostConfig']['NetworkMode']=='none' and not pg['HostConfig'].get('PortBindings')
 query="SELECT json_build_object('conversations',(SELECT json_agg(x) FROM (SELECT id::text,tenant_id FROM conversations ORDER BY id) x),'messages',(SELECT json_agg(x) FROM (SELECT id::text,conversation_id::text,tenant_id,role::text,content,sequence FROM messages ORDER BY sequence) x));"
 receipts=[];schemas=[];business=[]
 for arm,db in plan['databases'].items():
  first=sql(db,query);data=json.loads(first);assert len(data['conversations'])==720 and len(data['messages'])==17280
  assert {r['id']:r['tenant_id'] for r in data['conversations']}=={cid:f['sample']['tenant_id'] for cid,f in expected.items()}
  rows=defaultdict(list);ids=set();seqs=set()
  for r in data['messages']:
   assert str(uuid.UUID(r['id']))==r['id'] and r['id'] not in ids;ids.add(r['id'])
   assert type(r['sequence']) is int and r['sequence']>0 and r['sequence'] not in seqs;seqs.add(r['sequence'])
   assert r['conversation_id'] in expected and r['tenant_id']==expected[r['conversation_id']]['sample']['tenant_id'];rows[r['conversation_id']].append(r)
  for cid,f in expected.items():
   actual=rows[cid];assert [{'role':r['role'],'content':r['content']} for r in actual]==f['messages']
   for i,r in enumerate(actual):assert r['id']==str(uuid.uuid5(uuid.UUID(plan['namespace']),f['sample']['sample_id']+'/history/'+str(i)))
  corpus=sql(db,'COPY ('+meta['identity']['snapshot_content_projection'].split('  (psql')[0]+') TO STDOUT;');assert sha(corpus.encode())==meta['identity']['snapshot_content_sha256']
  counts=sql(db,'SELECT (SELECT count(*) FROM documents),(SELECT count(*) FROM chunks);').strip();assert counts=='124|2146'
  rls={}
  for tenant in sorted({f['sample']['tenant_id'] for f in fixtures})+['','independent-unknown']:
   n=int(sql(db,'SET LOCAL ROLE rag_app; SET LOCAL app.tenant_id='+quote(tenant)+'; SELECT count(*) FROM chunks;').strip());assert n==(2146 if tenant=='orq37-t23' else 0);rls[tenant]=n
  ddl=normalized(docker('exec',PG,'pg_dump','-U','orq41owner','-d',db,'--schema-only'));schemas.append(ddl)
  assert sql(db,query)==first
  business.append(sha(first.encode()));receipts.append({'arm':arm,'database':db,'conversations':720,'messages':17280,'business_projection_sha256':sha(first.encode()),'normalized_schema_sha256':sha(ddl),'corpus_content_sha256':sha(corpus.encode()),'rls':rls})
 assert schemas[0]==schemas[1] and business[0]==business[1]
 assert sha(schemas[0])==plan['source_schema_sha256']
 assert pg['HostConfig']['CpusetCpus']=='4,6'
 assert docker('exec',PG,'cat','/sys/fs/cgroup/cpuset.cpus.effective').strip()==b'4,6'
 assert docker('exec',PG,'cat','/sys/fs/cgroup/cpu.max').strip()==b'200000 100000'
 checks=constraint_proof(plan)
 protocol=protocol_proof(run,plan,fixtures,cases)
 preparation=preparation_proof(plan,prep)
 from experiments.production_graduation.gate_validation.g9_controller import env_for,P2_GUARD,private_write
 passwords=json.loads((Path(prep['private_state'])/'local-credentials.json').read_text());private=Path(tempfile.mkdtemp(prefix='orq41-independent-g6-settings-'));private.chmod(0o700)
 code="""import json,hashlib,os,pathlib
assert os.sched_getaffinity(0)=={0,2}
assert pathlib.Path("/sys/fs/cgroup/cpuset.cpus.effective").read_text().strip()=="0,2"
assert pathlib.Path("/sys/fs/cgroup/cpu.max").read_text().strip()=="200000 100000"
from sqlalchemy.engine import make_url
from experiments.production_graduation.gate_validation.validate_g123 import check_p2,check_config,config_identity
check_p2()
from app.core.settings import settings
check_config(settings)
values=settings.model_dump(mode='json')
for key,value in list(values.items()):
 if 'url' in key and value:
  u=make_url(str(value));u=u.set(database='CONTROLLED_PAIRED_DB') if key in ('database_url_override','database_url_app','database_url_ops') else u
  values[key]=u.render_as_string(hide_password=True)
 elif key.endswith(('password','secret','api_key','access_token','credential')) or key in ('aws_access_key_id','aws_session_token'):values[key]=bool(value)
print(json.dumps({'full':config_identity(settings),'normalized':hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'seed':__import__('experiments.production_graduation.gate_validation.blocked_latency',fromlist=['seed_probe']).seed_probe()}))
"""
 configs={}
 for arm,db in plan['databases'].items():
  env=env_for(arm,'C1',db,passwords);env.update(PYTHONPATH='/p2_netguard:/app',PATH='/usr/local/bin:/usr/bin:/bin',PYTHONHASHSEED='41');path=private/(arm+'.env');private_write(path,''.join(k+'='+v+'\n' for k,v in sorted(env.items())).encode())
  cfg=json.loads(docker('run','--rm','--pull=never','--network','none','--cpus=2','--cpuset-cpus','0,2','--memory=2147483648','--memory-swap=2147483648','--env-file',str(path),'--mount',f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly','--mount',f'type=bind,src={P2_GUARD},dst=/p2_netguard,readonly','--entrypoint','/usr/local/bin/python',plan['images'][arm],'-c',code).decode());assert cfg['full']==plan['config_sha256'][arm] and cfg['seed']==plan['seed_probe'];configs[arm]=cfg
 assert configs['c0']['normalized']==configs['c1']['normalized']==plan['normalized_config_sha256'],'Effective configuration differs beyond database names'
 result={'status':'BLOCKED_AA_PREPARED_DATABASES_READONLY_VERIFIER_PASS','verifier_author':'adapted previous independent verifier; current parent execution, not distinct SQL attestation','executor':'parent approved P2 Docker access','plan_sha256':sha((run/'plan.json').read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes()),'arms':receipts,'configuration':configs,'constraint_and_locale_proof':checks,'protocol_proof':protocol,'preparation_proof':preparation,'worker_effective_affinity':[0,2],'postgres_effective_affinity':[4,6],'normalized_effective_configuration_equal':True,'platform_api_calls':0,'gate_executed':False,'database_writes':0,'external_calls':0,'spend_usd':'0'}
 out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);main(p.parse_args().run)
