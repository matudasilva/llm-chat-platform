# Validation record

Commands executed from the repository root in this order. Local Docker orchestration uses the approved Unix socket; its application/service networks remain isolated. No image download. Initial preparation completed before creation of the prospective review packet; the third command executed only after the exact-plan independent-review PASS. One execution only, no retry/resume.

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-aa-fixed-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-aa-fixed-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python -m experiments.production_graduation.gate_validation.aa_calibration
```

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-aa-fixed-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-aa-fixed-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/aa-runs/261108131511/independent-audit/verify_prepared_databases.py --run .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/aa-runs/261108131511
```

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-aa-fixed-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-aa-fixed-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python -m experiments.production_graduation.gate_validation.aa_calibration --execute .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/aa-runs/261108131511
```

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-aa-fixed-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-aa-fixed-prepare/network-audit.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/aa-runs/261108131511/execution-review/verify_final_databases.py --run .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/aa-runs/261108131511
```

```sh
docker --host unix:///var/run/docker.sock stop --time 10 orq41-aa-261108131511-collector
```

```sh
docker --host unix:///var/run/docker.sock stop --time 10 orq41-aa-261108131511-redis
```

```sh
docker --host unix:///var/run/docker.sock stop --time 10 orq41-aa-261108131511-postgres
```

Results: AA_CALIBRATION_PREPARED_NOT_EXECUTED; AA_PREPARED_DATABASES_READONLY_VERIFIER_PASS; AA_CALIBRATION_FAIL (driver exit0 means result publication); AA_FINAL_DATABASES_READONLY_VERIFIER_PASS; three own services stopped/data retained. All840 requests passed (800 measured,40warmups), three of four calibration cells failed.

New pure file/hash/fixture comparison and protected-surface/P2 audit checks are recorded in preparation-comparison.json and scope-final.json. Their Python assertions verified exact old/new protocol/business equality, disjoint fresh UUIDs, current remediation/source pins and160unchanged protected files. Docker cleanup inline-script checked eight exited0 workers/resources and retained sanitized snapshots only, then stopped exactly three named own services; original source PostgreSQL still running.

No new pytest execution this task: controls.xml copies the reviewed remediation final.xml90PASS/0skips, with origin/digest in preparation-comparison.json. Exact code unchanged. Prospective review and postrun independent replay are attributed to /root/packet_review; execution-review/independent_replay.py and receipt.json bind the checks. Read-only SQL/config checks executed by parent, not reviewer. Empty P2 audit and network-none/container-namespace resource proof retained. No external/provider calls or paid spend.
