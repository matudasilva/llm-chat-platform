# LLM Chat Platform

## Low Level Design (LLD)

**Document type:** Living Low-Level Design + Architectural Decision Record (ADR) log
**Scope:** Backend (FastAPI)
**Audience:** Arquitectos backend, maintainers, operadores
**Status:** Baseline estable — Día 7

---

## 1. Visión general del sistema

LLM Chat Platform es un backend diseñado para soportar conversaciones basadas en modelos de lenguaje, priorizando **orden arquitectónico**, **trazabilidad operativa** y **evolución segura** por sobre la entrega rápida de funcionalidades.

El sistema se construye sobre una base explícita:

* arranque determinístico de la API
* separación estricta entre runtime y operaciones
* persistencia reproducible
* disciplina documental y de migraciones

Este documento define **cómo funciona el sistema por dentro**, no qué features ofrece.

---

## 2. Principios arquitectónicos

### 2.1 Separación runtime vs operaciones

El runtime de la API **no ejecuta lógica operacional**:

* no valida dependencias externas
* no corre migraciones
* no intenta “arreglar” el entorno

Las operaciones (migraciones, validaciones profundas, readiness real) son **explícitas y manuales**.

---

### 2.2 Arranque determinístico

La API debe poder iniciar siempre, independientemente del estado de:

* PostgreSQL
* Redis

Un fallo transitorio de dependencias **no debe impedir** que el proceso HTTP levante.

---

### 2.3 Una sola fuente de verdad

* Toda configuración proviene de `core.settings`
* `settings.database_url` es la **única** fuente válida del DB URL
* No se duplican valores en Alembic, Docker ni código

---

### 2.4 Persistencia reproducible

* El estado del esquema se define por **migraciones versionadas**
* La base de datos nunca es la fuente de verdad
* El repositorio sí

---

### 2.5 Diseño incremental

No se anticipan capas ni abstracciones sin necesidad real y estable.

---

## 3. Arquitectura lógica

### Componentes

1. **API (FastAPI)**

   * Boundary HTTP
   * Orquestación futura de conversaciones y LLMs
   * Sin lógica de bootstrap infraestructural

2. **PostgreSQL**

   * Persistencia estructurada
   * Esquema gestionado exclusivamente por Alembic

3. **Redis**

   * Preparado para caching, rate limiting y estado efímero
   * No utilizado activamente en el baseline

---

## 4. Estructura del repositorio

```
app/
  main.py

  api/
    ops.py

  core/
    settings.py

  infra/
    db.py
    db/
      base.py
      session.py
    redis_client.py

  models/
    conversation.py
    message.py

  alembic/
    env.py
    versions/

  alembic.ini

README.md
LLD.md
.env.example
Dockerfile
docker-compose.yml
```

### Reglas de capas

* `core/` no depende de `infra/`
* `infra/` puede depender de `core.settings`
* `api/` no ejecuta lógica infraestructural
* `models/` define dominio, no comportamiento

---

## 5. Configuración

### 5.1 Estrategia

* Variables de entorno → `core.settings`
* Prohibido:

  * hardcodear valores
  * duplicar URLs
  * interpolaciones frágiles

### 5.2 Database URL

Formato requerido:

```
postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
```

En Docker Compose:

* `HOST` debe ser el nombre del servicio (`postgres`)

---

## 6. Health y readiness

### 6.1 `/health`

* Endpoint **process-level**
* Valida únicamente que la API responde

### 6.2 Readiness de dependencias

* PostgreSQL → `pg_isready`
* Redis → `redis-cli PING`

Gestionado exclusivamente por Docker healthchecks.

---

## 7. Acceso a datos (SQLAlchemy 2.0 async)

### Componentes

* `infra/db/base.py` → `DeclarativeBase`
* `infra/db/session.py` → engine, session, `get_db()`
* `infra/db.py` → shim de compatibilidad

### Reglas

* `expire_on_commit=False`
* Sin checks obligatorios en startup

---

## 8. Migraciones (Alembic)

### Naturaleza

* Operacionales
* Nunca automáticas
* Nunca ejecutadas por la API

### Ejecución canónica

```
docker compose exec -w /app/app api alembic current
docker compose exec -w /app/app api alembic upgrade head
docker compose exec -w /app/app api alembic revision -m "message"
docker compose exec -w /app/app api alembic downgrade -1
```

### Configuración

* DB URL desde `settings.database_url`
* Migraciones async
* `target_metadata = Base.metadata`

---

## 9. Modelos de dominio

### Conversation

**Tabla:** `conversations`

* `id` (UUID, PK)
* `created_at` (timestamptz)
* `updated_at` (timestamptz)
* `title` (nullable)
* `metadata` (JSONB, nullable)

### Message

**Tabla:** `messages`

* `id` (UUID, PK)
* `conversation_id` (FK, ON DELETE CASCADE)
* `role` (`user | assistant | system`)
* `content`
* `created_at`

**Índice:** `(conversation_id, created_at)`

### Contrato semántico

* `user` → input humano
* `assistant` → output del modelo
* `system` → contexto/control

---

## 10. Invariantes operacionales

### Migraciones

* Todo archivo en `app/alembic/versions/` debe versionarse

### Docker build

La imagen `api` usa:

```
COPY app /app/app
```

**Regla:** nunca rebuild sin commit de migraciones.

---

## 11. ADRs

### ADR-001 — No checks de DB/Redis en startup

**Decisión:** la API no valida dependencias al iniciar.
**Impacto:** arranque determinístico.

---

### ADR-002 — `/health` process-level

**Decisión:** `/health` no valida dependencias externas.

---

### ADR-003 — Migraciones explícitas

**Decisión:** Alembic nunca corre automáticamente.

---

### ADR-004 — Fuente única de configuración

**Decisión:** `settings.database_url` como única fuente.

---

### ADR-005 — Modelo mínimo Conversation/Message

**Decisión:** persistencia mínima con contrato semántico explícito.

---

### ADR-006 — Migraciones versionadas

**Decisión:** toda revisión Alembic debe commitearse.

---

## 12. Reglas de estilo

* LLD ≠ README
* Documento normativo
* Sin features
* Cambios arquitectónicos → nuevo ADR

---

**Fin del LLD — Baseline Día 7**
