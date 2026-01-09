# Low Level Design (LLD)

## Project: LLM Chat Platform

---

## 1. Document objective

This document describes the **Low Level Design (LLD)** of the *LLM Chat Platform* project, covering the technical decisions, repository structure, and service behavior implemented during the initial development phases.

The LLD serves as a technical reference for:

* Project evolution
* Architectural review
* Technical interviews / portfolio presentation

This is a **living document**, updated as the project evolves.

---

## 2. Current scope

### Included

* Git repository initialization
* Base project structure
* Minimal API service built with FastAPI
* Environment-based configuration
* Structured logging to stdout
* Process-level health endpoint
* Containerization with Docker Compose
* Base infrastructure services:

  * PostgreSQL
  * Redis

### Not included yet

* Model-level persistence (tables / migrations)
* Alembic migrations
* Authentication / authorization
* LLM provider integration
* Prompt/version management
* Observability (metrics, traces)

---

## 3. Repository and version control

### 3.1 Repository

* Name: `llm-chat-platform`
* Hosting: GitHub
* Default branch: `main`

### 3.2 Commit conventions

The project follows a convention compatible with **Conventional Commits**:

* `chore:` structural or maintenance tasks
* `feat:` new functionality
* `docs:` documentation changes

Example:

```
feat(api): init fastapi app with health endpoint and env config
```

---

## 4. Project structure

```text
llm-chat-platform/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── ops.py
│   └── requirements.txt
├── docs/
│   └── lld_llm_chat_platform.md
├── infra/
├── scripts/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
└── README.md
```

### 4.1 Directory responsibilities

| Path     | Responsibility                            |
| -------- | ----------------------------------------- |
| app/     | API code and application logic            |
| docs/    | Technical and architectural documentation |
| infra/   | Infrastructure as Code (future)           |
| scripts/ | Operational / automation scripts          |

---

## 5. API service

### 5.1 Framework

* **FastAPI**
* ASGI server: **Uvicorn**

**Rationale**

* High performance
* Strong typing
* Native async support
* De facto standard for modern ML/AI-oriented APIs

---

## 6. Environment-based configuration

The application loads configuration from environment variables to ensure portability across local, containerized, and future cloud environments.

### 6.1 Defined variables

| Variable  | Description           | Default     |
| --------- | --------------------- | ----------- |
| APP_ENV   | Execution environment | development |
| LOG_LEVEL | Logging level         | INFO        |

Database and cache configuration is provided via environment variables and composed internally by the application.

### 6.2 Resolution strategy

* Loaded at startup
* Defaults applied when missing
* Empty values normalized
* `.env.example` documents the full configuration contract

---

## 7. Logging

### 7.1 Strategy

* Logging to **stdout**
* Container- and cloud-friendly
* Single, consistent formatter
* Compatible with Docker and orchestration platforms

### 7.2 Logged components

* Root logger
* Uvicorn core
* Uvicorn access logs
* Application lifecycle events

Example:

```
2026-01-09T01:42:49+0000 INFO app starting application
```

---

## 8. Health endpoints

### 8.1 Process-level health endpoint

**Endpoint**

```
GET /health
```

**Response**

```json
{
  "status": "ok",
  "app_env": "development"
}
```

**Purpose**

* Process liveness verification
* Basis for container and orchestration liveness probes
* Does not perform dependency checks

---

## 9. Local execution

### 9.1 Virtual environment

* Local Python virtual environment (`.venv`)

### 9.2 Execution

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 9.3 Testing

```bash
curl http://127.0.0.1:8000/health
```

---

## 10. Current state summary

* ✔ Minimal API operational
* ✔ Environment-based configuration
* ✔ Structured logging
* ✔ Process-level health endpoint
* ✔ Solid foundation for persistence and LLM integration

---

## 11. Day 3 – Containerization and base services

### 11.1 Objective

Containerize the API and provision base infrastructure services while preserving environment-based configuration and coexistence with other local stacks.

### 11.2 Added artifacts

* `Dockerfile` (API)
* `docker-compose.yml` (API + PostgreSQL + Redis)
* `.dockerignore`
* Dedicated Docker network (`llmnet`)

### 11.3 Services

| Service  | Image / Build      | Port (host → container) | Purpose             |
| -------- | ------------------ | ----------------------- | ------------------- |
| api      | build (Dockerfile) | 8001 → 8000             | FastAPI (Uvicorn)   |
| postgres | postgres:16-alpine | internal → 5432         | Relational database |
| redis    | redis:7-alpine     | 6380 → 6379             | Cache / future use  |

### 11.4 Networking

* Docker network: `llmnet`
* Internal service communication via service names:

  * `postgres`
  * `redis`

---

## 12. Dependency management (Python)

The project explicitly separates:

* `app/requirements.txt`: direct runtime dependencies
* `requirements.lock` (optional): fully frozen dependency set

**Rationale**

* Keep runtime dependencies readable
* Allow strict reproducibility when required (CI / prod)

---

## 13. Update – Day 4 (Foundation & stability)

### Scope completed

* FastAPI application containerized and running under Docker Compose
* PostgreSQL and Redis services integrated as core infrastructure
* Centralized environment-based configuration
* Structured logging enabled at application startup
* Process-level health endpoint exposed (`GET /health`)

### Design decision: health checks

At this stage, the platform exposes **only a process-level health endpoint**.

Dependency-level health checks (database and cache connectivity) are **intentionally deferred** to avoid coupling application startup stability to transient infrastructure conditions.

---

## 14. Update – Day 5 (Compose hardening & deferred dependency checks)

### Scope completed

* Docker Compose refined to decouple API startup from dependency readiness:

  * API depends on Postgres and Redis using `condition: service_started`
* Infrastructure-level healthchecks added and validated:

  * PostgreSQL: `pg_isready`
  * Redis: `redis-cli PING`
* Application runtime behavior clarified:

  * No DB or Redis checks executed during FastAPI startup
  * `GET /health` remains process-level only

### Design decision: defer runtime dependency checks

Dependency checks remain intentionally **out of the application runtime path** at this stage.

A dedicated dependency endpoint (e.g. `GET /health/deps`) will be introduced once persistence and migration tooling are in place.

### Current status summary

The platform now provides:

* Stable containerized execution
* Docker-level visibility into dependency health
* Process-level liveness endpoint
* Clean and explicit foundation for:

  * SQLAlchemy integration
  * Alembic migrations
  * Persistence layer design

---

## 15. Planned next steps

### Day 6

* Initialize Alembic
* Configure migration environment
* First reproducible migration
* Prepare base ORM models

### Day 7+

* Introduce persistence models (Conversation, Message, UsageEvent)
* Add dependency health endpoint (`GET /health/deps`)
* Expand observability (metrics / traces)
* Begin LLM provider integration

---

**End of document**
