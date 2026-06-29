# ADR-001: Capabilities-First Before the Execution Orchestrator

**Date:** 2026-04-29 (retroactive decision; documented 2026-06-26)  
**Status:** Accepted  
**ORQ reference:** ORQ-10 to ORQ-16 (execution), Master Continuity Document (original plan)  
**Superseded by / Supersedes:** —

---

## Context

At the V1.1 closure (2026-04-17, `docs/v1_1_closure.md`), the project had stabilized:

- The `/chat` core with 4-step atomic persistence
- The `ProviderPort` abstraction with adapters for OpenAI, Bedrock, and Stub
- `ResilientProvider` (primary/fallback, no retry to the same provider)
- Best-effort Redis cache for non-streaming responses
- Structured JSON logging and `request_id` propagation

The **Master Continuity Document** (Notion planning, reference "Proyecto LLM Chat Platform ES") contemplated as the next phase a sequence of ORQs (ORQ-5 to ORQ-9 in the original numbering) aimed at implementing an **Execution Orchestrator V2.1**: a tool-calling and orchestration runtime on top of the existing chat domain.

With the adoption of Framework V2 (ORQ-10, 2026-04-27 to 2026-04-29), the operational governance infrastructure was established. At that point the decision was made not to proceed with the Execution Orchestrator but instead with controlled external capabilities (web read, Notion read, Notion write). This decision was never explicitly recorded at the time; the drift between plan and code was the motivation for creating this ADR retroactively.

### Git evidence of the actual execution order

```
96f9619  2026-04-29  Close ORQ-10 framework tooling alignment
f5924ba  2026-04-29  Add controlled web read MVP                      ← first external capability
333476a  2026-04-30  Close ORQ-11 controlled web read hardening
afefc31  2026-04-30  Add Notion Read configuration and MCP dependency  ← second capability
e7f3636  2026-04-30  Implement ControlledNotionReadClient (ORQ-12)
b8f5162  2026-04-30  Implement NotionReadService with allowlist enforcement
...
5ca5a54  2026-04-30  ORQ-12 Closure: Remove submodule, finalize documentation
f0d316d  2026-05-08  ORQ-14 Closure: External Read Capabilities Consolidation
5dbc4db  2026-05-09  ORQ-15: Governance sync to Notion
bf6fd50  2026-05-09  ORQ-16: Implement Notion Write MVP with static validation
```

The Execution Orchestrator does not appear in any commit from the ORQ-10 to ORQ-16 period.

---

## Decision

We decided to implement controlled external read and write capabilities (Web Read, Notion Read, Notion Write MVP) **before** the Execution Orchestrator V2.1, diverging from the order planned in the Master Continuity Document.

The capabilities implemented in this period are:

| ORQ | Capability | Endpoint / Artifact |
|-----|-----------|---------------------|
| ORQ-11 | Controlled Web Read | `GET /web-read` |
| ORQ-12 | Controlled Notion Read (MCP) | `GET /notion-read/page` |
| ORQ-13 | Notion Read hardening | — |
| ORQ-14 | External Read Consolidation | `docs/external_read_capabilities.md` |
| ORQ-15 | Notion Write Safety Contract | `docs/notion_write_safety_contract.md` |
| ORQ-16 | Notion Write MVP (static validation) | `POST /notion-write/page` |

These capabilities are **stateless, read-only or write-controlled** endpoints, separate from the `/chat` write-path. They do not modify `ProviderPort`, `ChatService`, or the persistence layer.

---

## Consequences

### Positive

- External capabilities (web read, Notion read/write) are practical prerequisites for designing the Execution Orchestrator: the orchestrator needs to know what tools exist before designing the runtime.
- Each external capability delivered independent observable value without blocking on the full orchestrator design.
- The Notion Write safety contract (`docs/notion_write_safety_contract.md`) provides a solid foundation for future orchestrator integration.
- The minimal-diff principle was maintained: each ORQ was a bounded and verifiable change.

### Negative / Trade-offs

- The decision created drift between the plan documented in Notion and the code, since the Master Continuity Document was not updated at the time of the pivot. That drift was the direct motivator for the 2026-06-25 state audit (`docs/private/ANALISIS_ESTADO_PROYECTO_2026-06-25.md`).
- The Execution Orchestrator V2.1 remains pending with no set date.
- By not documenting the decision at the time, it had to be reconstructed retroactively from git history — which is the anti-pattern this ADR system is designed to prevent.

---

## Alternatives Considered

### Alternative A: Implement Execution Orchestrator V2.1 first (original plan)

The Master Continuity Document planned a tool orchestration runtime as the natural next step after V1.1. Rejected because:

- The orchestrator requires defining which tools (capabilities) will exist. Without the external capabilities implemented, the orchestrator design would have been speculative.
- The orchestrator scope is significantly larger (tool-calling, execution state, possibly RAG). External capabilities are more bounded and deliverable incrementally.

### Alternative B: Implement external capabilities AND orchestrator in parallel

Rejected for violating the minimal-diff principle and the Framework V2 scope restriction. A parallel change of that magnitude increases regression risk in the core.

### Alternative C: Defer all external capabilities and wait for a formal roadmap decision

Rejected because external read capabilities (web, Notion) have independent value as context tools for the operator, without requiring the orchestrator.

---

## Evidence

- Commits ORQ-10 to ORQ-16: see Context section above
- `docs/external_read_capabilities.md` — documentation for /web-read and /notion-read endpoints
- `docs/notion_write_safety_contract.md` — ORQ-15 safety contract, foundation for ORQ-16
- `docs/private/ANALISIS_ESTADO_PROYECTO_2026-06-25.md` — state audit that revealed the drift
- `docs/v1_1_closure.md` — V1.1 baseline preceding this ORQ sequence
- `.framework/context.md` — Framework V2 adoption (ORQ-10), starting point of the period
