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
   - **ORQ-34 — Final offline residual characterization
     (`DEV_04_S00_LANGSWAP`) — CLOSED LOCALLY — NO ACTIONABLE OFFLINE
     MECHANISM FOUND** (`ait-orq-number-ORQ-34`, closed 2026-08-27): the
     bounded, offline-only, zero-provider-call characterization of ORQ-33's
     one remaining stable residual (conversation 04, `_S00`/"atlas",
     en→es direction) against its two nearest flipped controls
     (conversations 00, 02), across all 12 precommitted dimensions (token
     count, event ordering, gold-event position, BM25 rank/score, lexical
     overlap, old-vs-current evidence position, competing-nonce count,
     serialization after suffix normalization, id/suffix patterns,
     conv04-only text patterns, normalized request-body diff, post-
     normalization distinguishability). Every dimension came back
     indistinguishable from both controls, each finding independently
     recomputed twice with identical results; USD 0.00 spent, zero
     provider/model/embedding calls. Per the precommitted terminal rule,
     this closes as `CLOSED — NO ACTIONABLE OFFLINE MECHANISM FOUND`, not
     `OFFLINE DISCRIMINATOR FOUND` — no causal hypothesis is recorded, none
     is warranted. **This closes the memory-experimentation diagnostic
     line ORQ-30 opened.** Conversation 04's abstention cause remains
     genuinely unknown and stays documented as such — this is an accepted,
     disclosed limitation of the `E-BM25` candidate (§ORQ-35 below), not a
     solved problem and not a reason to reopen diagnosis. No further
     diagnostic ORQ on this residual is authorized by this closure: no more
     repeated sampling, no broader sweep, no further offline inspection
     without a new, previously-justified discriminator (operator directive,
     2026-08-27 — see `.framework/orqs/ORQ-34-conv04-offline-characterization/validation.md`
     for the full bounded conclusion, single source of fact, not restated
     further here). Does not reopen or reinterpret ORQ-30 through ORQ-33.
     Claiming this number (`ait-orq-number-ORQ-34`) collided with the
     placeholder number previously held by the confirmatory-evaluation
     candidate below — renumbered to ORQ-35 as a direct consequence
     (operator-confirmed 2026-08-26), cascading through the then-numbered
     ORQ-36/37/38/39 below; no other ordering or scope change. Those four
     were renumbered again on 2026-08-28 — see the reordering decision in
     the log below.
   - **ORQ-35 — Conversational RAG Memory: confirmatory evaluation**
     (claimed, `ait-orq-number-ORQ-35`; **terminated in Plan, not
     executed**): intended to answer whether Conversational RAG Memory is
     finally validated. Terminal state `BLOCKED — NO CONFIRMATORY
     EVALUATION IS POSSIBLE WITH THE INHERITED APPARATUS`. Two rounds of
     independent design review established, against source rather than
     against the protocol charter's prose, that the inherited confirmatory
     apparatus cannot support a population inference at any sample size:
     `development.py`'s generator is index-parameterized only, so any `n`
     conversations are `n` renamings of a single item, and the frozen
     `GO` comparison passes deterministically. No pre-registration was
     frozen, no dataset generated, no provider call made, zero cost, no
     production change, and **no `GO`/`NO_GO` exists**. The Conversational
     RAG Memory line therefore closes **without confirmatory validation**;
     its standing evidence is development-grade only (ORQ-30) plus the
     ORQ-31–34 diagnostics. Full record, including the retracted
     Spanish-only scope: `.framework/orqs/ORQ-35-memory-confirmatory-evaluation/spec.md`;
     decision entry in the log below. Superseded design detail, retained
     only as the historical reason the ORQ was opened: `E-BM25` was
     resolved as the single defensible candidate — the only arm
     with positive out-of-window development evidence (ORQ-30: 16/32 vs.
     `B`'s 0/32, 32/32 gold-event delivery), its configuration unchanged in
     tracked code across ORQ-30–34, and no fix or variant was ever
     formulated against it (ORQ-33/34 both closed without a fix
     candidate). That candidate resolution is not overturned by this
     termination — it is simply never put to a confirmatory test.
   - **ORQ-36 — Cross-model diagnostic replication of the EN/ES asymmetry**
     (claimed, `ait-orq-number-ORQ-36`): does the EN/ES behaviour observed with
     GPT-4o-mini reproduce when only the generation model changes? Sequenced
     **ahead of ORQ-37 (RAG in Production)** by operator decision
     (2026-08-28): whether multilingual generation reliability is
     model-sensitive is an input to how production evaluation is designed, and
     that input is largely wasted if it arrives after the observability and
     evaluation surface is already built. This reverses the earlier sequencing,
     which placed it after production hardening.
     It remains **diagnostic and descriptive**: it cannot produce a
     productization `GO`/`NO_GO` and does not repair ORQ-35's limitation, so
     ORQ-37 must not be held indefinitely on it — if this ORQ stalls, is
     invalidated, or closes at the Arm 0 gate, ORQ-37 proceeds on its own
     production-readiness criteria. The two may run concurrently if
     `max_concurrent_orqs` allows (currently `2`, with `Blocked` ORQs not
     counting).
     Three arms over the **frozen** 32 `request_body_excluding_credentials`
     of ORQ-32: Arm 0 re-anchors `gpt-4o-mini-2024-07-18`; Stage 1 is Gemini
     2.5 Flash (Vertex AI); Stage 2 is Amazon Nova Lite (AWS Bedrock). No new
     retrieval, embeddings, dataset or sweeps; no production change; ORQ-30–35
     untouched. One call per request for the main comparison, plus a focused
     `k=10` replication of `DEV_04_S00_LANGSWAP` with `DEV_00_S00_LANGSWAP` as
     its **single** control (operator decision 2026-08-28: `conv02` is **not**
     added — `conv00` alone establishes the model's answer propensity, which
     is the only calibration the `k=10` needs; minimum sufficient scope).
     Repeated sampling is confined to those two cells. 52 calls per arm.
     Structured output is harmonized by **removing the provider-side
     mechanism in all three arms** — the JSON instruction already lives in the
     prompt text, and the three vendors' JSON modes have different binding
     strength, so equalizing at "none" is the only equal-force option;
     `non_conforming` becomes a first-class metric with a preregistered
     threshold that can invalidate an arm's comparison. Prompt semantics
     unchanged.
     **Arm 0 is a hard gate (operator decision 2026-08-28):** if the
     harmonized GPT-4o-mini arm does not reproduce the asymmetry after
     `response_format` is removed, the ORQ closes there and **Gemini and Nova
     are not executed** — without a comparable baseline there is nothing for a
     cross-model replication to replicate. Later stages may abort an earlier
     one for invalidity or cost, but may **never** modify a subsequent stage's
     prompts, dataset, metrics, scoring, comparable parameters, `k=10`
     protocol or terminal rule. Hard cost cap per arm, checked before each
     dispatch.
     Interpretation is capped at: *"On this fixed stimulus set, the observed
     EN/ES behaviour reproduces or does not reproduce under model
     substitution."* It must **not** assert model independence or
     generalization to other prompts or datasets. **Correction (2026-08-28,
     ORQ-36 design review R2):** this entry previously required the ORQ to
     state that the effective number of distinct items is 1, carried over from
     ORQ-35's finding about the 48-conversation confirmatory set. That figure
     is false of the 32-row artifact ORQ-36 actually consumes. Counted from
     `swapped-requests.json`: 2 fact families, each bound to one step id
     (`ATLAS`⟺`S00`, `BEACON`⟺`S01`), in 4 surface forms, each replicated 8
     times by conversation index — and the two question directions use
     disjoint conversation sets (0–7 and 8–15), so the language contrast is
     confounded with conversation identity. ORQ-36 must state that structure,
     not the inherited "1". ORQ-35's own finding is unaffected: it concerned a
     different subset and stands as recorded.
     Requires the operator override recorded in the decisions log below,
     because the `k=10` touches the conversation-04 residual that ORQ-34's
     closure declared off-limits.
   - **ORQ-37 — RAG in Production** (claimed, `ait-orq-number-ORQ-37`):
     end-to-end observability and hardening following ORQ-26/27 baseline
     metrics. Prerequisites: ORQ-23, 24, 25 operationally stable, baselines established, **and** the
     Conversational RAG Memory investigation closed (ORQ-33, ORQ-34, and
     ORQ-35 above) — per operator priority decision (2026-08-25), production
     hardening work follows the memory investigation's close rather than
     running ahead of it. That prerequisite is now met: the line is closed,
     though **without** a confirmatory validation. **This ORQ inherits no
     confirmatory decision — ORQ-35 produced no `GO`/`NO_GO` and authorized
     nothing** (see ORQ-35 above). The available memory evidence is
     development-grade (ORQ-30) plus the ORQ-31–34 diagnostics, and
     **`E-BM25` is not scientifically confirmed**. This ORQ *may*
     nonetheless evaluate a controlled production adoption of `E-BM25`, on
     its own authority and against its own production-readiness gates —
     observability, isolation, latency, cost, rollback and operational
     risk. Such an adoption would be **this ORQ's own engineering decision
     under uncertainty**, and must never be presented, documented or
     communicated as confirmatory validation, as scientific evidence that
     the candidate works, or as the execution of a decision made
     elsewhere. Any claim about the candidate's effectiveness stays bounded
     by the development-grade evidence that actually exists.
     This ORQ remains explicitly not where candidate selection, retrieval
     strategy, multilingual generation behaviour, abstention mitigation,
     prompt tuning, or retry policy get decided or re-litigated (operator
     directive, 2026-08-27) — the memory line is closed, and this ORQ is
     not the place to reopen it.
     Scope: complete OpenTelemetry instrumentation (`retrieve → rerank →
     generate` spans — including the emission the master doc assigned to the
     evaluation item, moved here so instrumentation is designed once with its
     backend), Phoenix/Grafana dashboard, adversarial robustness hardening,
     cost/latency tuning. Design Review prompt deferred pending Module 5 of
     the RAG course. Numbered ORQ-27 before the 2026-08-07 split, then ORQ-31
     until reassigned to the English-failure diagnosis (2026-08-20), then
     ORQ-32 until claimed by the controlled EN/ES probe (2026-08-25), then
     ORQ-33 before the 2026-08-25 replan inserted the two Memory-closure
     candidates ahead of it, then ORQ-35 before this replan's ORQ-34 claim
     bumped it again (2026-08-26). Deferred and reordered, not discarded —
     purpose and prerequisites unchanged.
2. **ORQ-38 — Routing evidence dataset** (not yet claimed): `RoutingPolicy`
   interface with heuristic and static implementations by default; collect real
   signal before any model. Numbered ORQ-22 in the original plan, then ORQ-28
   before the 2026-08-07 split, then ORQ-32 before the 2026-08-20 replan, then
   ORQ-33 before the 2026-08-25 replan's first pass, then ORQ-34 after the
   Memory-closure candidates were inserted ahead of it (2026-08-25), then
   ORQ-36 after this replan's ORQ-34 claim bumped it again (2026-08-26), then
   ORQ-38 when ORQ-36/37 were claimed by the cross-model replication and RAG in
   Production (2026-08-28). Convergence note: the Agentic RAG LLM router is
   conceptually the same classifier, so once ORQ-38/ORQ-39 produce real signal, the RAG router design
   follows at no extra cost.
3. **ORQ-39 — Offline ML routing baseline** (not yet claimed): a simple,
   explainable model, and only if ORQ-38's evidence dataset shows real signal.
   Numbered ORQ-23 in the original plan, then ORQ-29, then ORQ-33 before the
   2026-08-20 replan, then ORQ-34 before the 2026-08-25 replan's first pass,
   then ORQ-35 after the Memory-closure candidates were inserted ahead of it
   (2026-08-25), then ORQ-37 after this replan's ORQ-34 claim bumped it again
   (2026-08-26), then ORQ-39 on the 2026-08-28 reordering.

Reusable precedent: for broad or multilingual queries, reranking alone is not
enough when the initial candidate set is poor — intent detection plus an
"overview" canonical query expansion plus path-priority reranking is the pattern
that worked. Relevant here because project documentation is bilingual.

## Phase 3 — AI Green extension

**ORQ-40 — AI Green extension** (not yet claimed). Numbered ORQ-24 in the
original plan, then ORQ-30 before the 2026-08-07 evaluation split, then ORQ-34
before the 2026-08-20 replan, then ORQ-35 before the 2026-08-25 replan's first
pass, then ORQ-36 after the Memory-closure candidates were inserted ahead of
it (2026-08-25), then ORQ-38 after this replan's ORQ-34 claim bumped it again
(2026-08-26), then ORQ-40 on the 2026-08-28 reordering. Sequenced as energy
telemetry → carbon-aware routing → scheduler, and gated on ORQ-38 producing real routing signal. Convergence
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
- **Memory-experimentation diagnostic line closed; `E-BM25` confirmed as the sole candidate**
  (ORQ-34, 2026-08-27): the offline, zero-provider-call characterization of conversation 04's
  residual against its 2 nearest flipped controls found no discriminator across all 12
  precommitted dimensions — `CLOSED — NO ACTIONABLE OFFLINE MECHANISM FOUND`. Per the
  precommitted terminal rule, this closes the diagnostic line ORQ-30 opened: no further
  diagnostic ORQ on this residual without a new, previously-justified discriminator. Replan
  resolution (2026-08-27, evidence-only): `E-BM25` is the single defensible Conversational RAG
  Memory candidate (only arm with positive out-of-window evidence, unchanged in tracked code
  since ORQ-30); no candidate-development ORQ is inserted before the confirmatory. Conversation
  04's cause remains genuinely unknown and is carried into ORQ-35 as a disclosed, accepted-risk
  exclusion note, not a solved problem. Full evidence:
  `.framework/orqs/ORQ-34-conv04-offline-characterization/validation.md`.
- **Conversational RAG Memory closes without confirmatory validation** (ORQ-35,
  2026-08-27): the confirmatory evaluation was terminated in its Plan phase,
  before any pre-registration was frozen and before any provider call, at
  `BLOCKED — NO CONFIRMATORY EVALUATION IS POSSIBLE WITH THE INHERITED
  APPARATUS`. Verified cause: `development.py`'s dataset generator is
  index-parameterized only (`_language_questions()` takes the language, not the
  conversation), so any `n` conversations are `n` renamings of one item; the
  protocol charter's premise that "conversation is the independent unit" is
  false by construction, the bootstrap measures within-item repeatability, and
  the frozen `GO` comparison passes deterministically. The frozen selector
  cannot detect this — ORQ-30's paired differences are eight `0` and eight `1`,
  so `s = 0` within either language subset and `sigma_plan` floors at its
  hardcoded minimum, producing an identical power figure for the English subset
  in which the candidate never won. `guards.py` and `determinism.py` contain
  zero references to language, so **no scope choice repairs this** — a
  Spanish-only framing was proposed, disproved, and is recorded as rejected so
  it cannot be revived as an open option. Consequences: `E-BM25` remains
  scientifically unconfirmed and no confirmatory decision authorizes it;
  ORQ-37 inherits no `GO`/`NO_GO` and may only adopt it, if at all, as its
  own engineering decision under its own production-readiness gates, never
  as confirmatory validation (see ORQ-37 above); repairing the apparatus
  would need a genuinely new dataset design with real item variation, which
  the operator declined. Zero provider calls, USD 0, no production change.
  Full record:
  `.framework/orqs/ORQ-35-memory-confirmatory-evaluation/spec.md`.
- **Bounded override of ORQ-34's no-further-diagnostics directive, for a
  cross-model replication only** (2026-08-28): ORQ-34's closure authorized no
  further diagnostic ORQ on the conversation-04 residual. The operator
  overrides that directive **once and narrowly**, to permit the cross-model
  diagnostic replication candidate above, whose `k=10` cell necessarily touches
  that residual. Scope of the override: the frozen ORQ-32 stimulus set, three
  generation models, and repeated sampling confined to `DEV_04_S00_LANGSWAP`
  and its single control `DEV_00_S00_LANGSWAP`. It does **not** reopen offline
  inspection of the residual, does not authorize broader sweeps or repeated
  sampling elsewhere, and does not restore the memory-experimentation line —
  which stays closed. Recorded here because without it the roadmap would carry
  a standing prohibition and a candidate that violates it.
- **Cross-model replication sequenced ahead of RAG in Production; Phase 2/3
  renumbered** (2026-08-28): the cross-model diagnostic replication takes
  ORQ-36 and RAG in Production takes ORQ-37, reversing the order set earlier
  the same day. Operator rationale: whether multilingual generation
  reliability is model-sensitive is an input to how production evaluation and
  observability are designed, and that input is largely wasted if it arrives
  after that surface is already built. The reversal does not upgrade the
  cross-model ORQ's authority — it stays diagnostic and descriptive, produces
  no `GO`/`NO_GO`, and must not hold ORQ-37 indefinitely: if it stalls, is
  invalidated, or closes at its Arm 0 gate, ORQ-37 proceeds on its own
  production-readiness criteria. Consequent renumbering, no scope change:
  Routing evidence dataset ORQ-37→38, Offline ML routing baseline ORQ-38→39,
  AI Green extension ORQ-39→40. Correction recorded for the record: the
  2026-08-28 claim of ORQ-37 for the cross-model candidate collided with the
  number Routing evidence dataset already held in this roadmap, and the agent
  had stated before claiming that no renumbering would be needed — that
  statement was wrong, and the cascade above was required regardless of the
  reordering. Both numbers are reserved on `origin`
  (`ait-orq-number-ORQ-36`, `ait-orq-number-ORQ-37`); neither ORQ has a branch
  or folder yet.

## Related

Purpose and boundaries: [[mission]] · Constraints and invariants: [[tech-stack]]
