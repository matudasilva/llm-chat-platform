# Preparation and exact-packet validation

All operations ran locally with scrubbed credentials/disabled dotenv under P2.
These commands are historical execution records, not instructions to repeat
preparation, overwrite immutable evidence or execute a calibration.

## Approved preparation

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python -m experiments.production_graduation.gate_validation.blocked_latency --prepare-authorization .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/preparation-authorization.json
```

## Read-only independent verifier (parent execution)

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719/independent-audit/verify_prepared_databases.py --run .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719
```

## Sanitized environment/resources/host+DB observation proof

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python - <<'PY'
from pathlib import Path
import json,subprocess
from experiments.production_graduation.gate_validation import blocked_latency as h
p=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719');plan=json.loads((p/'plan.json').read_text());prep=json.loads((p/'preparation.json').read_text());fixtures=json.loads((p/'fixtures.json').read_text())
h.validate_plan(plan,fixtures,prepared=True)
before_host=h.host_snapshot();db=h.aa.Database(plan['containers']['postgres']);before_db=h.database_snapshot(db,plan);resources=h.aa.inspect_environment(plan)
def docker(*args):return subprocess.run(['docker','--host','unix:///var/run/docker.sock',*args],capture_output=True,check=True,timeout=60).stdout
containers={}
for key,name in plan['containers'].items():
 d=json.loads(docker('inspect',name))[0];limits=d['HostConfig'];state=d['State']
 containers[key]=dict(name=name,id=d['Id'],image=d['Image'],running=state['Running'],network_mode=limits['NetworkMode'],port_bindings=limits.get('PortBindings'),cpuset=limits['CpusetCpus'],nano_cpus=limits['NanoCpus'],memory_bytes=limits['Memory'],memory_swap_bytes=limits['MemorySwap'],mounts=[{k:m[k] for k in ('Type','Source','Destination','RW')} for m in d['Mounts']])
assert all(row['running'] for row in containers.values())
actual=docker('ps','-a','--filter','name=^/orq41-blocked-'+plan['run_id']+'-','--format','{{.Names}}').decode().splitlines()
assert set(actual)==set(plan['containers'].values()),actual
source=json.loads(docker('inspect','orq41-env-pg'))[0];assert source['State']['Running'] and source['HostConfig']['NetworkMode']=='none'
after_db=h.database_snapshot(db,plan);after_host=h.host_snapshot()
assert not (p/'execution-started.json').exists() and not (p/'execution-authorization.json').exists()
proof=dict(status='BLOCKED_AA_ENVIRONMENT_BINDING_PASS',plan_sha256=h.sha_file(p/'plan.json'),containers=containers,postgres_resources=resources,host_before=before_host,host_after=after_host,host_delta=h.host_delta(before_host,after_host),database_before=before_db,database_after=after_db,database_delta=h.database_delta(before_db,after_db),prepared_database_receipts=prep['databases'],worker_containers_created=0,application_requests=0,source_postgres_id=source['Id'],source_postgres_access='read-only dump/queries only',network='dedicated network-none namespace;zero published ports',external_provider_calls=0,spend_usd='0')
h.write_json(p/'environment-binding.json',proof)
print(proof['status'])
PY
```

## File-only admission guard check after packet review

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python - <<'PY'
from pathlib import Path
from experiments.production_graduation.gate_validation import blocked_latency as h
p=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109141719')
try:
 h.preflight(p)
except FileNotFoundError as exc:
 assert Path(exc.filename)==p/'execution-authorization.json',exc
else:
 raise AssertionError('Unapproved execution must not pass admission')
assert not (p/'execution-started.json').exists() and not (p/'execution-authorization.json').exists()
h.write_json(p/'admission-guard.json',dict(status='BLOCKED_AA_ADMISSION_REQUIRES_EXECUTION_APPROVAL',plan_sha256=h.sha_file(p/'plan.json'),blocked_by='missing execution-authorization.json',review_status='BLOCKED_AA_HARNESS_REVIEW_PASS',function_tested='preflight only; no execute/prepare',docker_calls=0,database_calls=0,application_requests=0,spend_usd='0'))
print('BLOCKED_AA_ADMISSION_REQUIRES_EXECUTION_APPROVAL')
PY
```

## Observed results

- BLOCKED_AA_PREPARED_NOT_EXECUTED: two fresh720conversation/17,280history DBs,
  restore/manual ANALYZE/readback and settings/seed/resource/local-readiness PASS.
- BLOCKED_AA_PREPARED_DATABASES_READONLY_VERIFIER_PASS: all fixture/UUID/content/
  sequence/P3/RLS/schema/role/locale/CHECK truth/config/seed proofs PASS.
- BLOCKED_AA_ENVIRONMENT_BINDING_PASS: three isolated running services, no
  published ports or actual worker containers; host/DB counter files/queries and
  reset validation work. Coarse endpoints are not performance stability evidence.
- BLOCKED_AA_HARNESS_REVIEW_PASS: distinct exact-packet review; parent SQL proof
  source/receipt inspected and attributed, no reviewer infrastructure/API calls.
- BLOCKED_AA_ADMISSION_REQUIRES_EXECUTION_APPROVAL: actual preflight blocked at
  missing execution-authorization.json; no Docker/SQL/request operation in check.

No new tests were run because exact reviewed source hashes still match. Existing
167image tests/0skips and67independent pure source controls are bound through
scope.json and their original receipts. controls.xml is copied unchanged with
explicit provenance. No1,440-request A/A, warmup, performance measurement, formal
G6 or paid campaign was executed. Zero external/provider calls/egress/spend.

No source changes, runtime/schema/grant changes outside approved disposable
bootstrap, global-env/model/threshold/accounting changes, G9, Notion or commit.
All500existing protected files preserved. Credentials remain private outside the
repository. Services are left running only in their isolated namespace; actual
future execution remains subject to rechecks and exact-plan operator approval.

