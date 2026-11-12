# Design-only validation

**MEASUREMENT_AMENDMENT_DESIGN_INTERNAL_CONSISTENCY_PASS**: 15 author checks.
This is neither independent review, harness validation nor execution evidence.
No new pytest, Docker, SQL, application request, provider or calibration ran.

The checks confirm the unchanged measured business multiset against the latest
frozen fixtures, 25 cases/category, five appearances/business case, 20 warmups
per worker, four balanced blocks/cell, 800 measured +640 warmups =1,440 requests,
32 workers and exact proposed PostgreSQL projections. Each arm goes first twice
per cell; category first/second counts differ by at most one because 25 is odd.

Other checks bind retained evidence/helper hashes, unchanged timing/thresholds/
images/resources/deadlines, seed declaration, seven-table ANALYZE allowlist from
retained schema, and 497 unchanged source/test/global-env files. Host CPU metric
files were checked for readability only, not stability under load. Future harness
files do not exist. The empty namespace exposes only loopback; credentials/dotenv
are scrubbed and the P2 network audit is empty/absent. External spend USD 0.

Exact reproducible command from the repository root, requiring the existing
permission to create the isolated P2 namespace:

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-aa-fixed-prepare/home LANG=C.UTF-8 AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-measurement-amendment-network.log /home/matias/Cursor/llm-chat-platform/.venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment/validate_design.py
```

Exit 0; full assertion groups and per-cell/block arithmetic in `validation.json`.
`validate_design.py` uses only standard-library file/namespace observations and
arithmetic. It contains no application import, service start, SQL, provider,
subprocess or connection operation. It preserves an existing identical receipt
and rejects overwriting a different one. Source identities are a snapshot of this
design task; a later authorized implementation needs new executable pins.

An initial inline author validation incorrectly required a route-table header.
The isolated namespace returned an entirely empty route file. That failure is
retained in `validation-initial-error.json`; a read-only inspection confirmed it.
The corrected document validator accepts empty or header-only tables (zero route
entries) and independently requires the loopback-only interface list. No protocol,
harness, application or network policy was changed to make the check pass.

Files authored here are proposal.md, contract.json, this record, the pure
document validator, validation.json and the retained initial validation error.
Only planning-status.json and session-handoff.md receive proposal references.
Implementation, exact executable manifest review and any local A/A execution
remain unapproved. Historical AA/G6 FAILs, paid block and global Implement /
DECISION_FREEZE_PASS are unchanged. No Notion, commit or deployment.
