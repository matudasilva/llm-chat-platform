# Driver diagnostic validation

Historical commands. No source edit, application/provider request, EXPLAIN,
explicit PREPARE, forced plan or new A/A. Thirty adapter calls only:20warmups
and10diagnostics in the frozen order, one attempt/slot. Source scripts parsed
with ast.parse before freezing; no pytest was run.

## Freeze exact volume and identities

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-driver-diagnostic-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/driver-diagnostic/run_driver_diagnostic.py --freeze
```

## Single authorized adapter diagnostic

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-driver-diagnostic-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/driver-diagnostic/run_driver_diagnostic.py --execute .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/driver-diagnostic/261109222205 > .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/driver-diagnostic/261109222205/controller-stdout.log 2> .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/driver-diagnostic/261109222205/controller-stderr.log
```

## File-only validation of all retained rows

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-driver-diagnostic-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/driver-diagnostic/261109222205/analyze_results.py
```

## Read-only final container-state check

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-driver-diagnostic-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python - <<'PY'
from pathlib import Path
import json,subprocess
p=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/driver-diagnostic/261109222205');m=json.loads((p/'manifest.json').read_text())
names=[m['container'],m['worker'],'orq41-env-pg','orq41-sql-261109212354-postgres','orq41-blocked-261109162430-postgres','orq41-blocked-261109162430-redis','orq41-blocked-261109162430-collector']
rows=[]
for name in names:
 d=json.loads(subprocess.run(['docker','--host','unix:///var/run/docker.sock','inspect',name],check=True,capture_output=True,timeout=30).stdout)[0]
 v=dict(name=name,id=d['Id'],image=d['Image'],running=d['State']['Running'],network_mode=d['HostConfig']['NetworkMode'],port_bindings=d['HostConfig'].get('PortBindings'))
 assert not v['port_bindings']
 if name=='orq41-env-pg':assert v['id']==m['source_postgres_id'] and v['running']
 else:assert not v['running']
 rows.append(v)
with (p/'environment-final.json').open('x') as f:
 f.write(json.dumps(dict(status='DRIVER_DIAGNOSTIC_STOPPED_DATA_RETAINED',containers=rows,historical_state_preserved=True,provider_calls=0,app_requests=0),indent=2)+'\n')
print('Adapter/PG stopped; old SQL/A-A clusters stay stopped; original source PG unchanged; no published ports')
PY
```

## Observed results

- Controller and worker exit0: REQUEST_FREE_DRIVER_DIAGNOSTIC_COMPLETE.
- 30 admitted/resolved PASS; no retry, unresolved slot or dispose failure.
- Real build_rag_sessionmaker/TenantScopedSession/PgVectorStore path and RLS.
- Actual SQL matches the source template, replacing binds in occurrence order.
- Inferred types vector,bigint,text,bigint; one backend/one hybrid cached name.
- Counter history: custom1..5, then generic1..25; mode remains auto.
- All10post-warmup calls generic; same ordered visible-result projection hash.
- Diagnostic document elapsed12.001-15.808ms/CPU0.409-0.493ms;
  combined19.529-24.140ms/CPU0.434-0.534ms; descriptive only.
- Metadata observations outside adapter timing; no PostgreSQL CPU measured.
- Corpus/business/schema/settings and500protectedfiles unchanged.
- New process/PG stopped/data+markers retained; old environment state preserved.
- P2 audit empty/absent. External/provider calls0, /chat0, external spendUSD0.
- Original AA/G6 FAIL and paid block preserved; no historical-cause certification.
- next-proposal.md is a separate20-query forced-mode comparison, not authorized.

