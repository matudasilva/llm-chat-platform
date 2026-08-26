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
     three draft slices by the operator on 2026-08-07**, after an Early Design
     Review found the combined scope violated this roadmap's own ORQ-23
     precedent. Only ORQ-26 was claimed under that draft sequence. Later
     operator decisions assigned ORQ-27 to conversational-memory research and
     ORQ-28 to deterministic message ordering; the answer-quality draft
     returned to the unnumbered backlog and contextual retrieval moved to the
     current ORQ-30 draft slot.
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
     Claims about production retrieval belong to a future answer-quality
     proposal, not to ORQ-26. See ADR-009.

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

     **Numbering correction (2026-08-10):** ORQ-28 was claimed and closed for
     deterministic message ordering. The operator then explicitly authorized
     reusing the inactive ORQ-27 reservation for conversational memory after
     verifying it contained no unique product commits; this is an override and
     intentionally does not call `fw_claim_orq_number.py`. ORQ-29 is now
     canonically reserved for the independently gated dual-memory successor;
     subsequent draft labels start at ORQ-30, and ORQ-28 is never reusable.
   - ✅ **ORQ-27 — CALMem-inspired episodic conversational memory experiment**
     (**CLOSED / VALIDATED, 2026-08-13; Gate 1 `NO_GO`**): the frozen
     teacher-forced offline experiment executed correctly, but the selected D1
     strategy passed only 16/20 conjunctive clauses. It failed registered
     preservation of recall and fact consistency versus bounded-history B,
     ambiguous-follow-up recall, and p95 TTFT. Gate 2 and Gate 3 were not
     authorized, no production runtime changed, ORQ-27 must not reopen, and its
     consumed held-out remains sealed. The verdict rejects D1 under that
     protocol; it does not reject all episodic memory or semantic memory.
   - ⏹ **ORQ-29 — Dual conversational memory successor** (**CLOSED LOCALLY,
     2026-08-14; `DEVELOPMENT INCONCLUSIVE — TARGET LONG-CONTEXT REGIME NOT
     EXERCISED`**): the approved development-only calibration completed with
     traceable evidence, but bounded-history B truncated in `0/48` steps,
     retained required gold evidence in `48/48`, and reached only `13.34%`
     maximum usable-capacity pressure. ORQ-29 therefore stopped before final
     pre-registration: no held-out was generated or accessed, no Gate 1
     `GO/NO_GO` verdict exists, and Gate 2/Gate 3 remain unauthorized. Results
     are frozen against post-hoc recalibration or reinterpretation. Any
     successor must use a different approved hypothesis, protocol, ORQ number,
     and completely new held-out. See ADR-010.
   - **Unnumbered candidate — RAG answer quality:** preserve the former ORQ-29
     draft as backlog: RAGAS `faithfulness` and `response_relevancy`,
     judge-stability evidence, and diagnostic separation between retrieval and
     generation. It has no reservation, branch, or implementation approval.
   - **ORQ-30 — Long-context conversational memory under operational context
     pressure — CLOSED — DEVELOPMENT STOP — REGISTERED 48-CONVERSATION
     CONFIRMATION UNDERPOWERED** (claimed by `ait-orq-number-ORQ-30`):
     independent successor to the closed ORQ-29, with a different hypothesis
     and protocol for evidence that is verifiably outside a bounded history
     window. This assignment supersedes the earlier unclaimed “Contextual
     retrieval A/B” placeholder; that experiment has no ORQ number or
     implementation authorization. **Closed 2026-08-20:** the valid
     replacement development execution showed event-level BM25 recovering
     out-of-window evidence (E-BM25 16/32 primary versus bounded-history B
     0/32, gold delivery 32/32, zero cross-tenant or cross-conversation
     delivery), but the effect was entirely heterogeneous by language — 16/16
     Spanish, 0/16 English — and the registered 48-conversation confirmation
     was underpowered. There was no pre-registration, held-out, confirmatory
     execution, Gate, or `GO`/`NO_GO` verdict; ORQ-30 must not reopen and its
     development evidence must not be reinterpreted as confirmatory. Full
     numbers and hashes:
     `.framework/orqs/ORQ-30-long-context-conversational-memory/closure.md`
     (single source of fact, not restated here). The EN/ES asymmetry is
     carried forward as ORQ-31 below.
   - **ORQ-31 — English-language failure diagnosis after ORQ-30 — CLOSED
     LOCALLY — FIRST OFFLINE DIVERGENCE LOCALIZED** (`ait-orq-number-ORQ-31`,
     closed 2026-08-21): the bounded diagnostic successor to ORQ-30 ran
     entirely offline, at zero provider/model/embedding cost, by
     deterministically reproducing ORQ-30's frozen E-BM25 replacement-development
     pipeline (dataset identity, 128/128 rebuilt requests, 64/64 primary
     request-hash matches — all confirmed against the recorded evidence).
     Retrieval and context assembly delivered the required gold evidence in
     16/16 primary steps for **both** languages; the frozen scorer reproduced
     the recorded outcome in 32/32 cases. The first observable EN/ES
     divergence in pipeline order is at **generation behaviour**: 16/16
     English primary steps recorded a uniform `abstain` decision, versus 16/16
     Spanish primary steps recording a correct answer. This is an
     **association, not a validated cause** — language stays confounded with
     `conversation_index`, and the underlying event/filler corpus content is
     English in both language groups, so only the query surface varies by
     language. ORQ-31 does not establish that query language causes the
     generation behaviour, does not reopen ORQ-30, and did not modify ORQ-30's
     evidence (integrity manifest identical open/close). Full evidence:
     `.framework/orqs/ORQ-31-english-failure-diagnosis/validation.md`
     (single source of fact, not restated further here).
   - **ORQ-32 — Controlled EN/ES generation-behaviour probe under matched
     retrieval success — CLOSED LOCALLY — LANGUAGE SWAP PARTIALLY REPRODUCES
     DIVERGENCE** (`ait-orq-number-ORQ-32`, closed 2026-08-25): the bounded,
     within-conversation matched-pair probe ORQ-31 proposed as its follow-up.
     For each of ORQ-30's 16 conversations, both primary steps were re-asked
     in the opposite language — same conversation, same delivered evidence
     (gold event delivered in 32/32 swapped requests), same frozen
     retrieval/assembly/framing code, only the query's language changed —
     dispatched for real (32 OpenAI `gpt-4o-mini-2024-07-18` calls, ≈USD
     0.0093 actual cost, well under the authorized USD 0.10 ceiling). Result:
     the Spanish-corpus→English-question direction reproduced ORQ-31's
     divergence fully (16/16 flipped to abstain); the English-corpus→
     Spanish-question direction reproduced it mostly, not fully (14/16
     flipped to a correct answer; conversations 01 and 04, step `_S00`
     only, did not flip). Per the classification rule fixed in the spec
     before dispatch, this mixed result closes as **partial**, not full,
     reproduction. This is a **stronger, more directly matched association
     than ORQ-31's, but still not a validated cause** — the design removes
     ORQ-31's `conversation_index` and corpus-language confounds by reusing
     the same conversation for both conditions, but the two-pair residual
     (n=2, no repeated sampling, one step type) leaves an interaction
     between query language and conversation-specific content unruled-out.
     ORQ-32 does not reopen ORQ-30 or ORQ-31, and neither's evidence was
     modified (integrity manifests identical open/close for both). Full
     evidence: `.framework/orqs/ORQ-32-controlled-en-es-generation-probe/validation.md`
     (single source of fact, not restated further here).
   - The shared-index partitioning trigger stays deferred until ORQ-26 shows
     measured recall degradation on the shared HNSW index — unchanged from
     ADR-006 §4.
   - **ORQ-33 — Conversational RAG Memory: residual diagnosis and minimal fix
     candidate — CLOSED LOCALLY — RESIDUAL DIAGNOSED, SAMPLING VARIANCE
     OBSERVED** (`ait-orq-number-ORQ-33`, closed 2026-08-26): repeated
     ORQ-32's exact recorded request 10 times each for the 2 residual pairs
     (conversations 01, 04) and 2 flipped controls (conversations 00, 02),
     40 OpenAI `gpt-4o-mini-2024-07-18` calls, ≈USD 0.0116 actual cost. The
     two residuals turned out to be qualitatively different, not one
     phenomenon: conversation 01 (`DEV_01_S00_LANGSWAP`) showed 9/10 answer,
     1/10 abstain — **run-to-run generation variability**, not a stable
     divergence; conversation 04 (`DEV_04_S00_LANGSWAP`) showed 10/10
     abstain — a **stable residual** repeated sampling does not explain. An
     offline structural comparison (token count, delivered-event-id
     sequence, full prompt text) against the 2 flipped controls found no
     structural or content anomaly beyond the expected per-conversation
     suffix — inconclusive on its own. Terminal label selected mechanically
     by the precommitted rule (triggered because at least one residual's
     samples included an answer) and does **not** mean both residuals were
     explained — conv04 remains open. No production fix validated; no
     causal claim made for either pair. Full evidence:
     `.framework/orqs/ORQ-33-memory-residual-diagnosis/validation.md`
     (single source of fact, not restated further here).
   - **Unclaimed successor candidate — Final offline residual
     characterization (`DEV_04_S00_LANGSWAP`)** (not yet claimed; operator
     framing recorded 2026-08-26): the memory-experimentation line continues
     only far enough to determine whether ORQ-33's one remaining stable
     residual has any concrete, reproducible, offline-visible discriminator
     from its nearest flipped controls (`DEV_00_S00_LANGSWAP`,
     `DEV_02_S00_LANGSWAP`, optionally one more `_S00_LANGSWAP` flip if
     needed to check uniqueness) — explicit goal is to **end** this
     experimentation line, not extend it indefinitely. Offline-first and
     diagnostic only: read-only inspection of already-produced ORQ-30/31/
     32/33 artifacts, deterministic recomputation via frozen tracked
     modules, token/structural/lexical/ranking/serialization comparison,
     nonce/suffix normalization — no provider/model/embedding calls, no
     repeated sampling, no new language swaps, no parameter sweeps, no
     retries, no ORQ-27 held-out, no ORQ-30–33 mutation, no production
     change, no fix implementation. Precommitted terminal rule, fixed before
     this candidate is planned: `CLOSED — OFFLINE DISCRIMINATOR FOUND` only
     if a concrete, reproducible, conv04-only, control-absent difference
     survives deterministic re-check and suggests exactly one narrowly
     testable mechanism (recorded as an unauthorized, untested hypothesis —
     returned to the operator for a separate authorization decision, at
     most one further bounded causal probe, no open-ended chain);
     otherwise `CLOSED — NO ACTIONABLE OFFLINE MECHANISM FOUND`, which
     explicitly recommends ending the line and returns to the main roadmap
     with no further experimentation proposed. No difference is ever
     labeled causal on its own — only structural, lexical/content-specific,
     ranking/position-specific, serialization-specific, or "no actionable
     discriminator." Standing engineering conclusions already supported by
     the accumulated ORQ-30–33 evidence, to be restated (not re-derived) in
     this candidate's closing documentation: retrieval success does not
     guarantee generation success; generation reliability should be
     evaluated conditioned on successful evidence delivery; multilingual
     behaviour must be included in production evaluation; abstention-after-
     successful-retrieval should be observable separately from retrieval
     failure; no language-specific routing, retry policy, prompt hack, or
     provider-specific production logic has yet been validated. Does not
     reopen or reinterpret ORQ-30 through ORQ-33. Inserted as an unclaimed,
     unnumbered candidate ahead of ORQ-34 (below) — no existing roadmap
     number is reassigned or renumbered by this insertion; ORQ-34 keeps its
     own placeholder number and stays gated on this candidate's outcome for
     what counts as a "frozen fix" going into confirmatory evaluation (per
     ORQ-33 spec's own correction: a formulated-only candidate is not a
     frozen fix — see `.framework/orqs/ORQ-33-memory-residual-diagnosis/spec.md`
     §Non-scope).
   - **ORQ-34 — Conversational RAG Memory: confirmatory preregistered
     evaluation** (not yet claimed): the single ORQ whose purpose is to
     answer whether Conversational RAG Memory is finally validated, given
     ORQ-33's diagnosis and candidate fix. Minimum required design: frozen
     baseline, frozen memory candidate, frozen fix; EN and ES evaluated;
     out-of-window recall, recent-evidence control, abstention correctness,
     tenant/conversation isolation, and correctness as measured outcomes;
     latency/TTFT if still part of the contract; cost; a sample sized by a
     power/sizing analysis performed before execution; pre-registration;
     exclusion criteria; thresholds; a predefined `GO`/`NO_GO`; a properly
     isolated held-out or confirmatory dataset; a single valid execution if
     the protocol defines one that way. Success is only claimed as something
     equivalent to: "the conversational-memory approach improves
     out-of-window recall over the agreed baseline, preserves isolation and
     abstention correctness, removes the previously observed English-language
     generation failure, and passes a preregistered confirmatory evaluation
     under the agreed latency and cost constraints" — and only if the
     predefined criteria are actually met. A failed confirmatory is recorded
     as a failed confirmatory; the design must not be shaped to guarantee a
     `GO`.
   - **ORQ-35 — RAG in Production** (not yet claimed): end-to-end observability
     and hardening following ORQ-26/27 baseline metrics. Prerequisites: ORQ-23,
     24, 25 operationally stable, baselines established, **and** the
     Conversational RAG Memory investigation closed (ORQ-33, its unclaimed
     offline-residual-characterization successor, and ORQ-34 above) — per
     operator priority decision (2026-08-25), production hardening work
     follows the memory investigation's close rather than running ahead of it.
     Scope: complete OpenTelemetry instrumentation (`retrieve → rerank →
     generate` spans — including the emission the master doc assigned to the
     evaluation item, moved here so instrumentation is designed once with its
     backend), Phoenix/Grafana dashboard, adversarial robustness hardening,
     cost/latency tuning. Design Review prompt deferred pending Module 5 of
     the RAG course. Numbered ORQ-27 before the 2026-08-07 split, then ORQ-31
     until reassigned to the English-failure diagnosis (2026-08-20), then
     ORQ-32 until claimed by the controlled EN/ES probe (2026-08-25), then
     ORQ-33 before this replan inserted the two Memory-closure candidates
     ahead of it (2026-08-25). Deferred and reordered, not discarded —
     purpose and prerequisites unchanged.
2. **ORQ-36 — Routing evidence dataset** (not yet claimed): `RoutingPolicy`
   interface with heuristic and static implementations by default; collect real
   signal before any model. Numbered ORQ-22 in the original plan, then ORQ-28
   before the 2026-08-07 split, then ORQ-32 before the 2026-08-20 replan, then
   ORQ-33 before this replan's first pass, then ORQ-34 after the Memory-closure
   candidates were inserted ahead of it (2026-08-25).
   Convergence note: the Agentic RAG LLM router is conceptually the same
   classifier, so once ORQ-35/ORQ-36 produce real signal, the RAG router design
   follows at no extra cost.
3. **ORQ-37 — Offline ML routing baseline** (not yet claimed): a simple,
   explainable model, and only if ORQ-36's evidence dataset shows real signal.
   Numbered ORQ-23 in the original plan, then ORQ-29, then ORQ-33 before the
   2026-08-20 replan, then ORQ-34 before this replan's first pass, then ORQ-35
   after the Memory-closure candidates were inserted ahead of it (2026-08-25).

Reusable precedent: for broad or multilingual queries, reranking alone is not
enough when the initial candidate set is poor — intent detection plus an
"overview" canonical query expansion plus path-priority reranking is the pattern
that worked. Relevant here because project documentation is bilingual.

## Phase 3 — AI Green extension

**ORQ-38 — AI Green extension** (not yet claimed). Numbered ORQ-24 in the
original plan, then ORQ-30 before the 2026-08-07 evaluation split, then ORQ-34
before the 2026-08-20 replan, then ORQ-35 before this replan's first pass, then
ORQ-36 after the Memory-closure candidates were inserted ahead of it
(2026-08-25). Sequenced as energy telemetry → carbon-aware routing →
scheduler, and gated on ORQ-36 producing real routing signal. Convergence
note: Adaptive RAG rests on the same principle — spend the cheapest resource
that still answers the question.

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
- **Cross-conversation / long-term memory** remains outside ORQ-29. It requires
  a trusted subject identity plus independent consent, authorization,
  retention, correction, revocation, export, and deletion decisions. It must
  not be inferred from tenant ownership or reuse ORQ-29's conversation scope
  silently; any future proposal needs a separately assigned ORQ and approval.
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
- **ORQ-32's two-pair residual is not one phenomenon** (ORQ-33, 2026-08-26): repeated sampling
  (10x each) split the residual into run-to-run generation variability (conversation 01, 9/10
  answer) and a stable, unexplained abstention (conversation 04, 10/10 abstain). No production
  fix validated; the memory-experimentation line continues only as far as a single further
  offline, no-call diagnostic of conversation 04 against its nearest flipped controls, with an
  explicit end-of-line default if no discriminator is found — not an open-ended chain of ORQs.
  Full evidence: `.framework/orqs/ORQ-33-memory-residual-diagnosis/validation.md`.

## Related

Purpose and boundaries: [[mission]] · Constraints and invariants: [[tech-stack]]
