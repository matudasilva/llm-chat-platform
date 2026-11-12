# Authorized balanced A/A execution commands

This is one local-stub execution of packet261109162430, not formal G6 or a
paid campaign. The exact plan was already independently reviewed. Existing
images are reused with pull=never. No source edits, retries or replacement
measurements are authorized.

## Pre-admission proof

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-261109162430-execution-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/preflight_check.py
```

Result: BLOCKED_AA_EXECUTION_PREFLIGHT_PASS. Protected 500-file inventory,
exact plan/review, source/support pins, actual prepared databases, unchanged
planner/autovacuum settings, image/resource/network identity, actual image
Settings/seed probes, local readiness and available evidence space verified.
Settings-only probes made no application/provider requests. Authorization is
bound to this plan in execution-authorization.json.

## Single reviewed controller execution

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-261109162430-execution-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python -m experiments.production_graduation.gate_validation.blocked_latency --execute .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430 > .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/controller-stdout.log 2> .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/controller-stderr.log
```

Raw controller stdout/stderr are retained separately. Each worker is admitted
once under durable markers; no marker is reset and no worker is resent. The
approved controller checks source identity before every next admission.
Manual Docker stdout/stderr recovery will retain both streams after execution,
covering the documented R2 LOW automatic stdout-only diagnostic limitation
without changing controller code.

Controller exit code: 0. Raw stdout: AA_CALIBRATION_FAIL. This is completion
of the evidence-producing process, not a passing calibration result.

## Post-execution read-only proof, raw-stream retention and own-service stop

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-blocked-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-blocked-261109162430-execution-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review/post_check.py
```

Result: BLOCKED_AA_POST_EXECUTION_PROOF_PASS, calibration AA_CALIBRATION_FAIL.
32 complete workers, 1,440 functional PASS rows, 800 measured/640 warmups,
1,440 distinct accounting instance IDs, all raw hashes and integer P95 replay
verified. Three cells PASS; ES-SSE FAIL at symmetric 8.42042448495289%.
Each actual database: 720 conversations/18,720 messages/720 usage_events/
0 rag_request_metrics; exact frozen histories plus single exchanges and P3/RLS/
schema/locale checks pass. Parent SQL is read-only; no reviewer SQL is claimed.
All 500 protected files unchanged. No new application request in post-validation.

Both stdout/stderr were retained for all 32 exited workers, without fixing
R2 LOW in controller source. Only this run's three own preparation services
were stopped after proof; all data/containers/markers retained, source PG running.
P2 network audits empty/absent. External/provider calls0, paid requests0, spend0.

No pytest rerun or new performance sample after the single execution.
Distinct post-execution review/replay is recorded in independent-review.md
and receipt.json. No automatic repetition, formal G6 or paid admission.
