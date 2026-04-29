# ORQ-10 Tareas

Escribe la narrativa de esta ORQ en español, de acuerdo con `orq_language: es`.

## Estado general

`Task-1 (Completed) → Task-2 (Completed) → Task-3 (Completed) → Task-4 (Completed) → Task-5 (Completed) → Task-6 (Completed)`

## Tareas

| ID | Name | Objective | Role | Status | Dependencies |
| --- | --- | --- | --- | --- | --- |
| task-1 | Confirm drift and scope | Reconfirm the drift classification and the minimum safe alignment set | orchestrator | Completed | - |
| task-2 | Validate alignment approach | Review whether the minimal refresh plan is safe and bounded | design-reviewer | Completed | task-1 |
| task-3 | Apply minimal refresh | Add only the approved canonical artifact available in the central Framework and preserve local-intentional prompts | executor | Completed | task-2 |
| task-4 | Declare artifact policy | Decide and record `artifact_policy` explicitly | orchestrator | Completed | task-3 |
| task-5 | Re-run fw-framework-check | Verify the new state read-only and capture remaining drift | execution-reviewer | Completed | task-4 |
| task-6 | Close ORQ-10 | Consolidate results, residual drift, and next step | closer | Completed | task-5 |

## Notas de coordinación

- Mantener el refresh estrictamente mínimo.
- No sobrescribir artefactos locales intencionales.
- Mantener visibles los archivos protegidos y el drift residual.
- No tocar runtime/producto.
- No marcar el repo como synced automáticamente.
- Si `artifact_policy` queda en duda, resolverlo explícitamente antes del cierre.

## Task evidence

- task-1: See ORQ-10 Pre-Review — drift confirmed, artifacts classified, and minimum safe alignment set defined
- task-2: See `review.md#design-review` — Approved for Execution
- task-3: See `execution.md#task-3--apply-minimal-refresh` — Templates refreshed, local prompts preserved
- task-4: See `execution.md#task-4--declare-artifact-policy` — artifact_policy: local-only declared in project-config.yml
- task-5: See `review.md#Execution Review` — read-only fw-framework-check executed; residual drift captured
- task-6: See `closure.md` — ORQ-10 locally closed
