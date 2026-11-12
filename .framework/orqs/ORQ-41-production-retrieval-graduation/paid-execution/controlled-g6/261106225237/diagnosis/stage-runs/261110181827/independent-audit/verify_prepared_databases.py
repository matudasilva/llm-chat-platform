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
 from experiments.production_graduation.gate_validation import stage_latency as stage
 from experiments.production_graduation.gate_validation.blocked_latency_worker import _cache_namespace
 from experiments.production_graduation.gate_validation.local_api import NamespacedRedis
 stage.validate_plan(plan,fixtures,prepared=True);stage.hashes_match(plan)
 assert stage.source_review()==json.loads((run/'preparation.json').read_text())['source_review_sha256']
 assert plan['schema']=='orq41-stage-latency-v1' and plan['mode']=='stage_observer_on_off_full_c1' and plan['full_c1_both_arms'] is True
 assert plan['images']['c0']==plan['images']['c1'] and plan['concurrency']==plan['sample_attempts']==plan['repetitions']==1
 assert len(plan['samples'])==180 and len(plan['arm_cell_order'])==8
 assert plan['total_requests']==360 and plan['measured']==200 and plan['warmups']==160
 assert plan['diagnostic_modes']==dict(c0='off',c1='on') and 'symmetric_limit_percent' not in plan
 assert not(run/'execution-started.json').exists() and not list(run.glob('c?-*-started.json')) and not(run/'result.json').exists()
 assert [e['arm'] for e in plan['arm_cell_order']]==['c0','c1','c1','c0','c1','c0','c0','c1']
 cells=[]
 for cell in ('EN-json','EN-sse','ES-json','ES-sse'):
  lang,protocol=cell.split('-');rows=[s for s in plan['samples'] if s['language']==lang and s['protocol']==protocol]
  assert len(rows)==45 and [s['warmup'] for s in rows]==[True]*20+[False]*25 and all(s['block']==0 for s in rows)
  expected_cases=[c['case_id'] for c in cases if c['language']==lang]
  assert Counter(s['case_id'] for s in rows[:20])==dict.fromkeys(expected_cases,1)
  assert Counter(s['category'] for s in rows[20:])==dict(document=7,history=6,combined=6,empty=6)
  cells.append(dict(cell=cell,warmups_per_mode=20,measured_per_mode=25,all_original_business_cases_warmed=True))
 names=[NamespacedRedis(None,_cache_namespace(plan,e)).namespace for e in plan['arm_cell_order']];assert len(set(names))==8
 old_requests=set();old_conversations=set();histories=0
 for file in(ORQ/'paid-execution').rglob('plan.json'):
  if file.resolve()==(run/'plan.json').resolve():continue
  samples=json.loads(file.read_text()).get('samples',[])
  if not isinstance(samples,list):continue
  histories+=1
  for row in samples:
   if isinstance(row,dict):
    old_requests.add(row.get('request_id'));old_conversations.add(row.get('conversation_id'))
 assert not old_requests & {s['request_id'] for s in plan['samples']}
 assert not old_conversations & {s['conversation_id'] for s in plan['samples']}
 return dict(cells=cells,total_future_requests=360,total_measured=200,total_warmups=160,historical_manifests_checked=histories,all180request_and_conversation_UUIDs_fresh=True,actual_cache_namespace_constructor_passes=8,source_review_sha256=stage.source_review(),application_requests=0)
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
 assert len(plan['samples'])==len(fixtures)==180
 expected={}
 for fixture,sample in zip(fixtures,plan['samples']):
  assert fixture['sample']==sample
  cid=sample['conversation_id'];assert cid==str(uuid.uuid5(uuid.UUID(plan['namespace']),sample['sample_id']))
  assert sample['request_id']==str(uuid.uuid5(uuid.UUID(plan['namespace']),'request/'+sample['sample_id']))
  match=[c for c in cases if all(c[k]==sample[k] for k in ('language','category','tenant_id','message'))];assert len(match)==1
  assert match[0]['history']==fixture['messages'] and match[0]['case_id']==sample['case_id']
  expected[cid]=fixture
 assert len(expected)==180
 pg=json.loads(docker('inspect',PG))[0];assert pg['Image']==plan['postgres_image'] and pg['HostConfig']['NetworkMode']=='none' and not pg['HostConfig'].get('PortBindings')
 query="SELECT json_build_object('conversations',(SELECT json_agg(x) FROM (SELECT id::text,tenant_id FROM conversations ORDER BY id) x),'messages',(SELECT json_agg(x) FROM (SELECT id::text,conversation_id::text,tenant_id,role::text,content,sequence FROM messages ORDER BY sequence) x));"
 receipts=[];schemas=[];business=[]
 for arm,db in plan['databases'].items():
  first=sql(db,query);data=json.loads(first);assert len(data['conversations'])==180 and len(data['messages'])==4224
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
  business.append(sha(first.encode()));receipts.append({'arm':arm,'database':db,'conversations':180,'messages':4224,'business_projection_sha256':sha(first.encode()),'normalized_schema_sha256':sha(ddl),'corpus_content_sha256':sha(corpus.encode()),'rls':rls})
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
 result={'status':'STAGE_DIAGNOSTIC_PREPARED_DATABASES_READONLY_VERIFIER_PASS','verifier_author':'adapted previous independent verifier; current parent execution, not distinct SQL attestation','executor':'parent approved P2 Docker access','plan_sha256':sha((run/'plan.json').read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes()),'arms':receipts,'configuration':configs,'constraint_and_locale_proof':checks,'protocol_proof':protocol,'preparation_proof':preparation,'worker_effective_affinity':[0,2],'postgres_effective_affinity':[4,6],'normalized_effective_configuration_equal':True,'platform_api_calls':0,'gate_executed':False,'database_writes':0,'external_calls':0,'spend_usd':'0'}
 out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);main(p.parse_args().run)
