# Plan comparison validation

Historical commands only. No /chat, provider, new A/A, runtime source change or
global/role planner override. Force modes exist only inside disposable READ ONLY
transactions. The two-mode20-execution scope was frozen before admission.

## Freeze approved inputs, type signature and mode order

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-plan-comparison-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/plan-comparison/run_plan_comparison.py --freeze
```

## Execute the twenty read-only EXPLAIN cases once

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-plan-comparison-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/plan-comparison/run_plan_comparison.py --execute .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/plan-comparison/261109225659 > .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/plan-comparison/261109225659/controller-stdout.log 2> .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/plan-comparison/261109225659/controller-stderr.log
```

## Verify raw records and compare plans offline

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-plan-comparison-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/plan-comparison/261109225659/analyze_results.py
```

## Verify own shutdown and retained historical states

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-plan-comparison-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python - <<'PY'
from pathlib import Path
import json,subprocess
p=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/plan-comparison/261109225659');m=json.loads((p/'manifest.json').read_text())
names=[m['container'],'orq41-env-pg','orq41-driver-261109222205-postgres','orq41-driver-261109222205-adapter','orq41-sql-261109212354-postgres','orq41-blocked-261109162430-postgres']
rows=[]
for name in names:
 d=json.loads(subprocess.run(['docker','--host','unix:///var/run/docker.sock','inspect',name],check=True,capture_output=True,timeout=30).stdout)[0]
 v=dict(name=name,id=d['Id'],image=d['Image'],running=d['State']['Running'],network_mode=d['HostConfig']['NetworkMode'],port_bindings=d['HostConfig'].get('PortBindings'))
 assert not v['port_bindings']
 if name=='orq41-env-pg':assert v['id']==m['source_postgres_id'] and v['running']
 else:assert not v['running']
 rows.append(v)
with (p/'environment-final.json').open('x') as f:
 f.write(json.dumps(dict(status='PLAN_COMPARISON_OWN_CLUSTER_STOPPED_HISTORY_RETAINED',containers=rows,historical_state_preserved=True,new_api_requests=0,provider_calls=0),indent=2)+'\n')
print('New cluster stopped; historical states preserved; source PG same identity; no published ports')
PY
```

## Results

- Syntax parse PASS before freeze; controller exit0.
- REQUEST_FREE_PLAN_COMPARISON_COMPLETE:20admitted/resolved/PASS,0errors/retries.
- Real rag_app/RLS/read-only/tenant validated;20fresh backend PIDs.
- Exact driver SQL/vector,bigint,text,bigint signature/parameter values retained.
- Each forced mode confirmed by local settings and prepared execution counters.
- All10generic plans slower; keyword filters retain parameterized plainto_tsquery.
- Custom filters hold literal tsquery; no exact function-call count measured.
- Combined custom7.937-8.600ms/generic23.776-27.272ms;
  document custom7.902-8.585ms/generic14.453-22.917ms.
- Keyword scan: custom0.667-0.869ms/generic7.342-19.776ms; no shared/temp reads.
- All20outputcardinalities20; EXPLAIN does not retain complete returned rows.
- Category/order coupled as preapproved; R=1 descriptive comparison only.
- Postflight data/schema/settings/defaultauto and500protectedfiles unchanged.
- Own cluster stopped/data+markers retained; old environments preserved.
- P2 audit empty/absent; external/provider calls0, application requests0, USD0.
- No pytest or repeated measurement. Parent verification, no distinct review.
- Original AA/G6FAIL/paidblock remain; runtime remediation proposal not authorized.

