# Balanced A/A packet prepared and independently reviewed

**BLOCKED_AA_HARNESS_REVIEW_PASS**. Packet261109141719 is prepared, not executed.
The operator authorized disposable preparation and then explicitly requested
independent review. No application request or performance sample ran. This PASS
cannot authorize the1,440-request calibration, formal G6 or a paid campaign.

## Frozen identities

Plan SHA-256: `ae37ecfb95379e52c8feff53fedfaabb83a99b2b3b6a7d61521cd58aaa7177bc`.
Fixtures SHA-256: `ab144380bd6254d706268c351d661d7ac970d12938a3ee9e04956368e517c3c9`.
The approved amendment and exact reviewed controller/worker/test source are
unchanged. Source identity is established by image/file hashes and the reviewed
source receipt, not a claim of a clean or newly committed worktree.

| Role | Immutable local Docker image ID |
|---|---|
| Both full-C1 A/A labels | sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707 |
| PostgreSQL/pgvector | sha256:8e5355e9ff399a002fa46148399a1ac22fb3e9b2d390f857296e6da6b5559ba1 |
| Redis | sha256:13105d2858ded45aedf7b24f0870e6a4e7ce4964924bffce68e562ca72149f1e |
| Local OTLP collector | sha256:50dccac76879873148242bb98c6472404f3af3388c318ef270a6912b855c2dbc |

These existing images were reused with pull=never; no image was acquired/built.
Worker resources are2CPU/2GiB on CPUs0,2; dedicated PostgreSQL2CPU/2GiB on4,6;
Redis/collector retain0.5CPU/256MiB caps. Configured/effective affinity, cgroup
quota and frozen topology/governor were verified. No exclusive CPU ownership,
constant-frequency, physical cache equality or statistical-equivalence claim.

## Actual preparation and verification

New dedicated services are orq41-blocked-261109141719-postgres/redis/collector.
The PG namespace has networknone; auxiliaries join only that namespace and no
ports are published. Services remain running and isolated. No API server or
measurement worker was deployed; API-image Settings/resource probes ran in
separate ephemeral network-none containers, without app lifespan or requests.
The historical source PG was accessed only through read-only schema/locale/
settings queries/dumps; its business data/schema were not modified.

Two fresh databases orq41_blocked_261109141719_c0/c1 each contain720conversations
and17,280exact history messages. Independent read-only fixture verification
checks UUID5 derivations, unique canonical IDs/sequences, content/tenant/order,
720request/conversation UUIDs disjoint from retained historical plans, and paired
logical equality. Corpus P3 remains124documents/2146chunks/1536dimensions:
fingerprint787ae13719ef23c5043449d7d2e84bd489e5896e18d0fe5a035f76e8c6df0999,
content SHA-2569fa959aeeb5d332882d61f60528eaa72468f110705c51ce05b70e213dd168506.
Restore/readback used the frozen snapshot; no ingestion/embedding/provider call.

Each disposable database received exactly the seven approved ANALYZE statements
after seeding. Read-only readback corroborates table inventories/completion
receipts and source-equivalent unchanged planner/autovacuum settings. RLS,
non-bypass rag_app/chat_ops roles, schema/locale and the precise reviewed source/
restore CHECK cast equivalence were rechecked. The same11-input truth table was
evaluated on source and both clones; no schema/constraint/grant was changed to
obtain equality. Fixture creation and role/schema bootstrap occurred only in the
new disposable cluster, following the approved existing procedure.

Effective Settings are equal after normalizing only paired database names;
full identities remain distinct and bound per arm. Settings checks require
fallbackNone, staticrouting, shadowOFF, local-only OTLP endpoint, loopback DB/
Redis and absent external credentials/integrations. Modelnemotron3/us-east-1
remains configured without invocation. Both actual startup probes agree on
seed41, string-hash928176814434627218 and Python3.13.15/siphash13/64bit.
Global dotenv was disabled. Readiness probes touched only local5432/6379/4318.

The parent executed independent-audit/verify_prepared_databases.py with READ ONLY
transactions and settings-only probes, obtaining
BLOCKED_AA_PREPARED_DATABASES_READONLY_VERIFIER_PASS. Adaptations from the prior
reviewed A/A verifier are retained in verifier-provenance.json. The distinct
reviewer inspected source/receipt but did not independently connect to SQL.
Additional environment-binding.json records sanitized Docker identities,
real coarse host/DB counters and reset checks. Credentials remain private in
/tmp; no environment secret values or full Docker Env array were retained.

## Prospective measurement and independent review

The exact approved1,440 slots comprise800measured+640warmups,32fresh workers,
four paired blocks/cell,20representative warmups then25measurements perworker.
Each arm/cell has100measurements/25percategory and balanced first/second order.
Original case contents, timing boundary, fullC1 accounting/native serialization
checks, request300s/cleanup10s bounds and symmetric5% rule are unchanged.
R=1/C=1/one attempt; no resend, replacement, correction or favorable repetition.
All historical AA/G6 FAILs remain; no performance value was produced here.

/root/packet_review independently checked typed manifest reconstruction,
protocol/fixtures/freshness/source/resource/config/seed/ANALYZE and evidence
bindings. independent-review.md/json records BLOCKED_AA_HARNESS_REVIEW_PASS and
binds plan/fixtures/preparation hashes required by the real admission guard.
No new BLOCKER/HIGH/MEDIUM was found in this scoped packet review. Parent SQL
execution is attributed explicitly. The prior167image tests and67independent
pure controls were reused through exact source/XML hashes; controls.xml is an
unchanged copy, not a new test execution. No new pytest was needed/run.

The real file-only preflight guard was then checked under P2: it rejected the
packet specifically because execution-authorization.json is absent, before
Docker or SQL. admission-guard.json records this. No execution-started marker,
per-worker admission marker, result or execution authorization exists. The only
persistent new containers are the three preparation services.

## Scope, cost and next authorization

All500 existing app/experiment/test/global-env files remain unchanged, including
app/, P5, the new reviewed harness and prior evidence. Only preparation/review/
evidence artifacts and minimal planning/handoff references were added. No
provider/retry/retrieval/SSE/persistence semantics, schema/grants outside the
disposable clone, global-env, model, threshold, accounting or host policy change.
P2 orchestration audit is empty/absent; namespace isolation and inspected code
paths support zero egress and external/provider calls. SpendUSD0, paidrequests0.
No G9, campaign, live G6/G7, Notion, commit, push or deployment.

Next requires explicit operator approval for this exactplan's single1,440-request
local-stub A/A execution. Recheck current source/settings/data/resources before
admission; any drift fails closed. Keep global In Progress / Implement /
DECISION_FREEZE_PASS, official CONTROLLED_G6_FAIL and
BLOCKED_CONTROLLED_G6_FAIL paid admission. A/A PASS would still require a separate
formal C0/C1 proposal/approval; it would not lift the paid block automatically.

