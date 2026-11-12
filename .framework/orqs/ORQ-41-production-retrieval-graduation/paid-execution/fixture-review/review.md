# Prospective paid-fixture materialization independent review

**PROSPECTIVE_FIXTURE_MATERIALIZATION_INDEPENDENT_REVIEW_PASS**. Reviewer `/root/g9_final_distinct_reviewer` did not author prepare_manifest.py. Scope is read-only input/source and pure in-memory validation; no fixture seeding or paid readiness is certified. No concrete error was found in this materialization.

Independent checks in verify.py confirm168 entries,160 measured/8 warmups,40 case identities and168 unique prospective conversation UUIDs. Each measured case appears exactly four times: C1/E1 crossed with JSON/SSE. Question, language, category, tenant and complete seeded-history content match across all paired entries, while every entry has a different prospective conversation. All slot UUIDs independently reconstruct from the recorded namespace. Warmup identities are separate, unique and excluded from measured IDs. Block ordering and strict JSON/SSE alternation match the approved campaign; each block has10 slots per measured category plus2 warmups (5 identities per category/path).

EN and ES each have5 document,5 history,5 combined and5 empty identities. Document/combined target the pinned P3 tenant; history/empty target new named no-document tenants rather than relabeling/copying corpus rows. Document/empty/warmup fixture histories are empty. The20 history/combined case histories each contain24 complete alternating turns (48 messages), with the unique target fact in the first turn. Using the real ConversationHistoryAssembler(max_messages=20,max_chars=12000) and build_materialized_window against an in-memory port, all20 target facts are outside the recent window and remain in the excluded-turn corpus. This establishes the prospective out-of-window placement without changing window thresholds. There are80 prospective history-bearing conversations/3840 historical messages across paired slots.

Materialization canonical manifest digest and all recorded JSON file hashes match. Reviewer receipt also hashes preparation source and all reviewed artifacts. Preparation source performs only local materialization; it refuses replacing an existing manifest. P3 corpus/source rows were not copied or mutated by this script or reviewer.

## Explicit remaining boundaries

- Fixtures say NOT_SEEDED. Unique generated UUIDs are not live database absence evidence; actual fresh ownership/conversation absence must be checked before seeding.
- New tenant names alone do not prove no documents. Positive document/combined question answerability and no-document tenant emptiness remain DB/corpus verification obligations.
- Seeding must preserve chronological sequence, exact contents/roles/tenants, no partial exchanges, paired equivalence and target fact outside the actual effective window; current input review is not evidence of successful DB preparation.
- Exact deployed image/source/effective config/provider network pins and runner pins are not present/accepted by this review. manifest.json by itself is not a ready-to-admit runner packet.
- P3 tenant/fingerprint, model, thresholds, provider behavior, concurrency and accounting remain under their prior approved contracts. This structural PASS does not authorize bypassing campaign STOP/admission or fixture preflight.

Exact independent command:

```sh
unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp/orq41-tenant-review-home AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard:/home/matias/Cursor/llm-chat-platform P2_NET_AUDIT_LOG=/tmp/orq41-fixture-review-net.log .venv/bin/python .framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/fixture-review/verify.py
```

Result: PASS,168 entries/40 paired identities/20 actual window checks. No escalation, sockets, database, API/provider calls, external network, paid spend, original artifact changes or source fixes. Only fixture-review evidence was created. Existing paid authorization is separate from demonstrated readiness.
