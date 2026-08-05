# Diagrams index — llm-chat-platform

Baseline established by `fw-init` on 2026-07-21. Refreshes are handled by `fw-replan`
using the ORQ-18 helpers in `.framework/local-tools/`; `fw-init` never regenerates an
existing diagram.

| tipo | alcance | archivo | generado/manual | última actualización | refresh_pending | refresh_baseline |
|---|---|---|---|---|---|---|
| context | producto | `context.svg` | generado | 2026-08-05 | no | `sha256:976c6cc77af0ca06e5cfe2bec14260b818a3b8b59b2ac02761e62acd0ea1a8d0` |
| architecture | framework | `architecture.svg` | generado | 2026-08-05 | no | `sha256:976c6cc77af0ca06e5cfe2bec14260b818a3b8b59b2ac02761e62acd0ea1a8d0` |
| structural | producto | `structural.svg` | manual | 2026-08-05 | no | `sha256:976c6cc77af0ca06e5cfe2bec14260b818a3b8b59b2ac02761e62acd0ea1a8d0` |
| deployment | producto | `deployment.svg` | manual | 2026-08-05 | no | `sha256:976c6cc77af0ca06e5cfe2bec14260b818a3b8b59b2ac02761e62acd0ea1a8d0` |
| behavior | producto | `behavior.svg` | manual | 2026-08-05 | no | `sha256:976c6cc77af0ca06e5cfe2bec14260b818a3b8b59b2ac02761e62acd0ea1a8d0` |
| erd | producto | `erd.svg` | manual | 2026-08-05 | no | `sha256:976c6cc77af0ca06e5cfe2bec14260b818a3b8b59b2ac02761e62acd0ea1a8d0` |

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
