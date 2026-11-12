# Incomplete A/A attempt validation record

Historical commands; do not rerun the started packet or overwrite evidence.
No source fix or request resend was performed.

## Single authorized execution (exit1)

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python -m experiments.production_graduation.gate_validation.blocked_latency --execute .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719
```

## Parent read-only post-failure proof and complete logs

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python - <<'PY'
from pathlib import Path
import json,subprocess,hashlib
from experiments.production_graduation.gate_validation import blocked_latency as h
p=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719');out=p/'execution-review';out.mkdir(exist_ok=False);plan=json.loads((p/'plan.json').read_text());prep=json.loads((p/'preparation.json').read_text());fixtures=json.loads((p/'fixtures.json').read_text())
name='orq41-blocked-'+plan['run_id']+'-c0-en-json-b0'
logs=subprocess.run(['docker','--host','unix:///var/run/docker.sock','logs',name],capture_output=True,check=True,timeout=60)
h.private_write(out/'worker-stdout.log',logs.stdout);h.private_write(out/'worker-stderr.log',logs.stderr)
assert logs.stdout==(p/'c0-EN-json-b0.log').read_bytes()
info=json.loads(subprocess.run(['docker','--host','unix:///var/run/docker.sock','inspect',name],capture_output=True,check=True,timeout=60).stdout)[0]
assert info['State']['Status']=='exited' and info['State']['ExitCode']==1 and not info['State']['OOMKilled']
assert b'invalid run cache namespace' in logs.stderr and b'blocked_latency_worker.py' in logs.stderr
keys=('Status','Running','ExitCode','StartedAt','FinishedAt','OOMKilled')
h.write_json(out/'worker-state.json',dict(name=name,id=info['Id'],image=info['Image'],state={k:info['State'][k] for k in keys},command=info['Config']['Cmd'],network_mode=info['HostConfig']['NetworkMode'],cpuset=info['HostConfig']['CpusetCpus']))
db=h.aa.Database(plan['containers']['postgres']);actual=h.verify_databases(db,plan,fixtures)
assert actual==prep['databases']
aux={}
for arm,database in plan['databases'].items():
 row=h.readonly(db,database,'SELECT (SELECT count(*) FROM usage_events),(SELECT count(*) FROM rag_request_metrics);').strip()
 assert row=='0|0';aux[arm]=dict(usage_events=0,rag_request_metrics=0)
assert not (p/'result.json').exists() and not list(p.glob('c?-*-b?.json'))
assert len(list(p.glob('*-started.json')))==2
proof=dict(status='BLOCKED_AA_POST_FAILURE_PREPARED_DATA_UNCHANGED',plan_sha256=h.sha_file(p/'plan.json'),database_projection=actual,equals_preparation=True,auxiliary_tables=aux,worker_containers_started=1,failed_workers=1,worker_exit_code=1,app_lifespan_entered=False,application_requests_executed=0,measured=0,warmups=0,provider_operations_executed=0,external_provider_calls=0,spend_usd='0',failure='NamespacedRedis validation during install before app lifespan/run_block',traceback_source='worker-stderr.log',controller_stdout_log_omits_stderr=True)
h.write_json(out/'database-post-failure-verification.json',proof)
print(proof['status'])
PY
```

## Pure startup namespace reproduction

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719/execution-review/reproduce_startup.py
```

## Stop only own services; preserve containers/data/markers

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python - <<'PY'
from pathlib import Path
import json,subprocess
from experiments.production_graduation.gate_validation import blocked_latency as h
p=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719');plan=json.loads((p/'plan.json').read_text())
def docker(*args):return subprocess.run(['docker','--host','unix:///var/run/docker.sock',*args],capture_output=True,check=True,timeout=100).stdout

def inspect(name):
 d=json.loads(docker('inspect',name))[0];s=d['State']
 return dict(name=name,id=d['Id'],image=d['Image'],state={k:s[k] for k in ('Status','Running','ExitCode','StartedAt','FinishedAt')},mounts=[{k:m[k] for k in ('Type','Source','Destination','RW')} for m in d['Mounts']])
source=inspect('orq41-env-pg');assert source['state']['Running']
before={k:inspect(name) for k,name in plan['containers'].items()}
worker=inspect('orq41-blocked-'+plan['run_id']+'-c0-en-json-b0');assert worker['state']['Status']=='exited' and worker['state']['ExitCode']==1
for key in ('collector','redis','postgres'):docker('stop','--time','10',plan['containers'][key])
after={k:inspect(name) for k,name in plan['containers'].items()}
assert all(not row['state']['Running'] for row in after.values())
source_after=inspect('orq41-env-pg');assert source_after['id']==source['id'] and source_after['state']['Running']
h.write_json(p/'execution-review/cleanup.json',dict(status='BLOCKED_AA_FAILED_ATTEMPT_SERVICES_STOPPED_DATA_RETAINED',plan_sha256=h.sha_file(p/'plan.json'),before=before,after=after,worker=worker,original_source_postgres_still_running=True,original_source_postgres_id=source['id'],containers_removed=0,volumes_removed=0,databases_deleted=0,marker_removed=False,request_resend=False,external_provider_calls=0,spend_usd='0'))
print('BLOCKED_AA_FAILED_ATTEMPT_SERVICES_STOPPED_DATA_RETAINED')
PY
```

## Results

- Execution controller exit1: first worker exit1, not OOM. Traceback at
  install -> NamespacedRedis before lifespan/run_block. No actual requests.
- Full worker stderr was recovered separately because the original stdout-only
  log omitted it. worker-state.json and both log streams are retained.
- BLOCKED_AA_POST_FAILURE_PREPARED_DATA_UNCHANGED: exact prepared720/17280
  projections per arm,0usage/metrics rows; no committed exchanges.
- BLOCKED_AA_STARTUP_NAMESPACE_DEFECT_REPRODUCED:32actual namespaces reject;
 32counterfactual unique names accepted by the real constructor only. No Redis,
 SQL, app lifespan, provider or performance operation in this reproduction.
- BLOCKED_AA_FAILED_ATTEMPT_SERVICES_STOPPED_DATA_RETAINED: own3services stopped,
  no deletion or marker reset; original sourcePG still running.
- Independent reviewer repeated only pure constructor validation under P2,
 inspected source/logs/parentSQL proof and recorded MEDIUMR1/LOWR2. No reviewer
 Docker/SQL/API or fix. See independent-review.md/json.

No valid AA_CALIBRATION_PASS/FAIL classification can be made from0samples.
Original167unit-test evidence remains historical; it did not cover main/install
startup integration. All source/support pins and500protected files unchanged.
Zero external/provider calls/egress/spend. No paid campaign, formalG6, G9,
Notion, commit or deployment. The started attempt remains non-resumable.

