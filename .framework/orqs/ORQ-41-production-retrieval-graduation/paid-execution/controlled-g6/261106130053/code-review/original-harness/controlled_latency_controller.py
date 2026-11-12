"""Prepare/freeze and separately execute the local controlled G6 timing contract."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4,uuid5

from .controlled_latency import build_samples,summarize
from .g9_controller import ROOT,ORQ,P2_GUARD,env_for,private_write,sha_file

PG='orq41-env-pg'
MODULES=('controlled_latency.py','controlled_latency_worker.py','controlled_latency_controller.py',
         'local_api.py','transports.py','capture.py','fixtures.py','validate_g123.py','g9_controller.py')

def docker(*args,data=None):
    p=subprocess.run(['docker','--host','unix:///var/run/docker.sock',*args],input=data,capture_output=True,timeout=240)
    if p.returncode: raise RuntimeError('Local controlled Docker failure: '+args[0])
    return p.stdout

def sql(database,query):
    return docker('exec','-i',PG,'psql','-X','-q','-At','-v','ON_ERROR_STOP=1','-U','orq41owner','-d',database,data=query.encode()).decode()

def quote(value): return "'"+value.replace("'","''")+"'"

def business_hash(database):
    query="""COPY (SELECT json_build_object(
      'conversations',(SELECT json_agg(x) FROM (SELECT id,tenant_id FROM conversations ORDER BY id) x),
      'messages',(SELECT json_agg(x) FROM (SELECT id,conversation_id,tenant_id,role,content,sequence FROM messages ORDER BY sequence) x))) TO STDOUT"""
    return hashlib.sha256(sql(database,query).encode()).hexdigest()

def schema_hash(database):
    raw=docker('exec',PG,'pg_dump','-U','orq41owner','-d',database,'--schema-only')
    return hashlib.sha256(b'\n'.join(line.strip() for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith((b'--',b'\\restrict ',b'\\unrestrict ')))).hexdigest()

def prepare():
    run_id=datetime.now(timezone.utc).strftime('%y%m%d%H%M%S')
    directory=ORQ/'paid-execution/controlled-g6'/run_id;directory.mkdir(parents=True,mode=0o700,exist_ok=False)
    namespace=uuid4()
    casefile=ORQ/'paid-execution/cases.json';cases=json.loads(casefile.read_text())['cases']
    source=json.loads((ORQ/'environment/g9/runs/261105143941/manifest.json').read_text())
    info=json.loads(docker('inspect',PG))[0]
    if info['HostConfig']['NetworkMode']!='none' or info['HostConfig'].get('PortBindings'): raise ValueError('P2 PostgreSQL topology changed')
    assert info['Image']==source['images']['postgres']
    assert info['HostConfig']['NanoCpus']==2_000_000_000 and info['HostConfig']['Memory']==info['HostConfig']['MemorySwap']==2_147_483_648
    samples,fixtures,order=build_samples(cases,namespace)
    plan={'schema':'orq41-controlled-g6-v1','run_id':run_id,'namespace':str(namespace),'warmups_per_cell_arm':5,'n_per_cell_arm':100,
          'boundary':'ASGI request ingress to entry of memory-only native SDK HTTP send for primary serialized payload; before capture.sent bookkeeping',
          'relative_p95_limit_percent':5,'sample_attempts':1,'arm_cell_order':order,'samples':samples,
          'images':{'c0':source['images']['baseline'],'c1':source['images']['candidate']},'postgres_image':source['images']['postgres'],
          'resources':{'nano_cpus':2_000_000_000,'memory_bytes':2_147_483_648,'memory_swap_bytes':2_147_483_648},
          'databases':{arm:'orq41_g6_'+run_id+'_'+arm for arm in ('c0','c1')},
          'casefile_sha256':sha_file(casefile),'harness_sha256':{str(Path('experiments/production_graduation/gate_validation')/name):sha_file(ROOT/'experiments/production_graduation/gate_validation'/name) for name in MODULES},
          'external_calls':0,'paid_requests':0,'g6_live_bounds_claimed':False,'limitation':'R=1; fixed balanced cell arm order, no best-run selection; host jitter remains a limitation'}
    prior=json.loads((ORQ/'environment/g9/runs/261105143941/execution.json').read_text())
    passwords=json.loads((Path(prior['private_state'])/'local-credentials.json').read_text())
    private=Path(tempfile.mkdtemp(prefix='orq41-g6-config-'));private.chmod(0o700)
    plan['config_sha256']={}
    for arm in ('c0','c1'):
        values=env_for(arm,'C1',plan['databases'][arm],passwords)
        values.update(PYTHONPATH='/p2_netguard:/app',PATH='/usr/local/bin:/usr/bin:/bin')
        env=private/(arm+'.env');private_write(env,''.join(f'{k}={v}\n' for k,v in sorted(values.items())).encode())
        code='from experiments.production_graduation.gate_validation.validate_g123 import check_p2,config_identity; check_p2(); from app.core.settings import settings; print(config_identity(settings))'
        output=docker('run','--rm','--pull=never','--network','none','--env-file',str(env),
            '--mount',f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
            '--mount',f'type=bind,src={P2_GUARD},dst=/p2_netguard,readonly','--entrypoint','/usr/local/bin/python',plan['images'][arm],'-c',code).decode().strip()
        assert len(output)==64;plan['config_sha256'][arm]=output
    plan['support_files_sha256']={str((ORQ/'environment/g123/execution-freeze/settings/inspect.py').relative_to(ROOT)):sha_file(ORQ/'environment/g123/execution-freeze/settings/inspect.py'),
                                  str((P2_GUARD/'sitecustomize.py').relative_to(ROOT)):sha_file(P2_GUARD/'sitecustomize.py')}
    private_write(directory/'plan.json',json.dumps(plan,indent=2).encode())
    private_write(directory/'fixtures.json',json.dumps(fixtures,indent=2).encode())
    ddl=docker('exec',PG,'pg_dump','-U','orq41owner','-d','orq41','--schema-only')
    dump=ORQ/'corpus-snapshot/orq37-t23-corpus.pgdump';meta=json.loads((ORQ/'corpus-snapshot/corpus-snapshot.json').read_text())
    assert sha_file(dump)==meta['artifact']['sha256']
    receipts=[]
    for arm,database in plan['databases'].items():
        assert not sql('postgres',"SELECT datname FROM pg_database WHERE datname="+quote(database)).strip()
        sql('postgres','CREATE DATABASE '+database+' OWNER orq41owner TEMPLATE template0')
        docker('exec','-i',PG,'psql','-X','-v','ON_ERROR_STOP=1','--single-transaction','-U','orq41owner','-d',database,data=ddl)
        sql(database,"INSERT INTO alembic_version VALUES ('e4b7f21c9a06')")
        docker('exec','-i',PG,'pg_restore','-U','orq41owner','-d',database,'--data-only','--single-transaction',data=dump.read_bytes())
        statements=['BEGIN;']
        for fixture in fixtures:
            sample=fixture['sample'];cid=sample['conversation_id'];tenant=sample['tenant_id']
            statements.append('INSERT INTO conversations(id,tenant_id) VALUES ('+quote(cid)+'::uuid,'+quote(tenant)+');')
            for i,message in enumerate(fixture['messages']):
                mid=str(uuid5(namespace,sample['sample_id']+'/history/'+str(i)))
                statements.append('INSERT INTO messages(id,conversation_id,tenant_id,role,content) VALUES ('+quote(mid)+'::uuid,'+quote(cid)+'::uuid,'+quote(tenant)+','+quote(message['role'])+','+quote(message['content'])+');')
        statements.append('COMMIT;');sql(database,'\n'.join(statements))
        content=sql(database,'COPY ('+meta['identity']['snapshot_content_projection'].split('  (psql')[0]+') TO STDOUT')
        assert hashlib.sha256(content.encode()).hexdigest()==meta['identity']['snapshot_content_sha256']
        counts=sql(database,'SELECT (SELECT count(*) FROM conversations),(SELECT count(*) FROM messages)').strip()
        expected_messages=sum(len(f['messages']) for f in fixtures)
        assert counts==f'{len(samples)}|{expected_messages}'
        receipts.append({'arm':arm,'database':database,'counts':counts,'corpus_content_sha256':hashlib.sha256(content.encode()).hexdigest(),
                         'business_sha256':business_hash(database),'schema_sha256':schema_hash(database)})
    private_write(directory/'preparation.json',json.dumps({'status':'CONTROLLED_G6_PREPARED_NOT_EXECUTED','plan_sha256':sha_file(directory/'plan.json'),'fixtures_sha256':sha_file(directory/'fixtures.json'),'databases':receipts,'provider_calls':0},indent=2).encode())
    print(str(directory.relative_to(ROOT)))

def execute(directory):
    directory=Path(directory).resolve();plan=json.loads((directory/'plan.json').read_text())
    review=json.loads((directory/'independent-review.json').read_text())
    assert review['status']=='CONTROLLED_G6_HARNESS_INDEPENDENT_REVIEW_PASS'
    assert review['plan_sha256']==sha_file(directory/'plan.json')
    for name,digest in plan['harness_sha256'].items(): assert sha_file(ROOT/name)==digest
    for name,digest in plan['support_files_sha256'].items(): assert sha_file(ROOT/name)==digest
    preparation=json.loads((directory/'preparation.json').read_text())
    assert preparation['plan_sha256']==sha_file(directory/'plan.json') and preparation['fixtures_sha256']==sha_file(directory/'fixtures.json')
    for db in preparation['databases']:
        assert business_hash(db['database'])==db['business_sha256'] and schema_hash(db['database'])==db['schema_sha256']
    assert not (directory/'result.json').exists(),'No rerun or best-run selection'
    source=json.loads((ORQ/'environment/g9/runs/261105143941/execution.json').read_text())
    passwords=json.loads((Path(source['private_state'])/'local-credentials.json').read_text())
    private=Path(tempfile.mkdtemp(prefix='orq41-controlled-g6-'));private.chmod(0o700)
    arms={'c0':[],'c1':[]}
    for cell in plan['arm_cell_order']:
        arm=cell['arm'];name='orq41-g6-'+plan['run_id']+'-'+arm+'-'+cell['cell'].lower()
        output=directory/(arm+'-'+cell['cell']+'.json');assert not output.exists()
        values=env_for(arm,'C1',plan['databases'][arm],passwords)
        values.update(PYTHONPATH='/p2_netguard:/app',PATH='/usr/local/bin:/usr/bin:/bin',G6_RUN_DIR='/g6run',G6_ARM=arm,G6_CELL=cell['cell'],P2_NET_AUDIT_LOG='/g6run/network-audit.log')
        env=private/(name+'.env');private_write(env,''.join(f'{k}={v}\n' for k,v in sorted(values.items())).encode())
        docker('create','--pull=never','--name',name,'--network','container:'+PG,'--user=1000:1000','--cpus=2','--memory=2147483648','--memory-swap=2147483648','--env-file',str(env),
               '--mount',f'type=bind,src={directory},dst=/g6run','--mount',f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
               '--mount',f'type=bind,src={P2_GUARD},dst=/p2_netguard,readonly','--entrypoint','/usr/local/bin/python',plan['images'][arm],'-m','experiments.production_graduation.gate_validation.controlled_latency_worker')
        info=json.loads(docker('inspect',name))[0]
        assert info['Image']==plan['images'][arm] and not info['HostConfig'].get('PortBindings')
        assert info['HostConfig']['Memory']==info['HostConfig']['MemorySwap']==2_147_483_648 and info['HostConfig']['NanoCpus']==2_000_000_000
        docker('start',name);exit_code=docker('wait',name).strip()
        if exit_code!=b'0': raise RuntimeError('Controlled worker failed; preserve container and never auto-resend')
        result=json.loads(output.read_text());assert result['config_identity']==plan['config_sha256'][arm]
        expected=[s for s in plan['samples'] if s['language']+'-'+s['protocol']==cell['cell']]
        assert len(result['samples'])<=len(expected)
        for observed,sample in zip(result['samples'],expected):
            assert all(observed[key]==sample[key] for key in ('sample_id','language','protocol','warmup','category','request_id','conversation_id'))
            if observed['status']=='PASS':
                assert type(observed['start_ns']) is int and type(observed['primary_dispatch_ns']) is int
                assert observed['primary_dispatch_ns']>=observed['start_ns']>=0
                assert observed['preparation_ns']==observed['primary_dispatch_ns']-observed['start_ns']
        arms[arm].extend(result['samples'])
    audit=directory/'network-audit.log';assert not audit.exists() or not audit.read_text()
    result=summarize(arms);result.update(plan_sha256=sha_file(directory/'plan.json'),worker_receipts={p.name:sha_file(p) for p in directory.glob('c?-*.json')})
    private_write(directory/'result.json',json.dumps(result,indent=2).encode());print(result['status'])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',type=Path);args=parser.parse_args()
    execute(args.execute) if args.execute else prepare()
