# ADR-006: RAG Corpus — Embedding Space, Row-Level Security, and HNSW Parameters

**Date:** 2026-07-29
**Status:** Accepted
**ORQ reference:** ORQ-21
**Superseded by / Supersedes:** —

---

## Context

The RAG baseline (`.framework/orqs/ORQ-21-rag-baseline/spec.md`) introduces the first genuinely
sensitive shared data in the system: a document/chunk corpus indexed with vector embeddings. This
ADR fixes the three decisions that constrain every later implementation task and are expensive to
undo once the corpus is populated: the embedding provider and dimension, the isolation control for
the corpus, and the HNSW index parameters.

ADR-003 §3 documented "application-layer scoping" as the enforcement approach for multitenancy,
with Row-Level Security explicitly deferred to ORQ-21. ADR-004 §5 extended that deferral to the
conversation/message read endpoints and stated it would be "resolved by RLS in ORQ-21." That is
imprecise: ORQ-21 implements RLS for the new RAG corpus only. `conversations` and `messages` are
untouched by this ORQ — the ADR-004 deferral is **re-targeted** to a future ORQ that owns applying
RLS to those tables, not closed here.

---

## Decision

### 1. Embedding provider and dimension — OpenAI `text-embedding-3-small`, 1536 dimensions, global

The corpus uses a single, corpus-level embedding provider and dimension rather than tracking each
tenant's chat provider. Reasoning:

- All vectors in one table must share one embedding space, or cosine distances between them are
  meaningless. The embedding provider is therefore a property of the corpus, decoupled from the
  per-tenant chat provider selected via `ProviderPort`.
- Cost is negligible for this corpus (~USD 0.02 per 1M tokens).
- The `httpx` adapter pattern used for the existing OpenAI chat provider extends directly to an
  embeddings call.
- 1536 dimensions sits under pgvector's 2000-dimension HNSW indexing ceiling.
- The OpenAI `dimensions` parameter is an escape hatch for later truncation without switching
  provider.

Changing the embedding provider or dimension after the corpus is populated requires a full
re-embed of every chunk — there is no in-place migration path, since distances across two
embedding spaces are not comparable.

### 2. Row-Level Security, enforced against a role that cannot bypass it

The existing Compose stacks provision the database via `POSTGRES_USER`, which the official
Postgres image makes a `SUPERUSER`. Superusers bypass RLS unconditionally, and `FORCE ROW LEVEL
SECURITY` does not cover the table owner. Policies written against today's single credential would
therefore be inert regardless of how they are written.

We introduce a dedicated application role — non-owner, non-superuser, without `BYPASSRLS`, holding
only DML grants on `documents` and `chunks` — reached through a new `DATABASE_URL_APP` setting.
Migrations and `CREATE EXTENSION vector` continue to run under the existing privileged role; the
application role is provisioned once, cluster-level, from a `/docker-entrypoint-initdb.d/` script
reading `POSTGRES_APP_PASSWORD` from the environment.

Policies are `FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK
(tenant_id = current_setting('app.tenant_id', true))`. `WITH CHECK` is explicit so that a `FOR
SELECT`-only policy cannot leave inserts unpoliced — an insert carrying a foreign `tenant_id` is
rejected by the database, not by application code. `FORCE ROW LEVEL SECURITY` covers the owner
case. In the absence of a set GUC, `current_setting(..., true)` returns `NULL` and the equality
comparison filters every row: the policy fails closed by construction, not by convention.

`DATABASE_URL_APP` must not silently fall back to `settings.database_url` — that would reconnect
as the superuser and make every policy inert with nothing failing loudly, reintroducing exactly the
problem this decision exists to solve. Readiness asserts that `current_user` holds neither
`rolsuper` nor `rolbypassrls`, turning "RLS is enforced" from a documentation claim into a runtime
invariant checked on every readiness probe.

Both the GUC placement (an `after_begin` event on a sync `Session` subclass, wired via
`sync_session_class=` into `init_db`) and the ingestion pipeline connecting through
`DATABASE_URL_APP` are implementation detail specified in `spec.md` §Design decisions 5 and 8; this
ADR fixes the policy shape and the role boundary, which is the part that would be expensive to
change after the corpus is populated.

This deferral is **local to the RAG corpus**. RLS on `conversations`/`messages` — the actual
subject of the ADR-004 §5 deferral — remains open, re-targeted to a named follow-up ORQ that owns
applying this same role-split pattern to those tables. It is not solved as a byproduct of this ADR.

### 3. HNSW parameters

The vector index uses pgvector's default HNSW parameters (`m=16`, `ef_construction=64`). At the
size of this corpus (a few thousand chunks), the runtime knob that actually matters is
`ef_search`, which is documented as a query-time setting rather than tuned in this ORQ.

### 4. Shared HNSW index with RLS filtering, partitioning deferred until measured

One HNSW index covers all tenants; Row-Level Security filters the result of the index scan rather
than each tenant getting its own index. This is the correct trade-off at the current corpus
volume — a few thousand chunks — where the cost of maintaining per-tenant indexes is not justified.

The evolution trigger is measurable, not assumed: if the ORQ-22+ evaluation harness shows
per-tenant `recall@k` degrading on the shared index (RLS filtering after an approximate-search
index scan can under-return true neighbors when a tenant's rows are a small fraction of the
corpus), the migration is to partition `chunks` by `tenant_id`, with one partition and one HNSW
index per tenant. This is a pure schema and storage change — `VectorStorePort`, the retrieval
queries, and the RLS policies are unaffected, since the port already addresses rows by tenant
context rather than by physical index. Not implemented now; the trigger can only be evaluated once
the harness exists.

### 5. The `tsvector` column is application-written, not generated

The keyword-search leg of hybrid retrieval indexes a `tsvector` computed over the chunk text. This
column is written by the ingestion pipeline rather than declared as a PostgreSQL generated column,
because a generated column takes one fixed expression for the whole table. Contextual retrieval
(§6) computes the embedding and the `tsvector` over `context || text` when enabled and over `text`
alone when it is not — a single generated-column expression cannot express both, so the ingestion
pipeline owns writing the column in either mode.

### 6. Contextual retrieval — capability shipped behind a default-off flag

Ingestion supports an optional `--contextualize` flag, off by default in this ORQ. When enabled,
each chunk is prefixed with one or two LLM-generated sentences situating it in its source document
before embedding; the original chunk text is preserved separately for the augmented prompt. This
targets orphan chunks — fragments like "the function returns `None` if..." that lose retrievability
once separated from their surrounding context — which is a known high-return improvement over
plain chunking, at a one-time ingestion cost per chunk and with zero change to retrieval
architecture.

Generation reuses `ProviderPort` with a fixed prompt and the cheapest model of the configured
provider, so no provider-specific logic enters the pipeline. This ORQ ships the capability without
claiming it improves retrieval: whether it does is an empirical question for the ORQ-22 evaluation
harness, which can run the same golden dataset against a corpus indexed with and without the flag
and compare `recall@10`/`MRR`. The document's indexing mode is persisted so a corpus built in mixed
modes is never silently compared against itself.

---

## Consequences

### Positive

- Corpus isolation becomes a database-enforced invariant, verifiable independently of application
  code, rather than a convention every future read path must remember to apply.
- The embedding space is fixed and documented before any chunk is embedded, avoiding a partial
  re-embed if the decision were revisited mid-ingestion.
- The shared-index and contextual-retrieval decisions are recorded with explicit, measurable
  triggers for revisiting them, rather than left as undocumented assumptions the next ORQ has to
  rediscover.

### Negative / Trade-offs

- **Dual external-provider dependency.** The RAG pipeline now depends on two external providers:
  OpenAI for embeddings (this ORQ) and AWS Bedrock for reranking (ORQ-22). This is an accepted
  trade-off, not an oversight — Bedrock Rerank is the reranking approach ORQ-22 specifies, and
  OpenAI embeddings are the corpus-level constant fixed here. If a tenant requires an AWS-only
  deployment, the documented escape is a full corpus re-embed with Titan Embeddings; the cost is
  bounded by corpus size and was already implied by "changing the embedding provider later is a
  full re-embed" in §1. **Operational note, not a blocker for this ORQ:** the AWS credential pair
  was revoked during ORQ-20 and has not been replaced. ORQ-21 touches only OpenAI and proceeds
  unaffected; a working credential pair must exist and be verified before any Bedrock-dependent
  work in ORQ-22 begins.
- A dedicated application role and credential add one more piece of infrastructure to provision and
  keep out of version control (`POSTGRES_APP_PASSWORD` via `.env`, never a literal in
  `alembic/versions/` — this repository is public).
- The application-layer scoping pattern from ADR-004 is deliberately not reused for this corpus.
  Two enforcement patterns for tenant isolation now coexist in the codebase (application-layer for
  `conversations`/`messages`, RLS for the RAG corpus) until the ADR-004 deferral is eventually
  picked up.
- Contextual retrieval, when enabled, multiplies ingestion cost by roughly one LLM call per chunk;
  over this repository's corpus that is minutes rather than seconds of ingestion time. Off by
  default in this ORQ specifically to keep that cost opt-in until the harness justifies it.

---

## Alternatives Considered

### Alternative A: Per-tenant embedding provider, matching each tenant's chat provider

Rejected. Vectors from different embedding spaces are not comparable by cosine distance; a
per-tenant provider would fragment the corpus into incompatible sub-indexes and break any
cross-tenant retrieval tooling (e.g., evaluation harnesses comparing recall across tenants).

### Alternative B: Reuse the ADR-004 application-layer scoping pattern for the RAG corpus

Rejected for this data specifically. The RAG corpus is the first data in the system where a single
missed `.where(tenant_id == ...)` in a new query path directly leaks another tenant's private
documents into a retrieval-augmented prompt. Postgres RLS moves that guarantee to the database,
where it holds regardless of which future code path queries the table.

### Alternative C: Per-tenant HNSW index from the start

Rejected for this ORQ. At current corpus volume the operational cost of one index and one set of
tuning parameters per tenant is not justified, and the shared-index-with-RLS-filter approach is the
standard pattern for this scale. Documented in §4 as a measured, not assumed, migration trigger for
when the corpus and tenant count grow.

### Alternative D: Default `--contextualize` to on

Rejected. The ROI is well-documented in general RAG literature but unverified against this
project's specific corpus (mixed prose and code) and golden dataset. Shipping it off by default
keeps the ORQ-21 baseline comparable to a plain-chunking corpus and leaves the A/B evaluation to the
ORQ-22 harness, which is the only place the claim can be falsified with this project's own data.

---

## Retrieval golden set (AC2)

Registered before running (spec.md AC2): 10 prompts against this repository's real corpus, each
with the source document expected in the top 5 hybrid-search results. Chosen for content that is
distinctive to a single document, to keep the pass/fail judgment unambiguous.

| # | Prompt | Expected source document |
|---|---|---|
| 1 | Why does this platform favor capabilities over a central execution orchestrator? | `docs/adr/001-capabilities-first-over-execution-orchestrator.md` |
| 2 | How does multitenancy propagate the tenant id through streaming responses? | `docs/adr/003-multitenancy-transversal-foundation.md` |
| 3 | What cross-tenant conversation read leak was found and how was it fixed? | `docs/adr/004-tenant-scoping-read-endpoints.md` |
| 4 | Why was a managed PaaS chosen for staging deployment instead of self-hosting? | `docs/adr/005-paas-provider.md` |
| 5 | Why is the RAG embedding provider a single corpus-level constant rather than per-tenant? | `docs/adr/006-rag-corpus-embeddings-and-rls.md` |
| 6 | Why must the pytest suite not depend on a developer's .env file? | `docs/testing.md` |
| 7 | What HTTP status code is returned when a URL is in the blocked domains list for web read? | `docs/error_decision_table.md` |
| 8 | What two controlled read-only external capabilities does the platform expose separate from /chat? | `docs/external_read_capabilities.md` |
| 9 | How does the pure-ASGI tenant middleware extract the tenant id from a request? | `app/http/middleware/tenant.py` |
| 10 | What is the exponential backoff and jitter formula used to retry a provider call? | `app/core/utils/retry.py` |

**Result (2026-07-30, real OpenAI embeddings, real corpus): 10/10 passed.** Full ingestion of this
repository (108 documents, 1817 chunks — `docs/private/` excluded as gitignored) against a
throwaway `pgvector/pgvector:pg16` container; each of the 10 prompts above embedded with the same
`text-embedding-3-small`/1536 configuration and queried via `PgVectorStore.hybrid_search`
(`top_k=20`). Raw top-5 source-document output for every prompt recorded in
`.framework/orqs/ORQ-21-rag-baseline/implementation.md` (Task 6 evidence).

**Role note (Execution Review R2):** the 108-document / 1817-chunk counts above were taken with
the privileged (superuser) role — correct for counting, since that's the role the ingestion
script writes as, but RLS does not apply to it. These counts are not isolation evidence. Tenant
isolation is AC3/AC8, verified separately under the unprivileged `rag_app` role in
`tests/core/test_rag_rls.py`.

## Evidence

- `.framework/orqs/ORQ-21-rag-baseline/spec.md` — Design decisions 1, 3, 4, 5, 6, 8, 9; Acceptance
  criteria AC1–AC3, AC8
- ADR-003: `.framework/constitution` multitenancy foundation — RLS deferred to ORQ-21
- ADR-004 §5: read-endpoint tenant scoping — RLS deferral re-targeted here to a future ORQ that
  applies this pattern to `conversations`/`messages`
- `.framework/constitution/tech-stack.md` §Known debt: RLS line re-targeted, not removed
- Independent design review (2 rounds) and orchestrator Early Design Review (1 round, addendum
  F6), recorded in `spec.md` front-matter `reviewed_by`
