# AGENTS.md

## Project
LLM Chat Platform API

## Purpose
This repository implements a portfolio-grade backend platform for LLM chat workloads.
The project emphasizes architectural clarity, provider abstraction, observability, cost awareness, reproducibility, and minimal-diff iterative delivery.

## Source of truth
Assume the following documents are authoritative and must remain aligned with implementation:

- `Proyecto_LLM_Chat_Platform_V1.1.pdf`
- `README.md`
- `docs/lld_llm_chat_platform_live_doc.md`
- `docs/lld_apendix.md`

Repository structure is validated from the current working tree using reproducible commands when needed. `tree.md` is not treated as an authoritative source of truth.

Suggested command:

```bash
find . -maxdepth 3 \
  -not -path "./.git/*" \
  -not -path "./.venv/*" \
  -not -path "*/__pycache__/*" \
  -not -path "./.pytest_cache/*" \
  | sort
```

Do not redefine architecture, scope, or system intent unless explicitly requested.

## Mandatory language rules
Use English for:
- code
- documentation
- config comments
- commit messages
- inline TODOs
- test names
- architectural notes stored in the repository

ORQ narratives and framework operational text may use Spanish when `orq_language: es`; repository artifacts must remain in English unless a framework artifact explicitly requires another language.

Explanations in chat may be in Spanish, but repository artifacts must remain in English.

## Core system invariants
These are non-negotiable:

- `/chat` is the only write-path
- persistence must remain atomic and consistent
- the system must remain provider-agnostic
- domain services must not depend on concrete providers
- no provider-specific logic in routes
- no provider-specific logic in domain services
- telemetry must remain best-effort even on failure
- streaming must not break
- fallback after partial stream emission is not allowed
- resilience and observability must remain additive, not invasive

If a proposed change violates any invariant, reject or adjust it.

## Scope discipline
Work architecture-first and keep a minimal-diff mindset.

Do:
- prefer the smallest safe change
- preserve existing boundaries
- improve clarity and testability
- reflect actual behavior in docs
- keep changes incremental and reviewable

Do not:
- introduce feature creep
- add V2 concepts into V1.1 work
- redesign working architecture without explicit approval
- add unnecessary abstractions
- expand a task beyond the requested scope
- mix unrelated technical and documentation changes

## Working mode
Always work in this sequence:

1. Propose
2. Wait for confirmation
3. Implement

Before implementing:
- state the intended scope
- identify the smallest affected surface
- call out risks if any
- keep the plan incremental

## Change boundaries
Prefer changing, in this order:
1. tests
2. test fixtures
3. documentation
4. isolated adapters or infra seams
5. production logic only if clearly required

Avoid touching:
- routes
- `ChatService`
- provider contracts
- persistence flow
- streaming flow

unless the task explicitly requires it.

## Provider architecture rules
Providers must remain adapter-level integrations behind the existing provider contract.

Rules:
- no provider-specific behavior in route handlers
- no provider-specific behavior in domain services
- preserve current normalization/error semantics
- preserve current retry/fallback semantics unless explicitly in scope
- preserve streaming semantics unless explicitly in scope
- keep provider observability additive and consistent

## Testing rules
When fixing failures:
- diagnose root cause before patching
- prefer test-local fixes when the issue is environment-coupled
- preserve contract-level assertions
- avoid broad refactors in test infrastructure unless necessary
- validate with the narrowest useful pytest scope first
- expand validation gradually

When writing tests:
- keep them deterministic
- prefer explicit fixtures over hidden coupling
- separate contract tests from integration tests
- avoid unnecessary external/environmental dependencies

## Documentation discipline
Documentation must reflect real implementation, not future intent.

Rules:
- update only the affected sections
- keep diffs minimal
- do not rewrite entire documents unnecessarily
- make implementation status easy to defend in interviews
- record validation evidence in the appendix when relevant

## Architecture Decisions (ADRs)
Before implementing an architecture change or direction pivot, review `docs/adr/` for related prior decisions.
If the task requires a new decision, write the ADR in `docs/adr/NNN-title.md` using `docs/adr/template.md`.
The ADR must be included in the same PR as the code that implements it, never separately.
See `docs/adr/README.md` for the full ADR workflow.

## Commit strategy
Split meaningful work into:
1. technical commit
2. documentation commit

Rules:
- keep commits small and clear
- use English commit messages
- tags point to the final documentation commit for the day
- do not bundle unrelated changes in one commit

## Diagram maintenance
Mermaid diagrams under `docs/working/diagrams/` are design artifacts and architectural context.

When changing:
- architecture
- boundaries
- request flow
- provider flow
- streaming or fallback behavior
- persistence flow

update the corresponding Mermaid diagram if it becomes stale.

Rules:
- prefer minimal updates to existing diagrams instead of creating new ones
- keep diagram names stable unless the scope changes materially
- do not implement Mermaid tooling as a product feature unless explicitly requested
- render diagrams only when local Mermaid rendering is available and explicitly requested

## What to include in task responses
Before implementation, provide:
- objective
- scope boundaries
- likely files affected
- minimal-diff plan
- validation approach

After implementation, provide:
- exact files changed
- concise diff summary
- validation commands run
- observed results
- explicit confirmation of what did not change

## Default task posture
Unless explicitly requested otherwise:
- assume V1.1 scope
- prefer consolidation over expansion
- prefer reliability over new features
- prefer testability over cleverness
- prefer additive hardening over redesign
