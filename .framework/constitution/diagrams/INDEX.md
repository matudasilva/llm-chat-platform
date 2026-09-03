# Diagrams index — llm-chat-platform

Baseline established by `fw-init` on 2026-07-21. Refreshes are handled by `fw-replan`
using the ORQ-18 helpers in `.framework/local-tools/`; `fw-init` never regenerates an
existing diagram.

| tipo | alcance | archivo | generado/manual | última actualización | refresh_pending | refresh_baseline |
|---|---|---|---|---|---|---|
| context | producto | `context.svg` | generado | 2026-09-03 | no | `sha256:511c6dc9275e1c3f0d456817006d512b5eec21834892a07848ffbdaacfd94787` |
| architecture | framework | `architecture.svg` | generado | 2026-08-07 | sí (deferred) | `sha256:6096ce9ea9c68868dd5216f05b946195f01a2d2db874d05e7612d69274ddf957` |
| structural | producto | `structural.svg` | manual | 2026-08-07 | sí (deferred) | `sha256:6096ce9ea9c68868dd5216f05b946195f01a2d2db874d05e7612d69274ddf957` |
| deployment | producto | `deployment.svg` | manual | 2026-09-03 | no | `sha256:511c6dc9275e1c3f0d456817006d512b5eec21834892a07848ffbdaacfd94787` |
| behavior | producto | `behavior.svg` | manual | 2026-08-07 | sí (deferred) | `sha256:6096ce9ea9c68868dd5216f05b946195f01a2d2db874d05e7612d69274ddf957` |
| erd | producto | `erd.svg` | manual | 2026-08-07 | sí (deferred) | `sha256:6096ce9ea9c68868dd5216f05b946195f01a2d2db874d05e7612d69274ddf957` |

## ORQ-38 replan result (2026-09-03)

`context.svg` and `deployment.svg` were reviewed and **acknowledged** (`ack`): ORQ-38 adds no
actor and no deployable component — it ships two modules that nothing calls. Both rows are
rebaselined to the current Constitution signature `sha256:511c6dc9…` and now read
`refresh_pending: no`.

`architecture.svg`, `structural.svg`, `behavior.svg` and `erd.svg` stay **deferred until ORQ-37
closes** (operator decision, 2026-09-03). The reason is that ORQ-38 deliberately shipped an
*unwired* conversation-history substrate: `ConversationHistoryAssembler` and
`SqlConversationHistoryAdapter` exist with no production caller, and ORQ-37 Block B is the named
consumer that will wire them. ORQ-37 may also resolve D-3, the missing
`(conversation_id, sequence)` index. Refreshing these four now would draw a transitional
architecture and require drawing it again a few weeks later; the four rows keep their
2026-08-07 baseline so the pending signal stays observable rather than being silently cleared.

This deferral is narrower than the ORQ-26 one below, which held all six. Two are now current.

**Detector note:** this is the first replan since 2026-08-10 whose diagram step actually ran.
`fw_check_diagram_refresh.py` had raised `ERROR detector-contract` on every invocation since
those six rows were annotated `sí (deferred)` — `parse_index()` compared the whole cell against
`{"no", "sí", "indeterminado"}` — which blocked step 8.b of every `fw-validate` and step 2 of
every `fw-replan` for three consecutive replans. The parser was fixed to accept an optional
parenthesised annotation while treating only the leading token as the contract, with 14
regression tests. The fix lives in `.framework/local-tools/`, which is gitignored under
`artifact_policy: hybrid`, so it is local-only and carries no commit. The annotation itself was
never the defect and was not altered.

## ORQ-26 replan result (2026-08-10) — deferred by operator

All six diagrams flagged `refresh_pending: sí` (architecture-signature source: constitution)
after this replan's `roadmap.md` edits — closing ORQ-26, correcting the cache-fingerprint and
message-order overclaims, adding the three rediscovered Phase 1 debt items, and adding the
"Conversational memory via RAG" Phase 2 item. Proposed disposition was `ack` for
`context`/`architecture`/`deployment` (no actor, framework-install, or deployable-component
change) and `adopt` for `structural`/`behavior`/`erd` (ORQ-26 added a real module —
`experiments/evaluation/` — and a real schema — `evaluation`, outside the Alembic chain per
ADR-009 — plus the roadmap's phase-dependency shape changed). **Operator explicitly deferred all
six** (2026-08-10): batch them together right before starting the Routing phase (Phase 2 item 2,
`RoutingPolicy`/ORQ-30 in the current draft numbering) rather than refreshing twice in a row for
adjacent changes. Signal only, does not block ORQ-26's closure or any work in between.

## ORQ-25 replan result (2026-08-07)

`context.svg`, `architecture.svg`, and `deployment.svg` were reviewed and acknowledged without
content changes (`ack`): ORQ-25 adds no actor, Framework installation change, or deployable
component. `structural.svg`, `behavior.svg`, and `erd.svg` were refreshed with real content
(`adopt`): structural now shows the default-off retrieval-to-chat augmentation boundary and
feedback telemetry; behavior marks ORQ-25 done and ORQ-26 as the grounded-answer-quality and
harness follow-up; ERD now records `UsageEvent.message_id`, feedback, and
`feedback_updated_at`. All six diagrams share the current Constitution signature and have no
pending refresh signal.

## ORQ-25 refresh signal (2026-08-06, fw-validate)

`fw_check_diagram_refresh.py` flagged all six rows `refresh_pending: sí`
(architecture-signature source: Constitution) after ORQ-25 changed `roadmap.md` and delivered
RAG augmentation plus UsageEvent feedback. This is a non-blocking signal only: framework diagram
review/regeneration belongs to `fw-replan`. The four affected hand-authored LLD SVGs under
`docs/rendered/architecture/` were updated and XML-validated within ORQ-25.

## ORQ-24 replan result (2026-08-06)

`context.svg`, `architecture.svg`, `deployment.svg` and `erd.svg` were reviewed and acknowledged
without content changes (`ack`) — ORQ-24 added no new deployable component and no schema change.
`structural.svg` and `behavior.svg` were refreshed with real content (`adopt`): structural now
shows the reranker adapters box as `CascadingRerankerAdapter: GCP primary → AWS fallback` (was
`AWS (production, us-west-2) · GCP · Qwen (benchmark only)`); behavior adds an ORQ-24 "done" box
between ORQ-23 and the planned-work box, and relabels that planned box from "ORQ-24
generation · ORQ-25 eval" to "ORQ-25 generation · ORQ-26 eval" to match `roadmap.md`'s
renumbering. All six diagrams share the current Constitution signature and have no pending
refresh signal.

## ORQ-23 replan result (2026-08-05)

`context.svg` and `architecture.svg` were reviewed and acknowledged without content changes
(`ack`). `deployment.svg` and `erd.svg` were reviewed and acknowledged without content changes —
ORQ-23 added no new deployable component and no schema change. `structural.svg` and
`behavior.svg` were refreshed with real content (`adopt`, not just a signature rebaseline):
structural now shows the retrieval pipeline wired end-to-end (was a dashed "benchmark only" box)
and the AWS reranker adapter marked production (`us-west-2`); behavior shows ORQ-23 as done and
relabels the old "follow-up retrieval pipeline" box to the actual ORQ-24/25 split. All six
diagrams share the current Constitution signature and have no pending refresh signal.

## ORQ-23 refresh signal (2026-08-05, fw-validate)

`fw_check_diagram_refresh.py` flagged all six rows `refresh_pending: sí` again
(architecture-signature source: Constitution) after ORQ-23 changed `roadmap.md`'s Phase 2 item 1
(the ORQ-23/24/25 split) — a `behavior`-level change, not structural/deployment. Signal only, per
fw-validate step 8.b: not recalculated further, not regenerated, does not block this ORQ's
closure. Actual regeneration is `fw-replan`'s responsibility (see result above).

## ORQ-21 refresh signal (2026-08-03, fw-validate)

`fw_check_diagram_refresh.py` flagged all six rows `refresh_pending: sí` (architecture-signature
source: Constitution) after ORQ-21 added a new pgvector-backed corpus (`documents`/`chunks`,
`DATABASE_URL_APP`, a second RLS-scoped role) — a real change to the ERD and deployment shape.
Signal only, per fw-validate step 8.b: not recalculated further, not regenerated, does not block
this ORQ's closure. Actual regeneration is `fw-replan`'s responsibility.

## ORQ-22 replan result (2026-08-04)

The operator approved the recommended disposition: `context.svg` and `architecture.svg` were
reviewed and acknowledged without content changes; `structural.svg`, `deployment.svg`,
`behavior.svg`, and `erd.svg` were refreshed to reflect the delivered RAG corpus and isolated
reranking benchmark. All six diagrams now share the current Constitution signature and have no
pending refresh signal.

## Gate evidence

- `context` — Constitution V3 present (`mission.md`, `tech-stack.md`, `roadmap.md`).
- `architecture` — AIT V3 installed with the 7 canonical Skills.
- `structural` — `mission.md` §Scope enumerates own modules: `/chat` write-path,
  `ProviderPort` + adapters, external capabilities, cache, tenant middleware.
- `deployment` — `tech-stack.md` declares more than one deployable component
  (API image on PaaS, separate SPA, managed Postgres and Redis, registry).
- `behavior` — `roadmap.md` has Phase 1 open items running alongside Phase 2, with
  explicit dependencies into Phase 3.
- `erd` — PostgreSQL with a product-owned schema (`Conversation`, `Message`,
  `UsageEvent`) evolved through the Alembic chain.

## Relationship to `docs/rendered/architecture/`

Those are hand-authored product documentation diagrams, governed by `AGENTS.md`
§Diagram maintenance — four of them, one per concern: request flow, module boundaries,
provider abstraction and the streaming sequence. They are a different artifact class and
remain the detailed LLD-level view. The diagrams in this directory sit one altitude above
and are governed by the AIT diagram gate. They reference, they do not duplicate.
