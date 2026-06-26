# ADR-001: Capabilities-First Antes del Execution Orchestrator

**Fecha:** 2026-04-29 (decisión retroactiva; documentada 2026-06-26)  
**Estado:** Aceptada  
**ORQ de referencia:** ORQ-10 a ORQ-16 (ejecución), Documento Maestro de Continuidad (plan original)  
**Superada por / Supera a:** —

---

## Contexto

Al cierre de V1.1 (2026-04-17, `docs/v1_1_closure.md`), el proyecto tenía estabilizado:

- El core de `/chat` con persistencia atómica de 4 pasos
- La abstracción `ProviderPort` con adapters para OpenAI, Bedrock y Stub
- `ResilientProvider` (primary/fallback, sin retry al mismo proveedor)
- Caché Redis best-effort para respuestas no-streaming
- Structured JSON logging y propagación de `request_id`

El **Documento Maestro de Continuidad** (planificación en Notion, referencia "Proyecto LLM Chat Platform ES") contemplaba como siguiente fase una secuencia de ORQs (ORQ-5 a ORQ-9 en la numeración original) orientada a implementar un **Execution Orchestrator V2.1**: un runtime de orquestación de herramientas y tool-calling sobre el dominio de chat existente.

Con la adopción de Framework V2 (ORQ-10, 2026-04-27 a 2026-04-29), se estableció la infraestructura de gobernanza operacional. En ese punto se tomó la decisión de no proceder con el Execution Orchestrator sino con capacidades externas controladas (web read, Notion read, Notion write). Esta decisión nunca fue registrada explícitamente en el momento; el drift entre el plan y el código fue la motivación para crear este ADR retroactivamente.

### Evidencia git del orden real de ejecución

```
96f9619  2026-04-29  Close ORQ-10 framework tooling alignment
f5924ba  2026-04-29  Add controlled web read MVP                      ← primera capacidad externa
333476a  2026-04-30  Close ORQ-11 controlled web read hardening
afefc31  2026-04-30  Add Notion Read configuration and MCP dependency  ← segunda capacidad
e7f3636  2026-04-30  Implement ControlledNotionReadClient (ORQ-12)
b8f5162  2026-04-30  Implement NotionReadService with allowlist enforcement
...
5ca5a54  2026-04-30  ORQ-12 Closure: Remove submodule, finalize documentation
f0d316d  2026-05-08  ORQ-14 Closure: External Read Capabilities Consolidation
5dbc4db  2026-05-09  ORQ-15: Governance sync to Notion
bf6fd50  2026-05-09  ORQ-16: Implement Notion Write MVP with static validation
```

El Execution Orchestrator no aparece en ningún commit del período ORQ-10 a ORQ-16.

---

## Decisión

Decidimos implementar capacidades de lectura y escritura externa controlada (Web Read, Notion Read, Notion Write MVP) **antes** del Execution Orchestrator V2.1, divergiendo del orden planificado en el Documento Maestro de Continuidad.

Las capacidades implementadas en este período son:

| ORQ | Capacidad | Endpoint / Artefacto |
|-----|-----------|---------------------|
| ORQ-11 | Controlled Web Read | `GET /web-read` |
| ORQ-12 | Controlled Notion Read (MCP) | `GET /notion-read/page` |
| ORQ-13 | Notion Read hardening | — |
| ORQ-14 | External Read Consolidation | `docs/external_read_capabilities.md` |
| ORQ-15 | Notion Write Safety Contract | `docs/notion_write_safety_contract.md` |
| ORQ-16 | Notion Write MVP (validación estática) | `POST /notion-write/page` |

Estas capacidades son endpoints **stateless, read-only o write-controlled**, separados del write-path `/chat`. No modifican `ProviderPort`, `ChatService`, ni la capa de persistencia.

---

## Consecuencias

### Positivas

- Las capacidades externas (web read, Notion read/write) son pre-requisitos prácticos para el diseño del Execution Orchestrator: el orchestrator necesita saber qué herramientas existen antes de diseñar el runtime.
- Cada capacidad externa entregó valor observable independiente, sin bloquear en el diseño del orchestrator completo.
- El contrato de seguridad de Notion Write (`docs/notion_write_safety_contract.md`) provee una base sólida para la integración futura con el orchestrator.
- Se mantuvo el principio de minimal-diff: cada ORQ fue un cambio acotado y verificable.

### Negativas / Trade-offs

- La decisión generó drift entre el plan documentado en Notion y el código, ya que el Documento Maestro de Continuidad no fue actualizado al momento del pivote. Ese drift fue el motivador directo de la auditoría de estado 2026-06-25 (`docs/private/ANALISIS_ESTADO_PROYECTO_2026-06-25.md`).
- El Execution Orchestrator V2.1 queda pendiente sin fecha. Depende del cierre limpio de ORQ-16 (bloqueador TEST 4, documentado en `docs/private/ORQ-16-BLOCKER-REPORT.md`) antes de avanzar a ORQ-17.
- Al no documentar la decisión en el momento, fue necesario reconstruirla retroactivamente desde git history, lo cual es el anti-patrón que este sistema de ADRs busca prevenir.

---

## Alternativas Consideradas

### Alternativa A: Implementar Execution Orchestrator V2.1 primero (plan original)

El Documento Maestro de Continuidad planificaba un runtime de orquestación de herramientas como siguiente paso natural después de V1.1. Fue descartada porque:

- El orchestrator requiere definir qué herramientas (tools) existirán. Sin las capacidades externas implementadas, el diseño del orchestrator habría sido especulativo.
- El scope del orchestrator es significativamente mayor (implica tool-calling, estado de ejecución, posiblemente RAG). Las capacidades externas son más acotadas y entregables de forma incremental.

### Alternativa B: Implementar capacidades externas Y orchestrator en paralelo

Descartada por violar el principio de minimal-diff y la restricción de scope de Framework V2. Un cambio paralelo de esa magnitud aumenta el riesgo de regresión en el core.

### Alternativa C: Deferir todas las capacidades externas y esperar una decisión de roadmap formal

Descartada porque las capacidades de lectura externa (web, Notion) tienen valor independiente como herramientas de contexto para el operador, sin necesitar el orchestrator.

---

## Evidencia

- Commits ORQ-10 a ORQ-16: ver sección Contexto arriba
- `docs/external_read_capabilities.md` — documentación de endpoints /web-read y /notion-read
- `docs/notion_write_safety_contract.md` — contrato de seguridad ORQ-15, base para ORQ-16
- `docs/private/ORQ-16-BLOCKER-REPORT.md` — estado actual del bloqueador TEST 4
- `docs/private/ANALISIS_ESTADO_PROYECTO_2026-06-25.md` — auditoría de estado que reveló el drift
- `docs/v1_1_closure.md` — baseline V1.1 que precede a esta secuencia de ORQs
- `.framework/context.md` — adopción Framework V2 (ORQ-10), punto de partida del período
