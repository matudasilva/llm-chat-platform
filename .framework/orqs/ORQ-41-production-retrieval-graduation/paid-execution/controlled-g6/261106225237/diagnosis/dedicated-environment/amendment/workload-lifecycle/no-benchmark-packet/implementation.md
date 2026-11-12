## Budget stop — latest adapter edits are unvalidated

The follow-up stopped at the enforced token budget (38,820 reported / 35,000).
Latest bootstrap, packet sealing preparation and focused-test changes are work in
progress, NOT covered by the previous 11-test result or document review. The
subagent was interrupted. No new test completion or independent source PASS is
claimed. Next: inspect partial bootstrap changes, run only the two focused adapter
suites under P2, resolve failures and independently review before any readiness
claim. No host/live authorization or execution; G6 and paid block unchanged.

# Synthetic no-benchmark adapter — offline implementation

Status: P2 adapter implemented; deployment and execution remain blocked. No live
identities, source-review receipt, deployment hash, or authorization is asserted.

## Adapter behavior

`synthetic_packet.py` authors one manifest only from supplied frozen identities.
It requires exactly one API worker, PostgreSQL, Redis, and collector; pins the
synthetic worker source hashes, direct Python PID1 command, exact source and
receipt mounts, and the read-only `/orq41-lifecycle` mount required by the
existing client. Duplicate, missing, or extra mounts fail closed. Its sealed-installation preparation returns a structured review
record and performs zero writes. It deliberately does not emit shell commands:
the existing sealed helper's exact source allowlist does not bind the new adapter,
and deployment/source-review/journal artifacts are not available in this lane.

`synthetic_worker.py` uses the existing `WorkerClient` Unix protocol for one
fixed slot. The CLI rejects any process that is not PID1 and verifies the
descriptor worker identity. Cleanup runs even after protocol failure. It writes
an explicitly synthetic receipt and the existing finalizer receipt only after
successful protocol completion and cleanup. No app, HTTP, provider, or benchmark
code is imported or invoked.

`synthetic_controller.py` waits for actual stopped state via the existing
`wait_worker`, requires exit code zero, validates both receipts and recomputes
the synthetic result digest, then calls the existing controller finish once.
Unknown exit, receipt, or protocol outcomes fail closed; there is no resend path.

## Validation

Focused deterministic tests ran in an empty network namespace with the absolute
P2 network guard and credential variables disabled:

```text
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp LANG=C.UTF-8 APP_SETTINGS_ENV_FILE= AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=41 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-synthetic-packet-network.log .venv/bin/python -m pytest -q -c /dev/null -p no:cacheprovider tests/experiments/test_orq41_synthetic_packet.py --junitxml=.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/workload-lifecycle/no-benchmark-packet/focused-p2.xml
11 passed in 0.08s
```

The P2 audit path `/tmp/orq41-synthetic-packet-network.log` was not created;
the test ran with `env -i`, empty `APP_SETTINGS_ENV_FILE`, and AWS credential
file paths set to `/nonexistent`. No credential values were present in the test
environment.

No live staging, installer execution, `/var` or `/run` writes, container/service
operation, application request, provider call, benchmark, or paid execution was
performed. The worker PID1 and Unix namespace integration remain unexecuted until
a separately reviewed and authorized staging packet exists.
The pinned `python3 -I` command does not prove that the `experiments` package is
importable in the selected container image. Bootstrap and image availability
remain unresolved; no image or repository path was invented to bridge that gap.
