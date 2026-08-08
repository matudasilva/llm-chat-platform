# Architecture Decision Records (ADRs)

Este directorio contiene los registros de decisiones arquitectónicas del proyecto LLM Chat Platform.

---

## Propósito

Un ADR documenta **una decisión técnica o arquitectónica significativa**: qué se decidió, por qué, qué alternativas se descartaron y cuáles son las consecuencias esperadas.

**Principio fundamental:** la decisión y su implementación viajan en el mismo PR. Nunca se documentan por separado. Si un cambio en el código no tiene ADR cuando debería tenerlo, el PR no está completo.

Esto resuelve el problema histórico de este proyecto: decisiones tomadas en el código que no tienen correlato en la documentación de planificación (Notion, docs/), generando drift entre lo implementado y lo registrado.

---

## Cuándo crear un ADR

Crear un ADR cuando la decisión:

- Cambia la arquitectura del sistema (capas, contratos, abstracciones)
- Diverge del plan documentado (Notion, LLD, AGENTS.md)
- Introduce o elimina una dependencia externa significativa
- Afecta la estrategia de despliegue, observabilidad o seguridad
- Es irreversible o costosa de revertir
- Genera trade-offs no obvios que un revisor futuro necesitaría entender

No crear un ADR para: bug fixes, refactors internos sin cambio de contrato, cambios de configuración triviales.

---

## Convención de Numeración

```
NNN-titulo-en-kebab-case.md
```

- `NNN`: número secuencial de tres dígitos, comenzando en `001`
- El título describe la decisión, no el problema: `001-capabilities-first-over-execution-orchestrator.md`
- Nunca reutilizar ni renumerar. Si una decisión es revertida, crear un nuevo ADR que la supere.

### Ejemplo

```
docs/adr/001-capabilities-first-over-execution-orchestrator.md
docs/adr/002-redis-cache-best-effort-non-streaming-only.md
docs/adr/003-...
```

---

## Ciclo de Vida de un ADR

| Estado | Significado |
|--------|-------------|
| `Propuesta` | Bajo discusión; no implementada aún |
| `Aceptada` | Decisión tomada e implementada |
| `Superada` | Reemplazada por otra decisión; ver campo "Superada por" |

Los ADRs aceptados **no se modifican** salvo para actualizar el estado a "Superada" y agregar la referencia al ADR que la reemplaza.

---

## Template

Ver [`template.md`](template.md) para la estructura mínima de un nuevo ADR.

---

## Índice

| # | Título | Estado | Fecha |
|---|--------|--------|-------|
| [001](001-capabilities-first-over-execution-orchestrator.md) | Capabilities-first antes del Execution Orchestrator | Aceptada | 2026-04-29 |
| [002](002-orq17-phase0-closure-resequencing.md) | ORQ-17 Phase 0 closure resequencing | Aceptada | 2026-06-29 |
| [003](003-multitenancy-transversal-foundation.md) | Multitenancy Transversal Foundation — Row-Level with Deferred RLS | Aceptada | 2026-06-30 |
| [004](004-tenant-scoping-read-endpoints.md) | Tenant Scoping for Read Endpoints — Application-Layer Filter | Aceptada | 2026-07-01 |
| [005](005-paas-provider.md) | PaaS Provider for Staging Deployment | Aceptada | 2026-07-06 (rev. 2026-07-08) |
| [006](006-rag-corpus-embeddings-and-rls.md) | RAG Corpus — Embedding Space, Row-Level Security, and HNSW Parameters | Aceptada | 2026-07-29 |
| [007](007-reranker-availability-cascade.md) | Reranker Availability — GCP Primary, AWS Fallback Cascade | Aceptada | 2026-08-06 |
| [008](008-rag-generation-and-feedback-boundaries.md) | RAG Generation and Feedback Boundaries | Aceptada | 2026-08-06 |
| [009](009-rag-evaluation-harness.md) | RAG Evaluation Harness — Instrument, Store, and Pre-registration | Propuesta | 2026-08-08 |
