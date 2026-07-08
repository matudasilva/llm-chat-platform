# ADR-005: PaaS Provider for Staging Deployment

**Date:** 2026-07-06 (created) — **Revised:** 2026-07-08 (decision changed after Design Review Ronda 1; corrected after Ronda 2)
**Status:** Accepted
**ORQ reference:** ORQ-20
**Superseded by / Supersedes:** —

---

## Context

ORQ-20 introduces the first deploy pipeline for the platform (Dev → Prod, staging first). The backend must run on a managed PaaS that provides: managed Postgres, managed Redis, container-based deploys from a registry image, and a reasonable cost profile for a project with no production traffic yet (idle most of the time).

Three options are viable given available cloud credits and the project's current provider integrations:

| Eje | AWS App Runner | GCP Cloud Run | Fly.io |
|---|---|---|---|
| Créditos disponibles | ✅ Sí | ✅ Sí | ❌ No |
| Provider LLM ya integrado | ✅ Bedrock (`app/core/providers/bedrock_provider.py`, en producción en el codebase) | ➕ Vertex AI (futuro, ORQ-21+, no integrado aún) | — |
| Postgres administrado | RDS / Aurora Serverless v2 | Cloud SQL | Fly Postgres (unmanaged, self-hosted en su infra) |
| Redis administrado | ElastiCache / Upstash | Memorystore | Upstash (vía integración externa) |
| Escala a cero | Con auto-pause (arranque en frío al primer request) | Sí, nativo (arranque en frío) | Sí |
| Complejidad primer deploy | Media (service config + IAM role) | Media (similar) | Baja (`fly launch` friccion mínima) |
| Lock-in | Medio (AWS-specific service config) | Medio (Cloud Run YAML) | Bajo (contenedor estándar) |
| Observabilidad nativa | CloudWatch | Cloud Monitoring | Métricas básicas (Grafana add-on) |

La decisión original (2026-07-06) eligió AWS App Runner por proximidad de cloud con Bedrock (ver sección "Alternativas Consideradas" para el detalle de esa decisión, ahora descartada).

### Revisión post Design Review (2026-07-08)

Task 2 — Design Review (Codex, `.framework/orqs/ORQ-20/review.md`, `REQUEST CHANGES`) identificó dos bloqueantes técnicos confirmados contra la documentación oficial de AWS:

1. **App Runner en modo image-based solo acepta imágenes de Amazon ECR o Amazon ECR Public** — no soporta GHCR directo, contradiciendo el diseño de pipeline ya aprobado (CI publica a `ghcr.io/matudasilva/llm-chat-platform`).
2. **`apprunner.yaml` solo aplica a servicios basados en source code**, no a servicios image-based — la config nativa propuesta en el diseño original no es utilizable con el pipeline de esta ORQ.
3. **Hallazgo adicional (verificado en vivo, 2026-07-08):** AWS App Runner dejó de aceptar clientes nuevos desde el **30 de abril de 2026** (reemplazado por Amazon ECS Express Mode como ruta de migración recomendada por AWS). Independientemente de esto, la cuenta AWS del proyecto se encontró en estado "Free Plan" (alta de cuenta incompleta) al momento de esta revisión, lo que habría bloqueado cualquier ruta de cómputo en AWS (App Runner o ECS Express Mode) hasta completar el upgrade de plan — un paso adicional no controlado por el pipeline de esta ORQ.

Con estos tres hallazgos, App Runner queda descartado como decisión de esta ADR. El orquestador del proyecto (sesión de gobernanza, 2026-07-08) resolvió la decisión de reemplazo, documentada en el doc maestro (Notion, sección 7.1), incorporando además la elección de proveedores administrados de Postgres y Redis (no cubierta por la tabla original, que asumía los servicios nativos de cada cloud).

### Corrección post Design Review Ronda 2 (2026-07-08)

Ronda 2 de Task 2 identificó que la premisa "Cloud Run soporta imágenes de GHCR directamente" (usada como razón principal para elegir Cloud Run en la revisión anterior de este mismo documento) es **incorrecta**. Según la documentación oficial de Cloud Run ("Supported container registries and images"), Cloud Run solo soporta **Artifact Registry y Docker Hub** de forma nativa; GHCR (y otros registries externos) requieren un **Artifact Registry remote repository** configurado como proxy. Esta corrección **no cambia la decisión de PaaS** (Cloud Run sigue siendo la opción elegida) — cambia el mecanismo de conexión entre el pipeline CI (que sigue publicando solo a GHCR, sin cambios) y el servicio de cómputo: se agrega un paso de infraestructura único (crear el remote repository) documentado en `spec.md`. Ver sección Decision, punto 1, corregido.

## Decision

Reemplazamos la decisión original por: **GCP Cloud Run** para cómputo, **Neon** como Postgres administrado, **Upstash** como Redis administrado — todos para el entorno de staging de esta ORQ.

Rationale, en orden de peso:

1. **Cloud Run soporta GHCR a través de un Artifact Registry remote repository** (proxy configurado una única vez, sin credenciales porque el package es público) — a diferencia de App Runner, que no tiene ningún mecanismo equivalente para consumir un registry externo en modo image-based (solo ECR/ECR Public, sin opción de proxy). El pipeline CI ya diseñado (`docker-publish.yml` → GHCR) no cambia; el proxy es un recurso de infraestructura del lado de GCP, no un cambio de pipeline. *(Corregido en Ronda 2 — la afirmación original de "soporte directo sin pasos intermedios" era incorrecta, ver `spec.md` para el mecanismo real.)*
2. **Créditos GCP disponibles y con vencimiento próximo:** trial de **US$299.96, vence el 27 de agosto de 2026** — usarlos para staging ahora evita perderlos sin uso. Los **US$1.000 de crédito GenAI de GCP quedan reservados íntegros para Vertex AI** (ORQ-21+, no se consumen en esta ORQ).
3. **Neon y Upstash tienen free tier permanente** (no expira, a diferencia del trial de GCP): el costo de staging con tráfico intermitente queda en ≈ US$0. Esto es preferible a Cloud SQL/Memorystore (los servicios administrados nativos de GCP considerados originalmente en la tabla), que no tienen un tier gratuito equivalente y consumirían crédito del trial de forma continua mientras el servicio esté activo, aunque no reciba tráfico.
4. **AWS sigue siendo el cloud del provider LLM activo (Bedrock)**, consumido vía HTTPS con credenciales IAM — no requiere que el cómputo esté en el mismo cloud (mismo razonamiento ya usado en la decisión original para justificar que Vertex AI tampoco requeriría same-cloud placement; se aplica ahora en sentido inverso a Bedrock). AWS deja de ser el cloud de cómputo, pero sigue siendo el cloud del LLM provider en producción — no hay cambio de código, solo de dónde corre el contenedor.
5. **Cloud Run ya estaba evaluado en la tabla original** con una puntuación casi idéntica a App Runner (la única diferencia real era el argumento de "mismo cloud que Bedrock", que queda anulado por los bloqueantes técnicos de App Runner) — el cambio de decisión no requiere research adicional ni una opción nueva no evaluada.

## Consequences

### Positive

- El pipeline CI (GHCR público) funciona sin cambios — el puente hacia Cloud Run se resuelve con un recurso de infraestructura (Artifact Registry remote repository) creado una única vez, no con cambios recurrentes de pipeline.
- Costo de staging ≈ US$0 mientras dure el trial de GCP (Cloud Run factura por uso con scale-to-zero nativo) y de forma permanente después (Neon/Upstash free tier no expira).
- Los US$1.000 de crédito GenAI de GCP quedan intactos para Vertex AI en ORQ-21+ — esta ORQ no los toca.
- No depende de resolver el estado de alta de la cuenta AWS (Free Plan) ni de la ambigüedad de elegibilidad de App Runner — dos bloqueantes operativos fuera del control de esta ORQ.
- `docker-compose.prod.yml` (fallback portable, este ORQ) sigue siendo válido como ruta de escape a cualquier otro host compose-compatible (VPS, staging local), independientemente del PaaS elegido.

### Negative / Trade-offs

- Se pierde el argumento de "mismo cloud que el LLM provider activo": Bedrock se sigue llamando desde fuera de AWS, lo que implica manejar credenciales AWS (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`) como secretos cross-cloud en GCP, en vez de IAM roles nativos. Mitigación: son las mismas credenciales que ya se usan en local/dev vía variables de entorno; no es un mecanismo nuevo, solo un cloud distinto sirviéndolas.
- Neon y Upstash son terceros externos a GCP (no Cloud SQL/Memorystore) — agrega dos proveedores adicionales a los que dar de alta y monitorear, en vez de mantenerlo todo dentro de la consola de un solo cloud.
- El trial de GCP (US$299.96) vence el 27 de agosto de 2026 — si el staging sigue activo después de esa fecha, Cloud Run pasa a facturar contra la cuenta de facturación real (mitigado por el bajo costo esperado de Cloud Run con scale-to-zero y tráfico de staging bajo).
- Se abandona la decisión original (App Runner) después de haber sido documentada y aprobada como Task 1 inicial — costo de retrabajo ya absorbido en esta revisión, documentado aquí para trazabilidad, no oculto.

## Alternatives Considered

### AWS App Runner (decisión original, descartada en esta revisión)

Seleccionada inicialmente (2026-07-06) por integración ya activa de Bedrock (mismo cloud, misma identidad IAM/billing) y créditos AWS disponibles. Descartada tras Design Review (2026-07-08) por tres motivos acumulados: (1) App Runner image-based no soporta GHCR, solo ECR/ECR Public; (2) `apprunner.yaml` no aplica a servicios image-based; (3) App Runner está cerrado a nuevos clientes desde el 30/04/2026, y la cuenta AWS del proyecto además se encontró en estado de alta incompleta ("Free Plan") al momento de la revisión. AWS ECS Express Mode se exploró informalmente como posible alternativa dentro de AWS (confirmado accesible desde la consola del proyecto, con soporte de imagen genérica compatible con GHCR vía el campo "Image URI"), pero no fue seleccionada: la decisión de gobernanza (2026-07-08) priorizó GCP por el trial de crédito con vencimiento próximo y el free tier permanente de Neon/Upstash, reservando el crédito GenAI de AWS/GCP de forma más clara para Vertex AI en ORQ-21+.

### GCP Cloud Run (seleccionada)

Comparable en madurez de servicios administrados y perfil de costo a App Runner, con mejor scale-to-zero nativo y créditos disponibles. **Corrección Ronda 2:** Cloud Run no pullea GHCR directo — requiere un Artifact Registry remote repository como proxy (paso único, sin impacto en el pipeline CI). Aun con esta corrección, resuelve el bloqueante técnico principal de App Runner (que no tiene ningún mecanismo de proxy equivalente para registries externos en modo image-based). Combinada con Neon (Postgres) y Upstash (Redis) en vez de Cloud SQL/Memorystore, por el free tier permanente de ambos frente al trial con vencimiento de GCP.

### Fly.io

Menor fricción de primer deploy y totalmente portable (contenedores estándar, sin config propietaria). Descartada por falta de créditos disponibles — costo real desde el día uno en un proyecto sin tráfico de producción — y sin beneficio de integración que lo compense frente a las dos opciones con créditos.

## Evidence

- `app/core/providers/bedrock_provider.py` — implementación existente de `ProviderPort` para Bedrock, evidencia de integración AWS activa (no afectada por este cambio de cloud de cómputo).
- `app/core/settings.py` — `DATABASE_URL` alias, `provider`/`fallback_provider` ya environment-driven; no se requiere cambio de código para apuntar a Neon/Upstash (mismos contratos de configuración).
- `.framework/orqs/ORQ-20/review.md` — Task 2 Design Review, `REQUEST CHANGES`, bloqueantes 1 y 5 (App Runner + GHCR/`apprunner.yaml` no ejecutable; decisión dependiente de elegibilidad de cuenta no verificada).
- AWS App Runner official docs (fetched 2026-07-06/2026-07-08):
  - https://docs.aws.amazon.com/apprunner/latest/dg/service-source-image.html — confirma ECR/ECR Public como únicos proveedores de imagen soportados.
  - https://docs.aws.amazon.com/apprunner/latest/dg/config-file-ref.html — confirma que `apprunner.yaml` solo aplica a servicios source-code.
  - https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html — confirma cierre a nuevos clientes desde el 30/04/2026 y recomienda ECS Express Mode como ruta de migración.
- Doc maestro (Notion, "Proyecto LLM Chat Platform ES", sección 7.1) — decisión de gobernanza (2026-07-08): GCP Cloud Run + Neon + Upstash, créditos GCP $299.96 (vence 27/08/2026) y $1.000 GenAI reservado para Vertex AI.
- Verificación en vivo (2026-07-08, operador): cuenta AWS del proyecto en estado "Free Plan" (alta incompleta); wizard de ECS Express Mode accesible sin bloqueo y compatible con imagen genérica (incluida GHCR) vía campo "Image URI".
- Google Cloud Run official docs (fetched 2026-07-08, Ronda 2): https://docs.cloud.google.com/run/docs/deploying — confirma que Cloud Run solo soporta Artifact Registry y Docker Hub de forma nativa; GHCR requiere un Artifact Registry remote repository.
- Google Cloud Artifact Registry official docs (fetched 2026-07-08, Ronda 2): https://docs.cloud.google.com/artifact-registry/docs/repositories/remote-repo — confirma la sintaxis de `gcloud artifacts repositories create --mode=remote-repository --remote-docker-repo=<URL>` para un upstream custom (incluido GHCR), y que funciona sin credenciales para imágenes públicas.
