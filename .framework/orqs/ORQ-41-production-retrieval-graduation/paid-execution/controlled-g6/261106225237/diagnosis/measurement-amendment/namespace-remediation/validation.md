# Namespace fix validation commands

Historical execution records. Original source is retained under initial-source/.
No requests, Redis/SQL/provider calls occurred in the new startup probes; the
existing native JSON/SSE regression tests use terminal memory transports.

## Expected RED startup reproduction before worker fix

```sh
docker run --rm --pull=never --network none --cpus=2 --cpuset-cpus=0,2 --memory=2147483648 --memory-swap=2147483648 --user=1000:1000 --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/experiments,dst=/app/experiments,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/tests,dst=/app/tests,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework,dst=/app/.framework,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/scripts,dst=/app/scripts,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard,dst=/p2_netguard,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/namespace-remediation,dst=/validation --entrypoint /usr/bin/env sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707 -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/p2_netguard:/app P2_NET_AUDIT_LOG=/validation/network-audit.log /usr/local/bin/python -m pytest -q --confcutdir=/app/tests/experiments -o asyncio_mode=strict -o asyncio_default_fixture_loop_scope=function -o cache_dir=/tmp/pytest_cache -W error::RuntimeWarning tests/experiments/test_orq41_blocked_latency.py -k worker_main_startup --junitxml=/validation/startup-before.xml
```

## Focused GREEN startup/namespace validation

```sh
docker run --rm --pull=never --network none --cpus=2 --cpuset-cpus=0,2 --memory=2147483648 --memory-swap=2147483648 --user=1000:1000 --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/experiments,dst=/app/experiments,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/tests,dst=/app/tests,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework,dst=/app/.framework,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/scripts,dst=/app/scripts,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard,dst=/p2_netguard,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/namespace-remediation,dst=/validation --entrypoint /usr/bin/env sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707 -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/p2_netguard:/app P2_NET_AUDIT_LOG=/validation/network-audit.log /usr/local/bin/python -m pytest -q --confcutdir=/app/tests/experiments -o asyncio_mode=strict -o asyncio_default_fixture_loop_scope=function -o cache_dir=/tmp/pytest_cache -W error::RuntimeWarning tests/experiments/test_orq41_blocked_latency.py -k 'worker_main_startup or all_worker_namespaces' --junitxml=/validation/startup-after.xml
```

## Final regression in immutable C1 image

```sh
docker run --rm --pull=never --network none --cpus=2 --cpuset-cpus=0,2 --memory=2147483648 --memory-swap=2147483648 --user=1000:1000 --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/experiments,dst=/app/experiments,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/tests,dst=/app/tests,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework,dst=/app/.framework,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/scripts,dst=/app/scripts,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard,dst=/p2_netguard,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/namespace-remediation,dst=/validation --entrypoint /usr/bin/env sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707 -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONHASHSEED=41 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/p2_netguard:/app P2_NET_AUDIT_LOG=/validation/network-audit.log /usr/local/bin/python -m pytest -q --confcutdir=/app/tests/experiments -o asyncio_mode=strict -o asyncio_default_fixture_loop_scope=function -o cache_dir=/tmp/pytest_cache -W error::RuntimeWarning tests/experiments/test_orq41_blocked_latency.py tests/experiments/test_orq41_aa_calibration.py tests/experiments/test_orq41_controlled_latency.py tests/experiments/test_orq41_performance_cleanup.py --junitxml=/validation/final-image.xml
```

Observed RED:2failed/77deselected, exact invalid-run-cache-namespace in main/install.
Observed focused GREEN:3passed/77deselected. Final:170passed/0failed/0skipped,
no warnings, pinned C1 Python3.13.15, networknone/P2/credential scrub/empty dotenv.
These are successive validations, not additive distinct-test counts. Independent
source reviewer68pureP2 PASS/12native-startup cases not repeated on host; actual
image XML inspected and attributed accurately. Both touched files and prior
source versions are hash-bound in source-manifest.json/independent-review.json.
Shared validator/controller and498other files unchanged. No R2stderr fix, real
PostgreSQL validation, A/A execution or paid operation by this source fix.

