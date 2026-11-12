# Offline analysis validation

Historical commands only. Scope: existing files and read-only logs/source from
already stopped containers. No service start, SQL connection, application
request, provider call or new performance measurement.

## Read already stopped collector logs

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-261109162430-offline-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/offline-es-sse/read_retained_collector.py
```

## Derive supplemental partitions and trace correlations

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-261109162430-offline-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/offline-es-sse/analyze.py
```

## Reproduce outputs from a clean scratch copy

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-261109162430-offline-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/offline-es-sse/verify_reproduction.py
```

## Verify baked source boundaries from a stopped worker

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-261109162430-offline-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python - <<'PY'
from pathlib import Path
import hashlib,io,json,subprocess,tarfile
p=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430'); out=p/'execution-review/offline-es-sse'
plan=json.loads((p/'plan.json').read_text())
name='orq41-blocked-'+plan['run_id']+'-c0-es-sse-b0'
docker=['docker','--host','unix:///var/run/docker.sock']
info=json.loads(subprocess.run(docker+['inspect',name],capture_output=True,check=True).stdout)[0]
assert not info['State']['Running'] and info['Image']==plan['images']['c0']==plan['images']['c1']
proof={}
for relative in ('app/core/domain/retrieval_pipeline.py','app/core/providers/pgvector_store.py','app/core/observability/context_evidence.py'):
 raw=subprocess.run(docker+['cp',name+':/app/'+relative,'-'],capture_output=True,check=True).stdout
 with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
  members=[m for m in archive.getmembers() if m.isfile()]
  assert len(members)==1
  data=archive.extractfile(members[0]).read()
 digest=hashlib.sha256(data).hexdigest(); host=hashlib.sha256(Path(relative).read_bytes()).hexdigest()
 assert digest==host,relative
 proof[relative]=dict(baked_image_sha256=digest,current_host_sha256=host,equal=True)
assert hashlib.sha256(Path('experiments/production_graduation/gate_validation/local_api.py').read_bytes()).hexdigest()==plan['harness_sha256']['experiments/production_graduation/gate_validation/local_api.py']
with (out/'source-boundary-proof.json').open('x') as f:
 f.write(json.dumps(dict(status='RETAINED_IMAGE_SOURCE_BOUNDARY_READ_ONLY_PASS',image=info['Image'],stopped_worker_id=info['Id'],source=proof,local_embedding_stub_source_bound=True,services_started=0,new_requests=0,provider_calls=0),indent=2)+'\n')
print('Retained image source boundaries match host; no service start or request')
PY
```

## Results

- 7,920 retained spans, 1,440 unique request roots and all 1,440 original
  accounting IDs matched, with expected child stages and correlation.
- 69 hashed inputs preserved; original primary P95 and calibration FAIL unchanged.
- All four derived files reproduced byte-for-byte in a scratch copy.
- All 500 protected source/test/global-env files remain unchanged.
- Baked retrieval_pipeline.py, pgvector_store.py and context_evidence.py from
  the stopped worker exactly match host source. No request or startup.
- No new pytest or runtime validation. Supplemental statistics are descriptive.
- New requests0, service starts0, external/provider calls0, spendUSD0.
- Status: OFFLINE_ES_SSE_ANALYSIS_COMPLETE_CAUSE_UNRESOLVED.
- G6 stays CONTROLLED_G6_FAIL and paid admission BLOCKED_CONTROLLED_G6_FAIL.

