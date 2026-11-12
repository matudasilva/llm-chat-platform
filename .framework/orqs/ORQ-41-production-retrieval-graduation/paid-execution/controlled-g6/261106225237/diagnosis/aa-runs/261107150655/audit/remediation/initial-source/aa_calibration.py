"""Fixed-affinity same-image A/A calibration. Never an official G6 run."""
import argparse
import hashlib
import json
import os
import secrets
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4, uuid5

from .aa_calibration_resources import API_CPUS, PG_CPUS, cpu_list, cpu_stat, topology, summarize_aa, resource_delta, canonical_schema
from .controlled_latency import build_samples
from .controlled_latency_controller import MODULES, OPTIMIZED_C1_PIN, docker, quote, resolve_candidate_image
from .g9_controller import ROOT, ORQ, P2_GUARD, env_for, private_write, sha_file

SOURCE_PG = 'orq41-env-pg'
COLLECTOR_CONFIG = ORQ/'environment/g8/collector.yaml'
OWN_MODULES = ('aa_calibration.py', 'aa_calibration_worker.py', 'aa_calibration_resources.py')


class Database:
    def __init__(self, container):
        self.container = container

    def sql(self, database, query):
        return docker('exec','-i',self.container,'psql','-X','-q','-At','-v','ON_ERROR_STOP=1',
            '-U','orq41owner','-d',database,data=query.encode()).decode()

    def schema(self, database):
        return docker('exec',self.container,'pg_dump','-U','orq41owner','-d',database,'--schema-only')

    def schema_hash(self, database):
        return hashlib.sha256(canonical_schema(self.schema(database))).hexdigest()

    def business_hash(self, database):
        query="""COPY (SELECT json_build_object(
          'conversations',(SELECT json_agg(x) FROM (SELECT id,tenant_id FROM conversations ORDER BY id) x),
          'messages',(SELECT json_agg(x) FROM (SELECT id,conversation_id,tenant_id,role,content,sequence FROM messages ORDER BY sequence) x))) TO STDOUT"""
        return hashlib.sha256(self.sql(database,query).encode()).hexdigest()


def pg_resources(name):
    def read(path):
        return docker('exec',name,'cat',path).decode().strip()
    affinity=next(line.split(':',1)[1].strip() for line in read('/proc/self/status').splitlines() if line.startswith('Cpus_allowed_list:'))
    result=dict(affinity=sorted(cpu_list(affinity)),effective_cpuset=sorted(cpu_list(read('/sys/fs/cgroup/cpuset.cpus.effective'))),
        cpu_max=read('/sys/fs/cgroup/cpu.max'),cpu_stat=cpu_stat(read('/sys/fs/cgroup/cpu.stat')),topology=topology())
    if result['affinity']!=list(PG_CPUS) or result['effective_cpuset']!=list(PG_CPUS) or result['cpu_max']!='200000 100000':
        raise ValueError('Effective PostgreSQL resource drift')
    return result


def inspect_environment(plan):
    pg=json.loads(docker('inspect',plan['containers']['postgres']))[0]
    h=pg['HostConfig']
    assert pg['State']['Running'] and pg['Image']==plan['postgres_image']
    assert h['NetworkMode']=='none' and not h.get('PortBindings')
    assert cpu_list(h['CpusetCpus'])==set(PG_CPUS) and h['NanoCpus']==2_000_000_000
    assert h['Memory']==h['MemorySwap']==2_147_483_648
    for service in ('redis','collector'):
        info=json.loads(docker('inspect',plan['containers'][service]))[0]
        assert info['State']['Running'] and info['Image']==plan['auxiliary_images'][service]
        assert info['HostConfig']['NetworkMode']=='container:'+pg['Id'] and not info['HostConfig'].get('PortBindings')
        assert info['HostConfig']['NanoCpus']==500_000_000
        assert info['HostConfig']['Memory']==info['HostConfig']['MemorySwap']==268_435_456
    assert topology()==plan['cpu_topology']
    return pg_resources(plan['containers']['postgres'])


def provision(plan, private, passwords):
    # Fresh credentials/roles/data live only in this disposable local cluster.
    values={**passwords,'POSTGRES_USER':'orq41owner','POSTGRES_DB':'orq41aa_bootstrap'}
    env=private/'postgres.env'
    private_write(env,''.join(f'{k}={v}\n' for k,v in sorted(values.items())).encode())
    for name in plan['containers'].values():
        assert not docker('ps','-a','--filter',f'name=^/{name}$','--format','{{.ID}}').strip(),'Container collision'
    pg=plan['containers']['postgres']
    docker('create','--pull=never','--name',pg,'--network','none','--cpus=2','--cpuset-cpus','4,6',
        '--memory=2147483648','--memory-swap=2147483648','--env-file',str(env),
        '--mount',f'type=bind,src={ROOT/"scripts/postgres-init"},dst=/docker-entrypoint-initdb.d,readonly',plan['postgres_image'])
    docker('start',pg)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            docker('exec',pg,'sh','-c','test "$(cat /proc/1/comm)" = postgres && pg_isready -h 127.0.0.1 -U orq41owner -d orq41aa_bootstrap')
            break
        except RuntimeError:
            time.sleep(.25)
    else:
        raise RuntimeError('Dedicated PostgreSQL readiness timeout; preserve partial environment')
    docker('run','-d','--pull=never','--name',plan['containers']['redis'],'--network','container:'+pg,
        '--cpus=0.5','--memory=268435456','--memory-swap=268435456',plan['auxiliary_images']['redis'],
        'redis-server','--bind','127.0.0.1','--save','','--appendonly','no')
    docker('run','-d','--pull=never','--name',plan['containers']['collector'],'--network','container:'+pg,
        '--cpus=0.5','--memory=268435456','--memory-swap=268435456',
        '--mount',f'type=bind,src={COLLECTOR_CONFIG},dst=/etc/otelcol/config.yaml,readonly',
        plan['auxiliary_images']['collector'],'--config=/etc/otelcol/config.yaml')


def prepare():
    stamp=datetime.now(timezone.utc).strftime('%y%m%d%H%M%S')
    out=ORQ/'paid-execution/controlled-g6/261106225237/diagnosis/aa-runs'/stamp
    out.mkdir(parents=True,mode=0o700,exist_ok=False)
    private=Path(tempfile.mkdtemp(prefix='orq41-aa-'+stamp+'-'));private.chmod(0o700)
    passwords={key:secrets.token_hex(24) for key in ('POSTGRES_PASSWORD','POSTGRES_APP_PASSWORD',
        'POSTGRES_EVALUATION_PASSWORD','POSTGRES_OPS_PASSWORD','POSTGRES_OPS_RETENTION_PASSWORD')}
    private_write(private/'local-credentials.json',json.dumps(passwords).encode())
    source=json.loads((ORQ/'environment/g9/runs/261105143941/manifest.json').read_text())
    environment=json.loads((ORQ/'environment/manifest.json').read_text())
    image=resolve_candidate_image(source,json.loads(OPTIMIZED_C1_PIN.read_text())['image_id'])
    namespace=uuid4();casefile=ORQ/'paid-execution/cases.json'
    samples,fixtures,order=build_samples(json.loads(casefile.read_text())['cases'],namespace)
    assert set((*API_CPUS,*PG_CPUS))<=os.sched_getaffinity(0)
    plan=dict(schema='orq41-aa-calibration-v1',not_a_gate=True,run_id=stamp,namespace=str(namespace),
        warmups_per_cell_arm=5,n_per_cell_arm=100,request_deadline_s=300,sample_attempts=1,
        symmetric_limit_percent=5,full_c1_both_arms=True,
        boundary='ASGI ingress to primary native send entry; before capture bookkeeping',
        arm_cell_order=order,samples=samples,images={'c0':image,'c1':image},
        postgres_image=source['images']['postgres'],auxiliary_images={k:environment['images'][k] for k in ('redis','collector')},
        containers={k:'orq41-aa-'+stamp+'-'+k for k in ('postgres','redis','collector')},
        databases={arm:'orq41_aa_'+stamp+'_'+arm for arm in ('c0','c1')},cpu_topology=topology(),
        resources=dict(api_cpus=list(API_CPUS),postgres_cpus=list(PG_CPUS),nano_cpus=2_000_000_000,memory_bytes=2_147_483_648),
        casefile_sha256=sha_file(casefile),
        harness_sha256={str(Path('experiments/production_graduation/gate_validation')/n):sha_file(ROOT/'experiments/production_graduation/gate_validation'/n) for n in (*MODULES,*OWN_MODULES)},
        support_files_sha256={str(p.relative_to(ROOT)):sha_file(p) for p in (OPTIMIZED_C1_PIN,COLLECTOR_CONFIG,P2_GUARD/'sitecustomize.py',ORQ/'environment/g123/execution-freeze/settings/inspect.py',*sorted((ROOT/'scripts/postgres-init').glob('*.sh')))},
        external_calls=0,paid_requests=0,official_g6_status='CONTROLLED_G6_FAIL',
        limitation='R=1 calibration only; affinity is not exclusive CPU ownership or fixed clock frequency')
    plan['source_schema_sha256']=Database(SOURCE_PG).schema_hash('orq41')
    locale=json.loads(Database(SOURCE_PG).sql('orq41',"SELECT json_build_object('encoding',pg_encoding_to_char(encoding),'collate',datcollate,'ctype',datctype,'provider',datlocprovider,'icu_locale',daticulocale) FROM pg_database WHERE datname=current_database();"))
    assert locale['provider']=='c' and locale['icu_locale'] is None,'Unexpected source locale provider'
    plan['database_locale']=locale
    for image_id in set([image,plan['postgres_image'],*plan['auxiliary_images'].values()]):
        assert json.loads(docker('image','inspect',image_id))[0]['Id']==image_id
    private_write(out/'allocation.json',json.dumps(dict(containers=plan['containers'],images=plan['images'],
        postgres_image=plan['postgres_image'],auxiliary_images=plan['auxiliary_images'],
        private_state=str(private),resources=plan['resources'],api_requests=0),indent=2).encode())
    provision(plan,private,passwords)
    resources=inspect_environment(plan)
    db=Database(plan['containers']['postgres'])
    ddl=Database(SOURCE_PG).schema('orq41')
    dump=ORQ/'corpus-snapshot/orq37-t23-corpus.pgdump';meta=json.loads((dump.parent/'corpus-snapshot.json').read_text())
    assert sha_file(dump)==meta['artifact']['sha256']
    receipts=[];probes={};plan['config_sha256']={}
    for arm,database in plan['databases'].items():
        assert not db.sql('postgres','SELECT datname FROM pg_database WHERE datname='+quote(database)).strip()
        db.sql('postgres','CREATE DATABASE '+database+' OWNER orq41owner TEMPLATE template0 ENCODING '+quote(locale['encoding'])+' LC_COLLATE '+quote(locale['collate'])+' LC_CTYPE '+quote(locale['ctype'])+' LOCALE_PROVIDER libc')
        docker('exec','-i',db.container,'psql','-X','-v','ON_ERROR_STOP=1','--single-transaction','-U','orq41owner','-d',database,data=ddl)
        db.sql(database,"INSERT INTO alembic_version VALUES ('e4b7f21c9a06')")
        docker('exec','-i',db.container,'pg_restore','-U','orq41owner','-d',database,'--data-only','--single-transaction',data=dump.read_bytes())
        statements=['BEGIN;']
        for fixture in fixtures:
            sample=fixture['sample'];cid=sample['conversation_id'];tenant=sample['tenant_id']
            statements.append('INSERT INTO conversations(id,tenant_id) VALUES ('+quote(cid)+'::uuid,'+quote(tenant)+');')
            for i,message in enumerate(fixture['messages']):
                mid=str(uuid5(namespace,sample['sample_id']+'/history/'+str(i)))
                statements.append('INSERT INTO messages(id,conversation_id,tenant_id,role,content) VALUES ('+quote(mid)+'::uuid,'+quote(cid)+'::uuid,'+quote(tenant)+','+quote(message['role'])+','+quote(message['content'])+');')
        statements.append('COMMIT;');db.sql(database,'\n'.join(statements))
        corpus=db.sql(database,'COPY ('+meta['identity']['snapshot_content_projection'].split('  (psql')[0]+') TO STDOUT')
        assert hashlib.sha256(corpus.encode()).hexdigest()==meta['identity']['snapshot_content_sha256']
        assert db.sql(database,'SELECT (SELECT count(*) FROM conversations),(SELECT count(*) FROM messages)').strip()=='420|9600'
        receipts.append(dict(arm=arm,database=database,counts='420|9600',business_sha256=db.business_hash(database),schema_sha256=db.schema_hash(database),corpus_content_sha256=hashlib.sha256(corpus.encode()).hexdigest()))
        assert receipts[-1]['schema_sha256']==plan['source_schema_sha256']
        values=env_for(arm,'C1',database,passwords);values.update(PYTHONPATH='/p2_netguard:/app',PATH='/usr/local/bin:/usr/bin:/bin')
        env=private/(arm+'.env');private_write(env,''.join(f'{k}={v}\n' for k,v in sorted(values.items())).encode())
        code='import json;from experiments.production_graduation.gate_validation.validate_g123 import check_p2,check_config,config_identity;from experiments.production_graduation.gate_validation.aa_calibration_resources import worker_resources;check_p2();from app.core.settings import settings;check_config(settings);print(json.dumps(dict(config=config_identity(settings),resources=worker_resources())))'
        value=docker('run','--rm','--pull=never','--network','none','--env-file',str(env),
            '--cpus=2','--cpuset-cpus','0,2','--memory=2147483648','--memory-swap=2147483648',
            '--mount',f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
            '--mount',f'type=bind,src={P2_GUARD},dst=/p2_netguard,readonly','--entrypoint','/usr/local/bin/python',image,'-c',code).decode().strip()
        proof=json.loads(value);assert len(proof['config'])==64
        assert proof['resources']['topology']==plan['cpu_topology']
        plan['config_sha256'][arm]=proof['config'];probes[arm]=proof['resources']
    assert receipts[0]['business_sha256']==receipts[1]['business_sha256'] and receipts[0]['schema_sha256']==receipts[1]['schema_sha256']
    private_write(out/'plan.json',json.dumps(plan,indent=2).encode())
    private_write(out/'fixtures.json',json.dumps(fixtures,indent=2).encode())
    # Only loopback TCP readiness, no OTLP payload/provider or application request.
    code="""import socket,time
from experiments.production_graduation.gate_validation.validate_g123 import check_p2
check_p2()
for port in (6379,4318):
 deadline=time.monotonic()+10
 while True:
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.5):pass
   break
  except OSError:
   if time.monotonic()>=deadline:raise RuntimeError('Local service readiness timeout')
   time.sleep(.1)
print('LOCAL_SERVICES_READY')
"""
    assert docker('run','--rm','--pull=never','--network','container:'+db.container,'--env-file',str(private/'c0.env'),
        '--mount',f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
        '--mount',f'type=bind,src={P2_GUARD},dst=/p2_netguard,readonly','--entrypoint','/usr/local/bin/python',image,'-c',code).strip()==b'LOCAL_SERVICES_READY'
    private_write(out/'preparation.json',json.dumps(dict(status='AA_CALIBRATION_PREPARED_NOT_EXECUTED',plan_sha256=sha_file(out/'plan.json'),fixtures_sha256=sha_file(out/'fixtures.json'),private_state=str(private),databases=receipts,postgres_resources=resources,worker_resource_probes=probes,provider_calls=0),indent=2).encode())
    print(str(out.relative_to(ROOT)))


def execute(out):
    out=Path(out).resolve();plan=json.loads((out/'plan.json').read_text())
    assert plan['schema']=='orq41-aa-calibration-v1' and plan['not_a_gate'] is True and plan['full_c1_both_arms'] is True
    assert plan['images']['c0']==plan['images']['c1'] and plan['symmetric_limit_percent']==5
    review=json.loads((out/'independent-review.json').read_text())
    assert review['status']=='AA_CALIBRATION_HARNESS_REVIEW_PASS' and review['plan_sha256']==sha_file(out/'plan.json')
    for name,digest in {**plan['harness_sha256'],**plan['support_files_sha256']}.items(): assert sha_file(ROOT/name)==digest
    prep=json.loads((out/'preparation.json').read_text())
    assert prep['plan_sha256']==sha_file(out/'plan.json') and prep['fixtures_sha256']==sha_file(out/'fixtures.json')
    inspect_environment(plan);db=Database(plan['containers']['postgres'])
    for receipt in prep['databases']:
        assert db.business_hash(receipt['database'])==receipt['business_sha256'] and db.schema_hash(receipt['database'])==receipt['schema_sha256']
    private=Path(prep['private_state']);passwords=json.loads((private/'local-credentials.json').read_text())
    private_write(out/'execution-started.json',json.dumps(dict(plan_sha256=sha_file(out/'plan.json'),started=datetime.now(timezone.utc).isoformat())).encode())
    arms={'c0':[],'c1':[]};pg_counters=[]
    for cell in plan['arm_cell_order']:
        arm=cell['arm'];key=arm+'-'+cell['cell'];name='orq41-aa-'+plan['run_id']+'-'+key.lower()
        output=out/(key+'.json');assert not output.exists()
        values=env_for(arm,'C1',plan['databases'][arm],passwords)
        values.update(PYTHONPATH='/p2_netguard:/app',PATH='/usr/local/bin:/usr/bin:/bin',G6_RUN_DIR='/g6run',G6_ARM=arm,G6_CELL=cell['cell'],P2_NET_AUDIT_LOG='/g6run/network-audit.log')
        env=private/(key+'.env');private_write(env,''.join(f'{k}={v}\n' for k,v in sorted(values.items())).encode())
        before=inspect_environment(plan)
        docker('create','--pull=never','--name',name,'--network','container:'+db.container,'--user=1000:1000',
            '--cpus=2','--cpuset-cpus','0,2','--memory=2147483648','--memory-swap=2147483648','--env-file',str(env),
            '--mount',f'type=bind,src={out},dst=/g6run','--mount',f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
            '--mount',f'type=bind,src={P2_GUARD},dst=/p2_netguard,readonly','--entrypoint','/usr/local/bin/python',plan['images'][arm],
            '-m','experiments.production_graduation.gate_validation.aa_calibration_worker')
        info=json.loads(docker('inspect',name))[0];h=info['HostConfig']
        assert info['Image']==plan['images'][arm] and h['NetworkMode']=='container:'+json.loads(docker('inspect',db.container))[0]['Id'] and not h.get('PortBindings')
        assert cpu_list(h['CpusetCpus'])==set(API_CPUS) and h['NanoCpus']==2_000_000_000 and h['Memory']==h['MemorySwap']==2_147_483_648
        docker('start',name);code=docker('wait',name).strip();private_write(out/(key+'.log'),docker('logs',name))
        if code!=b'0': raise RuntimeError('A/A worker failed; preserve artifacts and never auto-resend')
        worker=json.loads(output.read_text());assert worker['config_identity']==plan['config_sha256'][arm]
        assert worker['full_c1'] is True
        assert resource_delta(worker['resources_before'],worker['resources_after'])==worker['cpu_stat_delta']
        assert worker['resources_before']['topology']==plan['cpu_topology']
        expected=[s for s in plan['samples'] if s['language']+'-'+s['protocol']==cell['cell']]
        assert len(worker['samples'])==len(expected)==105
        for row,sample in zip(worker['samples'],expected):
            assert all(row[k]==sample[k] for k in ('sample_id','language','protocol','warmup','category','request_id','conversation_id'))
            assert row['status']=='PASS' and row['preparation_ns']==row['primary_dispatch_ns']-row['start_ns']>=0
        arms[arm].extend(worker['samples'])
        after=inspect_environment(plan);pg_counters.append(dict(cell=key,before=before,after=after,delta=resource_delta(before,after)))
    audit=out/'network-audit.log';assert not audit.exists() or not audit.read_bytes()
    result=summarize_aa(arms);result.update(plan_sha256=sha_file(out/'plan.json'),
        request_count=840,postgres_cell_counters=pg_counters,worker_receipts={p.name:sha_file(p) for p in out.glob('c?-*.json')})
    private_write(out/'result.json',json.dumps(result,indent=2).encode());print(result['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',type=Path);args=parser.parse_args()
    execute(args.execute) if args.execute else prepare()
