# ORQ Artifact Guide

Redactar el contenido narrativo de esta ORQ en el idioma definido por `orq_language` o por la decisión explícita del operador.

## Evidence Target Contract

Antes de ejecutar o revisar cualquier task, resolver el evidence target.

### Role to artifact map

- `orchestrator` / `pre-reviewer` -> `review.md` o `pre-review.md`
- `design-reviewer` -> `review.md#Design Review`
- `executor` -> `execution.md`
- `execution-reviewer` -> `review.md#Execution Review` o `execution-review.md` (solo después de evidencia de ejecución)
- `fw-audit` -> auditoría de una entrega ya ejecutada, antes de `fw-preclose`
- `fw-preclose` -> verificación de evidencia y readiness antes de `fw-close`
- `closer` -> `closure.md`
- `governance-sync` -> `governance-sync.md` o `closure.md#Governance Sync`, según el template de la ORQ
- si el sync externo ya está confirmado, la alineación local puede registrarse en `closure.md#Local Sync Status Alignment` sin repetir discovery ni escrituras externas

### tasks.md rule

- `tasks.md` es solo tablero liviano.
- Contiene estado, rol, dependencias y referencias de evidencia.
- No contiene logs largos de ejecución.
- No duplica evidencia de review, execution ni closure.

### Ambiguity rule

Si el evidence target es ambiguo:

- detenerse antes de editar;
- reportar la ambigüedad;
- recomendar el target correcto;
- no inventar un artifact nuevo.

## ORQ routing note

Para ORQs activas, el `README.md` de la ORQ puede incluir una sección breve de routing de evidencia para dejar visible el target esperado por task.

## Standard ORQ Task Flow

Toda ORQ ejecutable debe heredar este flujo salvo política local más estricta documentada:

```text
Task 1 — Design
Task 2 — Design Review
Task 3 — Execution
Task 4 — Execution Review
Task 5 — Closure
Task 6 — Learning & Governance Sync
```

Notas operativas:

- `Task 1 — Design` normalmente se completa durante `fw-create-orq` cuando existe contrato de diseño documentado.
- En una ORQ ejecutable recién creada, la primera task pendiente suele ser `Task 2 — Design Review`.
- Una ORQ puede quedar localmente cerrada después de `Task 5`, pero no debe declararse fully synced hasta completar, marcar `Not required`, dejar `Waived with rationale` o convertir `Task 6` en follow-up ORQ.
