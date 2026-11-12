"""Read-only CPU topology and retained-container resource audit."""
import hashlib,json,os,subprocess
from datetime import datetime,timezone
from pathlib import Path
OUT=Path(__file__).resolve().parent
base=Path('/sys/devices/system/cpu');rows=[]
for cpu in sorted(base.glob('cpu[0-9]*'),key=lambda p:int(p.name[3:])):
 def read(relative):
  p=cpu/relative
  return p.read_text().strip() if p.exists() else None
 rows.append(dict(cpu=int(cpu.name[3:]),core_id=read('topology/core_id'),siblings=read('topology/thread_siblings_list'),core_type=read('topology/core_type'),max_khz=read('cpufreq/cpuinfo_max_freq'),governor=read('cpufreq/scaling_governor')))
names=['orq41-g6-261106225237-c0-en-json','orq41-g6-261106225237-c1-en-json','orq41-env-pg']
r=subprocess.run(['docker','--host','unix:///var/run/docker.sock','inspect',*names],capture_output=True,timeout=30)
assert r.returncode==0,'Retained container inspection failed'
containers=[]
for c in json.loads(r.stdout):
 h=c['HostConfig']
 containers.append(dict(name=c['Name'],id=c['Id'],image=c['Image'],resources={k:h.get(k) for k in ('CpusetCpus','CpusetMems','NanoCpus','CpuQuota','CpuPeriod','Memory','MemorySwap','NetworkMode')}))
result=dict(status='READONLY_HARDWARE_AUDIT_COMPLETE',observed_utc=datetime.now(timezone.utc).isoformat(),cpu_topology=rows,auditor_affinity=sorted(os.sched_getaffinity(0)),containers=containers,
 limitations=['current sysfs/config observations, not historical per-request scheduling records','maximum advertised frequencies do not measure actual instruction throughput or observed clock rate','no CPU migration, throttle, thermal or actual-frequency tape was retained in previous experiments'],
 source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),api_requests=0,database_queries=0,provider_calls=0,external_calls=0,spend_usd='0')
(OUT/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(result['status'])
