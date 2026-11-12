# SQL diagnostic validation commands

All commands used P2 credential scrubbing and network isolation. No application
requests, provider calls, new A/A, paid campaign or source edits. One fresh local
PostgreSQL service only; ten hybrid SELECT executions through read-only EXPLAIN.

## Freeze before database operations

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-sql-diagnostic-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/sql-diagnostic/run_sql_diagnostic.py --freeze
```

## One approved execution

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-sql-diagnostic-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/sql-diagnostic/run_sql_diagnostic.py --execute .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/sql-diagnostic/261109212354 > .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/sql-diagnostic/261109212354/controller-stdout.log 2> .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/sql-diagnostic/261109212354/controller-stderr.log
```

## File-only validation of retained records

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-sql-diagnostic-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/sql-diagnostic/261109212354/analyze_results.py
```

## Final read-only container/isolation check

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-sql-diagnostic-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python - <<'PY'
from pathlib import Path
import json,subprocess
p=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/sql-diagnostic/261109212354');m=json.loads((p/'manifest.json').read_text());prior=p.parents[3]
names=[m['container'],'orq41-env-pg','orq41-blocked-261109162430-postgres','orq41-blocked-261109162430-redis','orq41-blocked-261109162430-collector']
rows=[]
for name in names:
 d=json.loads(subprocess.run(['docker','--host','unix:///var/run/docker.sock','inspect',name],check=True,capture_output=True).stdout)[0]
 row=dict(name=name,id=d['Id'],image=d['Image'],running=d['State']['Running'],network_mode=d['HostConfig']['NetworkMode'],port_bindings=d['HostConfig'].get('PortBindings'))
 assert not row['port_bindings']
 if name=='orq41-env-pg':assert row['id']==m['source_postgres_id'] and row['running']
 else:assert not row['running']
 rows.append(row)
audit=Path('/tmp/orq41-sql-diagnostic-network.log')
assert not audit.exists() or audit.stat().st_size==0
with (p/'environment-final.json').open('x') as f:f.write(json.dumps(dict(status='SQL_DIAGNOSTIC_OWN_CLUSTER_STOPPED_HISTORICAL_STATE_PRESERVED',containers=rows,network_audit_bytes=0,new_api_requests=0,provider_calls=0),indent=2)+'\n')
print('Own cluster stopped; old A/A services stay stopped; original source PG identity/running state retained; no published ports')
PY
```

## Results

- Initial file-only freeze: KeyError(casefile_sha256), recorded in ../authoring/.
  No allocation, SQL or container occurred; corrected to the exact existing
  support_files_sha256[cases.json] identity. Final freeze exit0.
- Controller exit0: REQUEST_FREE_SQL_DIAGNOSTIC_COMPLETE.
- Ten admitted, ten resolved PASS, zero failures/unresolved/retries.
- Actual rag_app login, RLS on, correct tenant, READ ONLY and rollback.
- One custom plan execution/case, zero generic; 20 output rows per case.
- Server execution7.492-8.157ms, planning0.897-1.035ms; descriptive, no G6 PASS.
- Same plan structure, two sequential scans; 0shared reads/writes/temporary I/O.
- Parent retained-record verification PASS; no new SQL call in verification.
- Postflight data/schema/settings and 500 protected source files unchanged.
- New cluster stopped/data retained; historical source/services state unchanged.
- No new pytest, app/provider calls or benchmark. External spendUSD0.
- Root cause unresolved; AA_CALIBRATION_FAIL/G6 FAIL/paid block preserved.

