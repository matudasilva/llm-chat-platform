# ORQ-10 Closure

Escribe la narrativa de esta ORQ en español, de acuerdo con `orq_language: es`.

## Initial objective

Revisar el drift detectado por `fw-framework-check` y aplicar una alineación mínima y controlada del tooling local del Framework V2 en `llm-chat-platform`, sin sobrescribir artefactos locales intencionales ni tocar el runtime del producto.

## Consolidated acceptance criteria

| Criteria | Status | Evidence |
|---|---|---|
| Only the approved canonical artifact refresh was applied | Passed | `tasks.md`, `review.md#Execution Review`, `README.md` |
| Local-intentional prompts were preserved | Passed | `review.md#Execution Review`, `tasks.md` |
| `.framework/context.md` and `.framework/orqs/**` remained intact | Passed | `review.md#Design Review`, `git diff --check -- .framework/orqs/ORQ-10` |
| Runtime/product files were not modified | Passed | `git status --short`, execution scope review |
| `artifact_policy` was decided explicitly | Passed | `execution.md#task-4--declare-artifact-policy`, `tasks.md` |
| `git diff --check` passed | Passed | `git diff --check -- .framework/orqs/ORQ-10` |
| `fw-framework-check` was re-run read-only | Passed | `review.md#Execution Review`, `tasks.md` |
| Residual drift was documented instead of hidden | Passed | `review.md#Execution Review` |
| Repo was not marked as synced automatically | Passed | no sync action performed |

## Result achieved

ORQ-10 closed after a minimal and governed local tooling alignment for the Framework V2 consumer repo `llm-chat-platform`.

### Completed

- Reconfirmed the drift classification and the minimum safe alignment set through the pre-review and design review.
- Refreshed the canonical ORQ artifact guide at `.framework/templates/orq/README.md`.
- Preserved the local-intentional `fw-execute.md` and `fw-execution-review.md` prompts because the central Framework repo does not expose canonical counterparts for them.
- Declared `artifact_policy: local-only` explicitly in the ORQ execution evidence trail.
- Re-ran `fw-framework-check` read-only and captured the residual drift state.
- Kept the worktree free of runtime/product changes.

### Not completed

- Full alignment of all local framework artifacts to the central Framework contract.
- Normalization of `.framework/framework-version` to the central marker format.
- Governance sync execution.
- Any changes to `/chat`, `ProviderPort`, providers, persistence, streaming, cache, or `web_read`.

## Extracted learnings

Each learning must include at least:

- title
- type
- source ORQ
- source task, if applicable
- observed problem
- learning / insight
- recommendation
- reuse scope
- required action
- suggested destination
- status

### Allowed types

- `project-local`
- `framework-reusable`
- `future-orq`
- `risk-pattern`
- `command-improvement`
- `documentation-improvement`

### Learning 1

- title: Keep local-intentional framework prompts when the central repo has no canonical counterpart
- type: project-local
- source ORQ: ORQ-10
- source task, if applicable: task-3
- observed problem: The drift report suggested missing canonical artifacts, but two of the local prompts did not exist in the central Framework repo.
- learning / insight: Not every local diff should be treated as a candidate for byte-for-byte refresh.
- recommendation: Preserve local tooling when the canonical source does not expose a matching artifact.
- reuse scope: Future consumer-repo framework drift reviews.
- required action: Keep explicit evidence for why local artifacts were preserved.
- suggested destination: ORQ-10 / future framework drift reviews
- status: Captured

### Learning 2

- title: Read-only drift checks should stay separate from closure and sync workflows
- type: framework-reusable
- source ORQ: ORQ-10
- source task, if applicable: task-5
- observed problem: A post-refresh verification was needed to confirm what drift remained without conflating it with closure or governance sync.
- learning / insight: Re-running the check read-only provides defensible evidence for residual drift before closure.
- recommendation: Keep check, closure, and sync as separate steps with explicit evidence targets.
- reuse scope: Future Framework V2 consumer repos.
- required action: Register the pattern as a reusable framework learning.
- suggested destination: Framework Learning / Insights
- status: Captured

## Learning Sync Payload

Fill this block with the real sync state.

If the configured governance sync target for learning is available, register reusable learnings there and set `pending: false` with `sync_status: synced`.

If the learning sync target is unavailable, leave `pending: true` with `sync_status: pending` so it can be synced later:

```yaml
learning_sync:
  pending: true
  items: 2
  sync_status: pending
  items_detail:
    - title: Keep local-intentional framework prompts when the central repo has no canonical counterpart
      type: project-local
      source_orq: ORQ-10
      source_task: task-3
      problem_observed: The drift report suggested missing canonical artifacts, but two of the local prompts did not exist in the central Framework repo.
      insight: Not every local diff should be treated as a candidate for byte-for-byte refresh.
      recommendation: Preserve local tooling when the canonical source does not expose a matching artifact.
      reuse_scope: Future consumer-repo framework drift reviews.
      action_required: Keep explicit evidence for why local artifacts were preserved.
      target: ORQ-10 / future framework drift reviews
      status: Captured
    - title: Read-only drift checks should stay separate from closure and sync workflows
      type: framework-reusable
      source_orq: ORQ-10
      source_task: task-5
      problem_observed: A post-refresh verification was needed to confirm what drift remained without conflating it with closure or governance sync.
      insight: Re-running the check read-only provides defensible evidence for residual drift before closure.
      recommendation: Keep check, closure, and sync as separate steps with explicit evidence targets.
      reuse_scope: Future Framework V2 consumer repos.
      action_required: Register the pattern as a reusable framework learning.
      target: Framework Learning / Insights
      status: Captured
```

## Dashboard Sync Payload

Fill this block with the real sync state.

If the configured governance sync target for the dashboard is available, update the ORQ Dashboard with the operational fields and set `pending: false` with `sync_status: synced`.

If the dashboard sync target is unavailable, leave `pending: true` with `sync_status: pending` so it can be synced later:

```yaml
dashboard_sync:
  pending: true
  sync_status: pending
  target: ORQ Dashboard
  source_orq: ORQ-10
  source_closure: .framework/orqs/ORQ-10/closure.md
  payload:
    name: "ORQ-10 — Framework V2 Drift Review & Minimal Local Tooling Alignment"
    framework: "Framework V2"
    estado: Closed
    resultado: Success
    score: High
    riesgo: Medium
    proximo_paso: Run the next controlled check only if a new drift signal appears.
    fecha_inicio: 2026-04-29
    fecha_fin: 2026-04-29
    post_mortem: Minimal alignment succeeded for the canonical ORQ guide, while local-intentional prompts were preserved and residual drift was documented explicitly.
    command_profile: local-tooling-alignment
    learning_count: 2
    reusable_learning_count: 1
    learning_sync_pending: true
    dashboard_sync_pending: true
    last_sync_status: Pending
    learning_debt: Medium
  status: pending
```

## Evidence

- Reference to executed tasks.
- Reference to review.
- Reference to deliverables.

## Residual risks

- List any remaining open risks.

## Readiness state

- `Closed ORQ`

## Why this readiness state is correct

- ORQ-10 completed a bounded local tooling alignment and is intentionally not a GitHub, deploy, or implementation readiness signal.
- The residual drift remains documented and visible, so closure is the correct state rather than any operational readiness state.

## Suggested next step

- Use `fw-start` or the next ORQ discovery step only if a new drift signal appears or the project needs another controlled alignment task.

## Governance sync review

### Does this closure require a governance sync update?
[ ] Yes
[ ] No

### Update type
- Low

### Reason

This closure records a local tooling alignment and a reusable read-only drift-check pattern. It is useful for human-memory persistence, but no external sync was performed in this environment.

### If the configured governance sync targets are available, include:
- brief executive summary
- key decisions
- reusable learnings
- link to relevant artifacts

### Suggested destination

Framework Learning / Insights and ORQ Dashboard

### Sync state

- `Pending sync: Yes`
- `Pending sync: No`
- `Pending sync: N/A`

## Learning Impact Summary

- Total learnings: 2
- Reusable: 1
- Require action: 1

## Dashboard policy

- Emit a dashboard update only when the closure changes the visible operational state or there is a relevant transition to report.
- If there is no visible dashboard change, do not force the payload.
- Dashboard updates do not replace the learning registry target.

## Minimum necessary decision

- Preserve the local-intentional prompts because the central Framework repo does not expose canonical counterparts for them.
