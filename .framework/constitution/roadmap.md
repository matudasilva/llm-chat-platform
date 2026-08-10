**Authorship:** operator + agent (derived from the Notion Master Project Document and V2 ORQ history)
**Date:** 2026-07-21
**Version:** v1

# Roadmap — LLM Chat Platform

> Ordering is subject to revision. Deviating is not drift as long as the change is
> recorded in an ADR. The authoritative live state lives in the Notion Master
> Project Document; this file is the local AIT V3 planning surface.

## Phase 0 — V1.1 clean closure — ✅ done

Left V1.1 without blocking debt and installed the anti-drift machinery: `docs/adr/`
with the same-PR rule, a CI reconciliation check, ORQ history reconciliation, and
the `v1.1-stable` tag.

## Phase 1 — V2 core — ✅ substantially delivered

- Retroactive ADR-001: capabilities-first instead of orchestrator-first.
- External capabilities: controlled web read, Notion read via MCP, Notion write
  behind a safety contract.
- Foundational multitenancy (ADR-003): `tenant_id` on `Conversation`/`Message`,
  pure-ASGI `TenantMiddleware` registered last (Starlette LIFO), `ContextVar`
  propagation, tenant-namespaced cache keyed on the message list passed to it.
  **Correction (2026-08-10, manual testing during ORQ-26 review):** ADR-003 and
  this roadmap both described the fingerprint as hashing "the full message
  list", read by a prior version of this bullet as full conversation history.
  It is not: `app/api/routes/chat.py` has never built that list with more than
  the single incoming message, in any commit. The fingerprint fix was real (a
  list-shaped hash instead of a bare string) but had nothing to omit, because
  no history was ever assembled upstream of it. See the new "still open" item
  below.
- Cross-tenant read-path leak closed via service-layer scoping (ADR-004).
- Local test suite hermetized.
- Minimal chat frontend, tenant-aware, in a separate repository; SSE framing
  and GFM tables. **Correction (2026-08-10):** the "message-order fix" here
  was frontend-only — `useChat.ts` sorts with a role-based tie-breaker when
  `created_at` ties (same transaction, same `func.now()`), documented at the
  time as `ORQ-19.1`'s workaround with the real backend fix named as
  "ORQ-19.2" and deferred. `ORQ-19.2` was never claimed. The backend's own
  `ORDER BY created_at ASC, id ASC` (`app/services/conversation_query_service.py:47`)
  still ties on a random UUID when timestamps match, so any client reading the
  API directly (not through the frontend workaround) can still see a reply
  ordered before the question that produced it. See the new "still open" item
  below.
- Dev→Prod Option A (ADR-005): image pipeline to GHCR, thin deploy repository,
  staging on PaaS with serverless Postgres and Redis, end-to-end SSE verified.

**Still open in this phase:**
- Execution Orchestrator + Tool Calling Engine, and the `ChatService` refactor
  that uses them — deferred by ADR-001, not cancelled.
- Default provider moved off `stub` to a live-validated OpenAI/Bedrock. Partial
  evidence: manually re-validated live against both Bedrock and OpenAI on
  2026-08-10 (ordinary chat + the multi-turn-memory probe below), but that was
  ad hoc testing during a review session, not a dedicated ORQ's evidence — this
  item stays open until one exists.
- Backend sequencing via `GENERATED ALWAYS AS IDENTITY` instead of
  timestamp-based ordering (proposed follow-up from the SSE fix, `ORQ-19.2` in
  the original V2 numbering, never claimed). **Next to be claimed** (operator
  decision 2026-08-10) as a narrowly-scoped ORQ — schema + `ORDER BY` change
  only, no RLS, no `usage_events` work folded in even though both touch
  adjacent tables, per the same narrow-scope precedent as the ORQ-26 split
  (see Phase 2 item 1).
- **Conversation history is never sent to the provider.** Moved to Phase 2 as
  RAG work (operator decision 2026-08-10) — see "Conversational memory via RAG"
  below. Kept as a one-line pointer here, not restated, so a reader scanning
  Phase 1 debt still finds it (ORQ-15 single-source-of-fact: the description
  lives in Phase 2 only).
- **RLS on `conversations`/`messages` remains unenforced.** Already referenced
  in Phase 2 item 1 above and `docs/adr/004-tenant-scoping-read-endpoints.md`
  and `docs/adr/006-rag-corpus-vector-store.md` §RLS discussion (single source
  of fact, not restated here) — recorded in this list only so it is visible
  next to the other still-open Phase 1 items rather than requiring a reader to
  already know to look inside ORQ-21's bullet. Verified live 2026-08-10:
  `relrowsecurity = false` on both tables.
- **`usage_events.tenant_id` is still missing.** No column exists on
  `usage_events` (verified live 2026-08-10). Deferred since ORQ-18.2 pending a
  cost-pipeline analysis that was never scheduled as its own ORQ.

## Phase 2 — Retrieval (RAG) + Routing — next

RAG enters as a **separate read capability**; it does not touch the `/chat`
invariant.

1. **RAG baseline** — split by the operator across two ORQs (see ORQ-21 §Scope):
   - ✅ done (ORQ-21, closed locally 2026-08-03): pgvector on the existing
     Postgres behind a `VectorStorePort`; API-first `EmbeddingPort`
     (OpenAI `text-embedding-3-small`, 1536 dims); hybrid retrieval (semantic +
     keyword, RRF fusion); tenant-scoped corpus and Postgres RLS against a
     genuinely unprivileged role (settles the ADR-004 §5 deferral for the RAG
     corpus specifically — `conversations`/`messages` RLS is still open, see
     `docs/adr/004-tenant-scoping-read-endpoints.md`).
   - ✅ done (ORQ-22, closed locally and merged 2026-08-04): isolated reranking
     benchmark measured the RRF baseline, GCP, AWS, and Qwen over one frozen
     dataset. The evidence outcome is recorded once in §Decisions closed by ORQ;
     ADR-006 remains unamended.
   - ✅ done (ORQ-23, fully synced 2026-08-05, merged to `main`): query rewrite
     via `ProviderPort` → `hybrid_search` → the incumbent AWS reranker (per
     the closed ORQ-22 outcome above, `us-west-2`) → a lightweight,
     conditional post-rerank evaluator (no agentic loop, count-based `R < M`
     trigger, never `relevance_score`), exposed as a new tenant-scoped read
     endpoint (`POST /rag/retrieve`). Still disconnected from `/chat` and
     `rag_enabled`/`retrieval_pipeline_enabled` stay `False` by default —
     activation is a deploy-time decision, not part of this ORQ. Golden-set
     regression 10/10 (rewrite ON and OFF, real corpus). Narrower than
     earlier drafts of this bullet — see below for what moved out. Split
     adopted from the Notion master doc ("LLM Chat Platform — Documento
     Maestro de Proyecto", v1.2, 2026-08-03) §10 items 11–13, which
     supersedes the single bundled "follow-up ORQ" this bullet used to
     describe.
   - ✅ done (ORQ-24, fully synced 2026-08-06, merged to `main`): reranker availability —
     `CascadingRerankerAdapter` makes GCP Vertex the primary production
     reranker, AWS Bedrock the automatic fallback. Triggered by ORQ-23's
     closure-pass finding that AWS Bedrock Rerank's account quota for
     `amazon.rerank-v1:0` is a hard, non-adjustable 2 requests/minute
     (`aws_quota_finding.md`) — confirmed in both `us-west-2` and
     `ca-central-1`, so region choice does not relieve it. ORQ-22's tied
     benchmark meant no quality trade-off in switching primaries. See
     `docs/adr/007-reranker-availability-cascade.md`. This ORQ claims the
     number the "RAG generation" bullet below previously held; that item
     renumbers to ORQ-25, and the evaluation-harness item renumbers to
     ORQ-26.
   - ✅ done (ORQ-25, fully synced 2026-08-07, merged to `main`): `/chat`
     generation now assembles an augmented prompt with retrieved chunks via
     `ProviderInput.metadata`, emits structured `sources` in non-stream JSON
     and SSE `done`, and supports lightweight answer feedback by updating the
     existing `UsageEvent`. Local browser validation also confirmed the
     separate `llm-chat-platform-web` client can consume the augmented stream
     over CORS, inspect the final `sources` payload, and submit feedback.
     This is where the answer-generation step and its system prompt landed —
     the item originally flagged as "not yet scoped in any ORQ" by
     `fw-replan` (2026-08-03), previously numbered ORQ-24. **Closure correction
     (2026-08-07):** "merged to `main`" covers the backend only. The frontend
     half of this ORQ is commit `f79f920` in `llm-chat-platform-web`, still
     unpushed; ORQ-26 carries pushing it as a prerequisite.
   - The master doc's single "Evaluation and harness" item was **split into
     three ORQs by the operator on 2026-08-07**, after an Early Design Review
     found the combined scope violated this roadmap's own ORQ-23 precedent
     (narrowing so an item does not grow into a second RAG-baseline-sized ORQ).
     The split renumbers everything below it by two. The three slices cut on
     what each one needs: ORQ-26 needs no LLM judge, ORQ-27 introduces one,
     ORQ-28 needs a second corpus ingestion.
   - ✅ done (ORQ-26, 5 review rounds — round 4 blocked on a corpus-fingerprint
     gap that round 5 closed and re-verified live with all three test DSNs and
     `pgvector` installed — merged to `main` 2026-08-10): frozen bilingual golden
     set derived from `experiments/reranking/ground_truth.jsonl` — already 30
     bilingual pairs with labels declared before retrieval ran, so the master
     doc's "expand to 30 prompts" is satisfied and the work is promoting them to
     a first-class asset. Retriever metrics `recall@10`, `MAP@10`, `MRR@10` in
     an MLflow-compatible Postgres schema created outside the Alembic chain.
     Answers one question: under a frozen configuration, does the deterministic
     candidate generator retrieve the labelled documents?

     **Correction (2026-08-08, external review round 2):** this bullet said
     "answers one question: is the retriever the problem?". That overclaims.
     The harness measures `PgVectorStore.hybrid_search` alone; production
     retrieval also rewrites the query and reranks, so a good score here does
     not clear the production path and a poor one does not by itself indict it.
     Claims about production retrieval belong to ORQ-27. See ADR-009.

     **Correction (2026-08-07):** an earlier revision of this bullet said the
     tautological golden-set prompt 5 was "carried as `q016`". That conflated
     two different sets. ADR-006 embeds all ten of ORQ-21's prompts verbatim
     (§Retrieval golden set) and ADR-006 is itself ingested, so each of those
     ten matches its own expected document lexically — that is the R3 defect.
     None of the 30 reranking queries appears in ADR-006, verified by exact
     string search; `q015`/`q016` asks a legitimate question that happens to
     expect ADR-006. So the derived set needs no replacement pair, and ORQ-26
     instead asserts the general property: no golden-set query text may appear
     in any ingested document.

     The readable citation label (`source_path` on `RagSourceOut`) is *not*
     part of this ORQ. The metrics resolve `source_path` with a post-query
     lookup and zero production diff, exactly as
     `experiments/reranking/build_dataset.py` already does, so the two do not
     share a dependency. It remains an unscheduled follow-up, to ride along
     with a future ORQ that already touches the retrieval path.

     **Pending renumbering note (2026-08-10):** the message-ordering item
     (Phase 1, "still open") is next in line to be claimed via
     `fw_claim_orq_number.py`, ahead of any item below. Numbers are assigned
     strictly by claim order (`max(existing tags/branches) + 1`), not by this
     document's draft labels — none of ORQ-27 through ORQ-32 below has a
     branch or reservation tag yet, so claiming the ordering item now will
     take the number **27**, shifting every draft number below down by one
     (RAG answer quality becomes ORQ-28, and so on through AI Green becoming
     ORQ-33). This bullet list keeps its current draft numbers until each item
     is actually claimed, at which point its real number replaces the draft
     one here — same convention as every prior renumbering in this section.
   - **Conversational memory via RAG** (not yet claimed, unnumbered — sequenced
     after the Phase 1 message-ordering ORQ claims its number): `app/api/routes/chat.py`
     builds `_messages = [ChatMessage(role="user", content=payload.message)]` —
     one message, always, regardless of `conversation_id`; `ChatService.run`
     accepts a full `Sequence[ChatMessage]` and is provider-agnostic, but
     nothing upstream of it ever supplies more than the current turn.
     Reproduced live 2026-08-10 against both Bedrock and OpenAI (identical:
     the model denies being told anything in a prior turn of the same
     conversation). First named as deferred debt in `ORQ-19` Design Review
     finding F3 (2026-07-02), candidate for "a future backend ORQ" that was
     never claimed — see `.framework/learnings.md` (2026-08-10 governance
     entry) for how it fell out of the V2→V3 transition.

     **Design direction (operator decision 2026-08-10):** solve it with RAG
     rather than full-history replay — embed each turn and retrieve the top-k
     most relevant prior turns of the *same* `conversation_id` via
     `PgVectorStore`/`VectorStorePort`, the same infrastructure already built
     for `documents`/`chunks`, applied to `messages` instead. Reuses embedding
     + hybrid retrieval rather than growing token cost linearly with
     conversation length. **Scoped strictly to within one conversation** —
     cross-conversation / long-term per-tenant memory ("remember me across
     sessions") is explicitly *not* included here; noted under §Open decisions
     as a future RAG improvement candidate, not committed to any ORQ.
     Needs its own spec (retrieval `top_k`, embedding-write path on every
     turn or lazy/batched, interaction with the existing Redis response
     cache's fingerprint, token/cost impact relevant to Phase 3's per-tenant
     accounting) before implementation — a design decision, not a mechanical
     fix like the ordering item in Phase 1.
   - **ORQ-27 — RAG answer quality** (not yet claimed): RAGAS `faithfulness`
     and `response_relevancy` as LLM-as-judge signals, judged by a non-OpenAI
     model in an optional dependency group that never reaches any image;
     diagnostic separation (low recall indicts the retriever, low faithfulness
     indicts the generator) computed from pre-registered thresholds; and judge
     *stability* evidence as its own assertion, since replaying cached bytes
     proves harness determinism and nothing about a managed endpoint — the
     distinction ORQ-22 §Design decisions 5 already learned. Adjust the RAG
     prompt/citation guidance only if the evidence shows retrieval is correct
     but the answer still underuses the best chunks.
   - **ORQ-28 — Contextual retrieval A/B** (not yet claimed): falsify the
     `--contextualize` ROI that ADR-006 §Alternative D deliberately left
     unverified, with both arms ingested from one commit under two tenants and
     a pre-registered decision rule. A whole experiment, not a task: the
     contextualized arm is roughly 1817 provider calls, and the arm must prove
     it contextualized with a real provider — the default is still `stub`, and
     `indexing_mode` is set from the CLI flag without checking that
     contextualization produced anything.
   - The shared-index partitioning trigger stays deferred until ORQ-26 shows
     measured recall degradation on the shared HNSW index — unchanged from
     ADR-006 §4.
   - **ORQ-29 — RAG in Production** (not yet claimed): end-to-end observability
     and hardening following ORQ-26/27 baseline metrics. Prerequisites: ORQ-23,
     24, 25 operationally stable, baselines established. Scope: complete
     OpenTelemetry instrumentation (`retrieve → rerank → generate` spans —
     including the emission the master doc assigned to the evaluation item, moved
     here so instrumentation is designed once with its backend), Phoenix/Grafana
     dashboard, adversarial robustness hardening, cost/latency tuning. Design
     Review prompt deferred pending Module 5 of the RAG course. Numbered ORQ-27
     before the 2026-08-07 split.
2. **ORQ-30 — Routing evidence dataset** (not yet claimed): `RoutingPolicy`
   interface with heuristic and static implementations by default; collect real
   signal before any model. Numbered ORQ-22 in the original plan, then ORQ-28
   before the 2026-08-07 split. Convergence note: the Agentic RAG LLM router is
   conceptually the same classifier, so once ORQ-29/ORQ-30 produce real signal,
   the RAG router design follows at no extra cost.
3. **ORQ-31 — Offline ML routing baseline** (not yet claimed): a simple,
   explainable model, and only if ORQ-30's evidence dataset shows real signal.
   Numbered ORQ-23 in the original plan, then ORQ-29.

Reusable precedent: for broad or multilingual queries, reranking alone is not
enough when the initial candidate set is poor — intent detection plus an
"overview" canonical query expansion plus path-priority reranking is the pattern
that worked. Relevant here because project documentation is bilingual.

## Phase 3 — AI Green extension

**ORQ-32 — AI Green extension** (not yet claimed). Numbered ORQ-24 in the
original plan, then ORQ-30 before the 2026-08-07 evaluation split. Sequenced as
energy telemetry → carbon-aware routing → scheduler, and gated on ORQ-30
producing real routing signal. Convergence note: Adaptive RAG rests on the same
principle — spend the cheapest resource that still answers the question.

Fits as an extension, not a rewrite; each piece maps to an existing component.

- Per-request energy/CO2e telemetry extending `UsageEvent` / `ProviderResult`.
- Carbon-aware, small-first routing extending `RoutingPolicy`.
- Semantic caching extending the Redis layer.
- Green LLMOps dashboard on MLflow/Grafana.
- Horizon: a carbon-aware scheduler with batch/deferred modes.

Transversal multitenancy enables the per-tenant accounting (tokens, cost, energy,
CO2e) this phase depends on.

## Open decisions

- Energy/CO2e estimation methodology per request.
- Default model and routing escalation thresholds.
- **Cross-conversation / long-term memory via RAG** (raised 2026-08-10, operator
  decision when scoping "Conversational memory via RAG" in Phase 2). Same
  retrieval mechanism as within-conversation memory, but over a corpus that
  spans a tenant's conversations rather than one `conversation_id` — "remember
  what I told you last week" instead of "remember what I told you five
  messages ago". Deliberately not committed to any ORQ yet: needs its own
  privacy/retention model (how long a fact persists, whether a user can clear
  it) that within-conversation memory does not, and depends on the
  within-conversation version shipping first to reuse its embedding-write
  path rather than building two parallel mechanisms.
- **Moving the embedding provider off OpenAI** (raised 2026-08-07). The operator
  intends to consolidate GenAI spend on Bedrock/GCP, where credits are
  available; generation already runs on Bedrock, so embeddings are the last
  OpenAI dependency. Not scheduled in any ORQ. This is not a config change:
  ADR-006 §1 fixes `text-embedding-3-small` at 1536 dimensions as a
  corpus-level constant, another provider likely changes the dimension, and the
  pgvector column is dimension-typed — so it implies a schema migration plus
  full corpus re-ingestion, and warrants its own ORQ. Decide it with ORQ-26's
  harness rather than by intuition, mirroring how ORQ-22's frozen dataset
  justified the reranker choice before ORQ-24 acted on it. ORQ-26 deliberately
  does not add provider dispatch to the embedding factory — its harness takes an
  injected `EmbeddingPort` instead, so this decision stays unmade rather than
  half-made. Amends ADR-006 when taken. Related: the same rationale drives the
  reranker's planned AWS→GCP swap.

## Decisions closed by ORQ

- **Embedding provider and dimension** (ORQ-21, 2026-07-29): OpenAI
  `text-embedding-3-small` at 1536 dimensions, a corpus-level constant
  independent of each tenant's chat provider. Full rationale:
  `docs/adr/006-rag-corpus-embeddings-and-rls.md` §1.
- **Reranker benchmark outcome** (ORQ-22, 2026-08-04): AWS, GCP and local Qwen
  tied on every pairwise pre-registered quality metric, so the evidence does not
  justify overturning ADR-006's AWS incumbent for the retrieval-pipeline
  follow-up. This confirms the existing direction rather than amending the ADR;
  cross-provider latency remains indicative only. Full evidence:
  `docs/reranking_benchmark.md`.
- **Production reranker region correction** (ORQ-23, 2026-08-05): the AWS
  reranker's default region moved from `ca-central-1` (ORQ-22's fastest-latency
  probe, not a quality result) to `us-west-2` (the region ORQ-22's actual tied
  quality benchmark ran against). No ADR amendment — same incumbent backend,
  corrected region evidence.
- **Reranker primary switched to GCP, AWS demoted to fallback** (ORQ-24, 2026-08-06): AWS Bedrock
  Rerank's account quota for `amazon.rerank-v1:0` measured at 2 requests/minute
  (`QuotaAppliedAtLevel: ACCOUNT`, `Adjustable: false`, confirmed in `us-west-2` and
  `ca-central-1`) — a real production ceiling, not a test-burst artifact. GCP Vertex becomes
  primary via `CascadingRerankerAdapter`; AWS stays as an automatic availability fallback.
  Amends, does not supersede, ADR-006's quality rationale for AWS (unchanged, per ORQ-22).
  Full rationale: `docs/adr/007-reranker-availability-cascade.md`.

## Related

Purpose and boundaries: [[mission]] · Constraints and invariants: [[tech-stack]]
