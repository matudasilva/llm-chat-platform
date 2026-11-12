"""Create a dedicated disposable campaign PG clone; no application/provider I/O."""
import hashlib,json,os,secrets,subprocess,tempfile,time,sys
from pathlib import Path
ROOT=Path.cwd(); ORQ=ROOT/'.framework/orqs/ORQ-41-production-retrieval-graduation'; HERE=Path(__file__).resolve().parent
PG='orq41-paid-pg';NET='orq41-paid-internal';DB='orq41_paid';VOLUME='orq41-paid-pg-data'
def docker(*args,data=None):
 r=subprocess.run(['docker','--host','unix:///var/run/docker.sock',*args],input=data,capture_output=True,timeout=120)
 if r.returncode: raise RuntimeError('Local Docker operation failed: '+args[0]+'; no automatic rerun')
 return r.stdout
def sql(query): return docker('exec','-i',PG,'psql','-X','-q','-At','-v','ON_ERROR_STOP=1','-U','orq41owner','-d',DB,data=query.encode()).decode()
def quote(s): return "'"+s.replace("'","''")+"'"
assert not (HERE/'database.json').exists(),'Refuse overwriting campaign DB receipt'
resume = sys.argv[1:] == ['--resume-empty']
if not resume:
 assert not docker('ps','-a','--filter','name=^/'+PG+'$','--format','{{.ID}}').strip(),'Existing target; inspect rather than reset'
 assert not docker('network','ls','--filter','name=^'+NET+'$','--format','{{.ID}}').strip()
 assert not docker('volume','ls','--filter','name=^'+VOLUME+'$','--format','{{.Name}}').strip()
else:
 assert sql("SELECT rolname FROM pg_roles WHERE rolname NOT LIKE 'pg_%' ORDER BY rolname").strip() == 'orq41owner'
 assert sql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").strip() == '0'
manifest=json.loads((ORQ/'environment/g9/runs/261105143941/manifest.json').read_text()); image=manifest['images']['postgres']
meta=json.loads((ORQ/'corpus-snapshot/corpus-snapshot.json').read_text());dump=ORQ/'corpus-snapshot/orq37-t23-corpus.pgdump'
assert hashlib.sha256(dump.read_bytes()).hexdigest()==meta['artifact']['sha256']
if resume:
 private=Path(json.loads((HERE/'database-preparation.json').read_text())['private_state'])
 passwords=json.loads((private/'local-credentials.json').read_text());env=private/'postgres.env'
else:
 private=Path(tempfile.mkdtemp(prefix='orq41-paid-db-'));private.chmod(0o700)
 passwords={key:secrets.token_urlsafe(32) for key in ('POSTGRES_PASSWORD','POSTGRES_APP_PASSWORD','POSTGRES_OPS_PASSWORD')}
 (private/'local-credentials.json').write_text(json.dumps(passwords));(private/'local-credentials.json').chmod(0o600)
 env=private/'postgres.env';env.write_text('POSTGRES_USER=orq41owner\nPOSTGRES_DB='+DB+'\nPOSTGRES_PASSWORD='+passwords['POSTGRES_PASSWORD']+'\n');env.chmod(0o600)
roles=docker('exec','orq41-env-pg','pg_dumpall','-U','orq41owner','--roles-only','--no-role-passwords')
roles=b'\n'.join(line for line in roles.splitlines() if line.strip()!=b'CREATE ROLE orq41owner;')
ddl=docker('exec','orq41-env-pg','pg_dump','-U','orq41owner','-d','orq41','--schema-only')
if not resume:
 docker('network','create','--internal',NET);docker('volume','create',VOLUME)
 docker('create','--pull=never','--name',PG,'--network',NET,'--memory=2147483648','--memory-swap=2147483648','--cpus=2','--env-file',str(env),'--mount',f'type=volume,src={VOLUME},dst=/var/lib/postgresql/data',image)
 docker('start',PG)
for _ in range(50):
 ready=subprocess.run(['docker','exec',PG,'pg_isready','-U','orq41owner','-d',DB],capture_output=True)
 if ready.returncode==0 and docker('exec',PG,'cat','/proc/1/comm').strip()==b'postgres': break
 time.sleep(.2)
else: raise RuntimeError('PostgreSQL startup timeout')
docker('exec','-i',PG,'psql','-X','-v','ON_ERROR_STOP=1','-U','orq41owner','-d',DB,data=roles)
for role,key in [('orq41owner','POSTGRES_PASSWORD'),('rag_app','POSTGRES_APP_PASSWORD'),('chat_ops','POSTGRES_OPS_PASSWORD')]: sql('ALTER ROLE '+role+' PASSWORD '+quote(passwords[key])+';')
docker('exec','-i',PG,'psql','-X','-v','ON_ERROR_STOP=1','--single-transaction','-U','orq41owner','-d',DB,data=ddl)
sql("INSERT INTO alembic_version VALUES ('e4b7f21c9a06')")
docker('exec','-i',PG,'pg_restore','-U','orq41owner','-d',DB,'--data-only','--single-transaction',data=dump.read_bytes())
assert sql('SELECT (SELECT count(*) FROM conversations),(SELECT count(*) FROM messages)').strip()=='0|0'
fixtures=json.loads((HERE/'fixtures.prospective.json').read_text());statements=['BEGIN;']
for row in fixtures['conversations']:
 statements.append('INSERT INTO conversations(id,tenant_id) VALUES ('+quote(row['conversation_id'])+'::uuid,'+quote(row['tenant_id'])+');')
 for msg in row['messages']:
  statements.append('INSERT INTO messages(id,conversation_id,tenant_id,role,content) VALUES (gen_random_uuid(),'+quote(row['conversation_id'])+'::uuid,'+quote(row['tenant_id'])+','+quote(msg['role'])+','+quote(msg['content'])+');')
statements.append('COMMIT;');sql('\n'.join(statements))
assert sql('SELECT (SELECT count(*) FROM conversations),(SELECT count(*) FROM messages)').strip()=='168|3840'
docs=sql("SELECT source_path,content_hash FROM documents WHERE tenant_id='orq37-t23' ORDER BY source_path,content_hash").strip().splitlines()
fingerprint=hashlib.sha256('\n'.join(row.replace('|',':',1) for row in sorted(docs)).encode()).hexdigest();assert fingerprint==meta['identity']['content_fingerprint']
projection=sql('COPY ('+meta['identity']['snapshot_content_projection'].split('  (psql')[0]+') TO STDOUT');assert hashlib.sha256(projection.encode()).hexdigest()==meta['identity']['snapshot_content_sha256']
for tenant in {r['tenant_id'] for r in fixtures['conversations']}:
 expected=2146 if tenant=='orq37-t23' else 0
 assert sql('SET ROLE rag_app; SET app.tenant_id='+quote(tenant)+'; SELECT count(*) FROM chunks; RESET ROLE;').strip()==str(expected)
info=json.loads(docker('inspect',PG))[0];assert info['Image']==image and not info['HostConfig'].get('PortBindings')
network=json.loads(docker('network','inspect',NET))[0];assert network['Internal'] is True
receipt={'status':'PAID_FIXTURES_SEEDED_LOCAL_VERIFICATION_PASS','container':PG,'container_id':info['Id'],'image':image,'network':NET,'network_internal':True,'published_ports':False,'database':DB,'volume':VOLUME,'private_state':str(private),'conversations':168,'messages':3840,'corpus_fingerprint':fingerprint,'corpus_content_sha256':hashlib.sha256(projection.encode()).hexdigest(),'schema_dump_sha256':hashlib.sha256(ddl).hexdigest(),'fixture_file_sha256':hashlib.sha256((HERE/'fixtures.prospective.json').read_bytes()).hexdigest(),'tenant_rls_counts_verified':True,'provider_calls':0,'paid_requests':0,'spend_usd':'0'}
(HERE/'database.json').write_text(json.dumps(receipt,indent=2)+'\n');print(receipt['status'])
