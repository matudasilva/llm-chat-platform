# ADR-002: ORQ-17 Phase 0 Closure — Technical Debt Resolution and ORQ Resequencing

**Fecha:** 2026-06-29  
**Estado:** Aceptada  
**ORQ de referencia:** ORQ-17

---

## Contexto

Al inicio del sprint de cierre de Fase 0, se realizó una auditoría técnica del estado del repositorio que identificó tres hallazgos de deuda técnica (F1–F3) heredados de la V1.1:

- **F1:** `tree.md` no existía en la raíz del repositorio (referenciado en AGENTS.md como artefacto de orientación).
- **F2:** `app/scripts/run_stub_chat.py:7` tenía un import bare (`from core.providers.stub_provider`) en lugar del path calificado completo (`from app.core.providers.stub_provider`), lo que causaba un `ModuleNotFoundError` al ejecutar el script desde la raíz del repo. Ningún check de CI detectaba este tipo de regresión.
- **F3:** `tests/test_cost_report_pipeline.py` tenía un `pytest.skip` hardcodeado con el comentario "script not present". El script `run_cost_report.py` sí existía en `app/scripts/` pero el resolver de rutas del test no incluía ese path como candidato, por lo que el test nunca corría.

Adicionalmente, el número ORQ-17 estaba reservado en documentación histórica para "RAG Baseline". Se tomó la decisión de resecuenciar deliberadamente para priorizar el cierre de Fase 0.

---

## Decisión

### Resecuenciación ORQ-17

Decidimos reasignar ORQ-17 al cierre de Fase 0 (deuda técnica V1.1 + tag de estabilidad) y mover RAG Baseline a ORQ-18. La Fase 0 debe cerrarse antes de introducir features nuevas para mantener la integridad del baseline de estabilidad.

### F1 — Regenerar tree.md

Decidimos generar `tree.md` en la raíz del repo con `tree -I '__pycache__|*.pyc|.git'`. No se modifica AGENTS.md porque la línea 18 ya establece explícitamente que `tree.md` no es fuente autoritaria.

### F2 — Corregir import y agregar smoke check CI

Decidimos corregir el import en `run_stub_chat.py` al path calificado completo y agregar un step de smoke check en `.github/workflows/ci.yml` que hace un AST scan sobre todos los scripts en `app/scripts/`, fallando si detecta imports con prefijo `core.` sin `app.`. Esto previene la regresión a futuro sin requerir ejecución real de los scripts.

### F3 — Rehabilitar el test (Opción A)

Decidimos rehabilitar `tests/test_cost_report_pipeline.py` en lugar de eliminarlo. El script `run_cost_report.py` existe y los 4 tests del archivo son válidos. El fix es agregar el candidato de ruta faltante (`{repo_root}/app/scripts/run_cost_report.py`) y eliminar el `pytest.skip`. El test se incorpora al baseline de CI.

---

## Consecuencias

### Positivas

- El repo queda en estado limpio y auditable como Fase 0 cerrada.
- El smoke check de CI previene regresiones futuras en imports de scripts.
- Los 4 tests del cost report pipeline quedan activos y en CI.
- El tag `v1.1-stable` marca el baseline de estabilidad de manera formal.
- La resecuenciación ORQ-17→Fase0 / ORQ-18→RAG está documentada y trazable.

### Negativas / Trade-offs

- El número ORQ-17 queda consumido por un ORQ de mantenimiento, no por una feature. Esto es intencional y deliberado.
- El smoke check de CI agrega un step liviano pero no reemplaza tests de integración reales para scripts.

---

## Alternativas Consideradas

### Alternativa A (F3): Eliminar test_cost_report_pipeline.py

Descartar el archivo de test porque el skip lo tenía efectivamente muerto. Se descartó porque el script existe, los tests son válidos y eliminarlos sería pérdida de cobertura sin beneficio.

### Alternativa B (ORQ-17): Mantener reserva para RAG Baseline

No resecuenciar y abrir un nuevo número para el cierre de Fase 0. Se descartó porque la resecuenciación tiene un costo de documentación menor que la deuda de mantener el repo en estado sucio antes de avanzar con features nuevas.

---

## Evidencia

- Hallazgos F1–F3: auditoría técnica pre-ORQ-17 (2026-06-29)
- Script roto: `app/scripts/run_stub_chat.py:7` (import `core.providers.stub_provider`)
- Script existente pero no encontrado: `app/scripts/run_cost_report.py`
- Framework version confirmada: `.framework/framework-version` = `v2.0.3`
- Tag creado: `v1.1-stable` (post-commit de este ORQ)
