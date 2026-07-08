# ADR-005: PaaS Provider for Staging Deployment

**Date:** 2026-07-06
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

The provider comparison alone (columns) is close to a tie between App Runner and Cloud Run. The deciding factor is **which cloud already hosts an LLM provider this codebase talks to today**: AWS Bedrock is integrated and used in production code paths (`ProviderPort` implementation, `bedrock_provider.py`); Vertex AI is only a planned future addition (ORQ-21+), not yet implemented.

A same-cloud placement matters for the resources that require network/IAM proximity (compute ↔ managed Postgres/Redis: private VPC, IAM roles, security groups). It does **not** meaningfully matter for LLM provider access itself — both Bedrock and Vertex AI are consumed over public HTTPS APIs with bearer/IAM credentials, so a Cloud Run service could call Bedrock cross-cloud with an AWS access key just as an App Runner service could later call Vertex AI cross-cloud with a GCP service account key. Cross-cloud LLM calls add one extra credential to manage, not a networking redesign.

Fly.io is excluded: no credits available means real cost from day one for a project with no revenue, and it does not reduce integration work versus the two credit-backed options.

## Decision

We select **AWS App Runner** as the staging (and initial production-candidate) PaaS.

Rationale, in order of weight:

1. **Reduces cloud surface area today.** Bedrock is already integrated and is the primary non-stub provider exercised in this codebase. Running compute on AWS means one IAM identity, one billing account, and one credential set for both compute and the active LLM provider, instead of splitting operational surface across two clouds for no functional gain yet.
2. **Vertex AI does not require same-cloud placement.** When Vertex AI is integrated in ORQ-21+, adding it as a second `ProviderPort` implementation only requires a GCP service account key as a secret on whatever compute is already running — it does not require migrating the deploy target.
3. **AWS credits are available and unused elsewhere in this project**; using them for staging avoids introducing cost before the platform has real traffic.
4. **RDS/ElastiCache are mature, well-documented managed services** with straightforward `DATABASE_URL`/`REDIS_URL` connection strings, matching the existing settings-based configuration (`app/core/settings.py`) with no code changes required.
5. **App Runner deploys directly from a container registry image** (including public GHCR images), matching the CI pipeline design in this ORQ (`docker-publish.yml` → GHCR) without requiring an additional registry (e.g., ECR) for the first deploy.

## Consequences

### Positive

- Single cloud (AWS) for compute + managed data stores + active LLM provider (Bedrock): one IAM/billing surface for the initial deploy.
- Reuses AWS credits; staging cost stays near zero while idle (subject to App Runner's auto-pause behavior — see Negative).
- `docker-compose.prod.yml` (portable fallback, this ORQ) and `apprunner.yaml` (native config) are both produced, keeping a documented escape hatch to any other container host (Cloud Run, Fly.io, a VPS) if App Runner proves unsuitable later.
- No code changes required to `app/core/settings.py` — `DATABASE_URL`/`REDIS_URL`/`OPENAI_API_KEY`/`AWS_*` are already read from environment variables.

### Negative / Trade-offs

- App Runner's scale-to-zero is auto-pause based (idle detection + cold start on resume), not as instantaneous as Cloud Run's native scale-to-zero — first request after an idle period will be slower.
- AWS service configuration (App Runner service definition, IAM role for RDS/ElastiCache access) has a steeper one-time learning curve than Cloud Run's more uniform YAML, though this is a one-time cost paid in this ORQ.
- Choosing AWS now is a soft bet that Bedrock remains the primary provider through the staging period; if Vertex AI becomes primary sooner than ORQ-21+, this decision would need revisiting (documented as accepted risk, not blocking).
- Vendor lock-in is medium: App Runner's service configuration is AWS-specific, though the underlying container image remains portable (mitigated by keeping `docker-compose.prod.yml` as the portable fallback).

## Alternatives Considered

### Alternative A: GCP Cloud Run

Comparable managed-service maturity and cost profile to App Runner, with better native scale-to-zero and credits available. Rejected as the primary choice because it would split operational surface across two clouds (AWS for Bedrock's IAM/network context today, GCP for compute) with no current functional benefit — Vertex AI is not yet integrated, so there is nothing on GCP for the compute layer to be "close to" yet. Remains the natural target if Vertex AI becomes the primary LLM provider in ORQ-21+; not discarded permanently, revisit possible via a superseding ADR at that point.

### Alternative B: Fly.io

Lowest first-deploy friction and fully portable (standard containers, no proprietary service config). Rejected due to lack of available credits — real cost from day one on a project with no production traffic — and no offsetting integration benefit versus the two credit-backed cloud options.

## Evidence

- `app/core/providers/bedrock_provider.py` — existing Bedrock `ProviderPort` implementation, evidence of active AWS integration.
- `app/core/settings.py` — `DATABASE_URL` alias, `provider`/`fallback_provider` fields already environment-driven; no code change needed to point at RDS/ElastiCache.
- `.framework/orqs/ORQ-20/spec.md` — Environments section, staging/prod variable list (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`).
- Operator brief (2026-07-06): GCP credits active (Vertex AI, ORQ-21+ candidate) and AWS credits active (App Runner, Bedrock already integrated) — both confirmed available at ADR time.
