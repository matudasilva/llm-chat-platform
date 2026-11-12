"""Independent pre-execution DB/config proof. Parent executes approved P2 Docker.

Only READ ONLY SELECT/COPY and transaction-local role/tenant context. Config
containers import settings under network none, never app lifespan or API calls.
"""
import argparse,hashlib,json,subprocess,tempfile,uuid
from collections import defaultdict
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
def main(run):
 run=Path(run);plan=json.loads((run/'plan.json').read_text());prep=json.loads((run/'preparation.json').read_text());fixtures=json.loads((run/'fixtures.json').read_text());cases=json.loads((ORQ/'paid-execution/cases.json').read_text())['cases'];meta=json.loads((ORQ/'corpus-snapshot/corpus-snapshot.json').read_text());out=run/'execution-review/database-final-verification.json'
 assert not out.exists()
 assert prep['plan_sha256']==sha((run/'plan.json').read_bytes()) and prep['fixtures_sha256']==sha((run/'fixtures.json').read_bytes())
 assert plan['casefile_sha256']==sha((ORQ/'paid-execution/cases.json').read_bytes())
 for name,digest in {**plan['harness_sha256'],**plan['support_files_sha256']}.items():assert sha((ROOT/name).read_bytes())==digest,name
 assert len(plan['samples'])==len(fixtures)==20
 expected={}
 for fixture,sample in zip(fixtures,plan['samples']):
  assert fixture['sample']==sample
  cid=sample['conversation_id'];assert cid==str(uuid.uuid5(uuid.UUID(plan['namespace']),sample['sample_id']))
  assert sample['request_id']==str(uuid.uuid5(uuid.UUID(plan['namespace']),'request/'+sample['sample_id']))
  match=[c for c in cases if all(c[k]==sample[k] for k in ('language','category','tenant_id','message'))];assert len(match)==1
  assert match[0]['history']==fixture['messages']
  expected[cid]=fixture
 assert len(expected)==20
 pg=json.loads(docker('inspect',PG))[0];assert pg['Image']==plan['postgres_image'] and pg['HostConfig']['NetworkMode']=='none' and not pg['HostConfig'].get('PortBindings')
 query="SELECT json_build_object('conversations',(SELECT json_agg(x) FROM (SELECT id::text,tenant_id FROM conversations ORDER BY id) x),'messages',(SELECT json_agg(x) FROM (SELECT id::text,conversation_id::text,tenant_id,role::text,content,sequence FROM messages ORDER BY sequence) x));"
 receipts=[];schemas=[];business=[]
 for arm,db in plan['databases'].items():
  first=sql(db,query);data=json.loads(first);assert len(data['conversations'])==20 and len(data['messages'])==424
  assert {r['id']:r['tenant_id'] for r in data['conversations']}=={cid:f['sample']['tenant_id'] for cid,f in expected.items()}
  rows=defaultdict(list);ids=set();seqs=set();generated_ids=set()
  for r in data['messages']:
   assert str(uuid.UUID(r['id']))==r['id'] and r['id'] not in ids;ids.add(r['id'])
   assert type(r['sequence']) is int and r['sequence']>0 and r['sequence'] not in seqs;seqs.add(r['sequence'])
   assert r['conversation_id'] in expected and r['tenant_id']==expected[r['conversation_id']]['sample']['tenant_id'];rows[r['conversation_id']].append(r)
  for cid,f in expected.items():
   actual=rows[cid];history_count=len(f['messages']);assert len(actual)==history_count+2
   assert [{'role':r['role'],'content':r['content']} for r in actual[:history_count]]==f['messages']
   for i,r in enumerate(actual[:history_count]):assert r['id']==str(uuid.uuid5(uuid.UUID(plan['namespace']),f['sample']['sample_id']+'/history/'+str(i)))
   assert [{'role':r['role'],'content':r['content']} for r in actual[history_count:]]==[{'role':'user','content':f['sample']['message']},{'role':'assistant','content':'Controlled local response.'}]
   generated_ids.update(r['id'] for r in actual[history_count:])
  corpus=sql(db,'COPY ('+meta['identity']['snapshot_content_projection'].split('  (psql')[0]+') TO STDOUT;');assert sha(corpus.encode())==meta['identity']['snapshot_content_sha256']
  counts=sql(db,'SELECT (SELECT count(*) FROM documents),(SELECT count(*) FROM chunks);').strip();assert counts=='124|2146'
  rls={}
  for tenant in sorted({f['sample']['tenant_id'] for f in fixtures})+['','independent-unknown']:
   n=int(sql(db,'SET LOCAL ROLE rag_app; SET LOCAL app.tenant_id='+quote(tenant)+'; SELECT count(*) FROM chunks;').strip());assert n==(2146 if tenant=='orq37-t23' else 0);rls[tenant]=n
  ddl=normalized(docker('exec',PG,'pg_dump','-U','orq41owner','-d',db,'--schema-only'));schemas.append(ddl)
  assert sql(db,query)==first
  assert len(generated_ids)==40
  paired_data=dict(data,messages=[dict(r,id='<generated:'+r['role']+'>') if r['id'] in generated_ids else r for r in data['messages']])
  paired_sha=sha(json.dumps(paired_data,sort_keys=True,separators=(',',':')).encode())
  business.append(paired_sha);receipts.append({'arm':arm,'database':db,'conversations':20,'messages':424,'business_projection_sha256':sha(first.encode()),'normalized_business_projection_sha256':paired_sha,'normalized_generated_message_ids':40,'normalized_schema_sha256':sha(ddl),'corpus_content_sha256':sha(corpus.encode()),'rls':rls})
 assert schemas[0]==schemas[1] and business[0]==business[1]
 from experiments.production_graduation.gate_validation.g9_controller import env_for,P2_GUARD,private_write
 old=json.loads((ORQ/'environment/g9/runs/261105143941/execution.json').read_text());passwords=json.loads((Path(old['private_state'])/'local-credentials.json').read_text());private=Path(tempfile.mkdtemp(prefix='orq41-independent-g6-settings-'));private.chmod(0o700)
 code="""import json,hashlib
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
print(json.dumps({'full':config_identity(settings),'normalized':hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}))
"""
 configs={}
 for arm,db in plan['databases'].items():
  env=env_for('c1','C1',db,passwords);env.update(PYTHONPATH='/p2_netguard:/app',PATH='/usr/local/bin:/usr/bin:/bin');path=private/(arm+'.env');private_write(path,''.join(k+'='+v+'\n' for k,v in sorted(env.items())).encode())
  cfg=json.loads(docker('run','--rm','--pull=never','--network','none','--env-file',str(path),'--mount',f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly','--mount',f'type=bind,src={P2_GUARD},dst=/p2_netguard,readonly','--entrypoint','/usr/local/bin/python',plan['images'][arm],'-c',code).decode());assert cfg['full']==plan['config_sha256'][arm];configs[arm]=cfg
 assert configs['old']['normalized']==configs['new']['normalized'],'Effective configuration differs beyond database names'
 result={'status':'C1_COMPARISON_FINAL_DATABASES_READONLY_VERIFIER_PASS','verifier_author':'adapted prior independent read-only verifier; parent executed, distinct reviewer inspects source/receipt','executor':'parent approved P2 Docker access','plan_sha256':sha((run/'plan.json').read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes()),'arms':receipts,'configuration':configs,'normalized_effective_configuration_equal':True,'platform_api_calls':0,'gate_executed':False,'database_writes':0,'external_calls':0,'spend_usd':'0'}
 out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);main(p.parse_args().run)
