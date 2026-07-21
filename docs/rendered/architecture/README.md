# Architecture diagrams

Four hand-authored SVGs, each covering one concern. They are the source of truth for
themselves: there is no Mermaid source behind them anymore, so there is nothing to
regenerate and nothing that can silently diverge from a render.

| File | Concern |
|---|---|
| `chat-request-flow-v2.svg` | End-to-end path of a `/chat` request: middleware stack, tenant resolution, orchestration, persistence and cache |
| `module-boundaries-v2.svg` | Package boundaries and the allowed direction of dependency |
| `provider-abstraction-v1.svg` | `ProviderPort`, the factory, `ResilientProvider` and the concrete adapters |
| `streaming-fallback-sequence-v1.svg` | SSE sequence and the three streaming outcomes, including where fallback is forbidden |

## Rules

- Keep each diagram focused on one concern. Prefer editing an existing diagram over
  adding a new one.
- Keep filenames stable unless the scope changes materially. Bump the version suffix
  when it does.
- Do not draw future components in current-state diagrams.
- Update the relevant diagram when architecture, boundaries, request flow, provider
  flow, streaming or fallback behavior, or persistence flow changes.
- Every diagram must carry a `<title>` and a `<desc>`, and must stay readable in the
  palette shared with `.framework/constitution/diagrams/`.
- Validate the XML after editing and check that no arrow ends without touching its
  target.

## History

These replace six Mermaid sources under `docs/working/diagrams/architecture/` and three
SVGs rendered from them in March 2026. The renders had drifted: they still showed the
pre-multitenancy architecture months after the sources were updated, and both flow
diagrams described `TenantMiddleware` as outermost, which stopped being true once CORS
and the staging guard were registered around it. Consolidating to a single authored
artifact per concern removes the render step where that drift accumulated.

Three source files described the same request flow (`chat-flow-architecture-v1`,
`chat-flow-architecture-v2`, `tenant-flow-v1`); they are now one diagram.

## Relationship to `.framework/constitution/diagrams/`

Those sit one altitude above and are governed by the AI Together Framework diagram gate.
These are the LLD-level detail. They reference each other; they do not duplicate.
