# ORQ-10: Framework V2 Drift Review & Minimal Local Tooling Alignment

## Propósito

ORQ-10 existe para revisar el drift detectado por `fw-framework-check` y aplicar una alineación mínima y controlada del tooling local del Framework V2 en el repo consumidor `llm-chat-platform`.

La decisión tomada antes de abrir esta ORQ es evitar un refresh masivo. En su lugar, esta ORQ solo debe incorporar los artefactos canónicos faltantes necesarios para completar el tooling local mínimo del Framework V2 y declarar una política explícita de `artifact_policy`, preservando el contexto local, el historial ORQ y el runtime del producto.

## Estado

**Open**

- ✅ Drift detectado por `fw-framework-check`
- ✅ Pre-review completado con clasificación inicial de artefactos
- ⏳ Pending: design review de la alineación mínima
- ✅ Refresh controlado del artefacto canónico disponible
- ⏳ Pending: decisión explícita sobre `artifact_policy`
- ✅ Re-ejecución read-only de `fw-framework-check`
- ✅ Cierre local de la ORQ

## Contenidos

- [Especificación](spec.md) — Objetivo, contexto, alcance, restricciones y decisión propuesta
- [Criterios de Aceptación](acceptance.md) — Validación observable de la alineación mínima
- [Tareas](tasks.md) — Secuencia mínima para revisión, aplicación y cierre
- [Revisión](review.md) — Design review y execution review
- [Cierre](closure.md) — Resultado final, learnings y sync debt cuando corresponda
