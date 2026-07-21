# Diagrams index — llm-chat-platform

Baseline established by `fw-init` on 2026-07-21. Refreshes are handled by `fw-replan`
using the ORQ-18 helpers in `.framework/local-tools/`; `fw-init` never regenerates an
existing diagram.

| tipo | alcance | archivo | generado/manual | última actualización | refresh_pending | refresh_baseline |
|---|---|---|---|---|---|---|
| context | producto | `context.svg` | generado | 2026-07-21 | no | `sha256:240a74bf40cf3050f05f901a4978a02916231cce83d883f33ce298a3b7df1f6a` |
| architecture | framework | `architecture.svg` | generado | 2026-07-21 | no | `sha256:240a74bf40cf3050f05f901a4978a02916231cce83d883f33ce298a3b7df1f6a` |
| structural | producto | `structural.svg` | manual | 2026-07-21 | no | `sha256:240a74bf40cf3050f05f901a4978a02916231cce83d883f33ce298a3b7df1f6a` |
| deployment | producto | `deployment.svg` | manual | 2026-07-21 | no | `sha256:240a74bf40cf3050f05f901a4978a02916231cce83d883f33ce298a3b7df1f6a` |
| behavior | producto | `behavior.svg` | manual | 2026-07-21 | no | `sha256:240a74bf40cf3050f05f901a4978a02916231cce83d883f33ce298a3b7df1f6a` |
| erd | producto | `erd.svg` | manual | 2026-07-21 | no | `sha256:240a74bf40cf3050f05f901a4978a02916231cce83d883f33ce298a3b7df1f6a` |

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
