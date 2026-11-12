"""Read-only inspection; raw credentials are compared in memory and never saved."""
import json,subprocess,hashlib
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
OUT=Path(__file__).resolve().parent;RUN=OUT.parent
plan=json.loads((RUN/'plan.json').read_text())
names=['orq41-aa-'+plan['run_id']+'-'+c['arm']+'-'+c['cell'].lower() for c in plan['arm_cell_order']]
p=subprocess.run(['docker','--host','unix:///var/run/docker.sock','inspect',*names],capture_output=True,timeout=30)
assert p.returncode==0,'Worker inspection failed'
items={c['Name'].lstrip('/'):c for c in json.loads(p.stdout)}
def env(c):return dict(v.split('=',1) for v in c['Config']['Env'] if '=' in v)
def normalized(e):
 e=dict(e);e['G6_ARM']='PAIRED_ARM'
 for key in ('DATABASE_URL','DATABASE_URL_APP','DATABASE_URL_OPS'):
  u=urlsplit(e[key]);e[key]=urlunsplit(u._replace(path='/PAIRED_DATABASE'))
 return e
pairs=[];runtime=[]
for cell in ('EN-json','EN-sse','ES-json','ES-sse'):
 a,b=[items['orq41-aa-'+plan['run_id']+'-'+arm+'-'+cell.lower()] for arm in ('c0','c1')]
 ea,eb=env(a),env(b);na,nb=normalized(ea),normalized(eb)
 keys=set(na)|set(nb);different=sorted(k for k in keys if na.get(k)!=nb.get(k))
 fields=('User','WorkingDir','Entrypoint','Cmd');config_equal=all(a['Config'][k]==b['Config'][k] for k in fields)
 hostfields=('CpusetCpus','CpusetMems','NanoCpus','CpuQuota','CpuPeriod','Memory','MemorySwap','NetworkMode','Privileged','ReadonlyRootfs','SecurityOpt')
 host_equal=all(a['HostConfig'][k]==b['HostConfig'][k] for k in hostfields)
 mounts=lambda c:sorted((m['Destination'],m['Source'],m['RW'],m['Type']) for m in c['Mounts'])
 assert not different and config_equal and host_equal and mounts(a)==mounts(b) and a['Image']==b['Image']==plan['images']['c0']
 pairs.append(dict(cell=cell,normalized_environment_equal=True,unexpected_environment_difference_keys=different,
  expected_raw_difference_keys=sorted(k for k in set(ea)|set(eb) if ea.get(k)!=eb.get(k)),image_equal=True,process_configuration_equal=True,resources_equal=True,mounts_equal=True))
 for c,e in ((a,ea),(b,eb)):
  runtime.append(dict(name=c['Name'],started=c['State']['StartedAt'],finished=c['State']['FinishedAt'],exit_code=c['State']['ExitCode'],oom_killed=c['State']['OOMKilled'],restart_count=c['RestartCount'],
   runtime_environment={key:e.get(key,'UNSET') for key in ('PYTHONHASHSEED','PYTHONMALLOC','PYTHONOPTIMIZE','PYTHONDONTWRITEBYTECODE','PYTHON_GIL','PYTHON_JIT','LANG','TZ','MALLOC_ARENA_MAX')}))
result=dict(status='RETAINED_PROCESS_CONFIGURATION_AUDIT_PASS',pairs=pairs,workers=runtime,
 api_requests=0,database_queries=0,provider_calls=0,external_calls=0,
 limitations=['configuration identity is not equality of runtime scheduler/heap/cache state','unset PYTHONHASHSEED leaves process hash randomization uncontrolled; magnitude unproven'],source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(OUT/'worker-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result['status'],'pairs':pairs,'runtime':runtime[0]['runtime_environment']},indent=2))
