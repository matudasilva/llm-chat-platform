# LLD Appendix — LLM Chat Platform

**Companion document to:** `lld_llm_chat_platform_live_doc.md`

**Scope:** Deep technical appendices, debugging playbooks and execution-level details

**Validity:** Up to Day 9

---

## Appendix A — SQL schema & constraints (expected state)

> This section documents the **effective schema semantics** as enforced by Alembic migrations and runtime behavior.

### A.1 `conversations`

```sql
CREATE TABLE conversations (
  id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  title TEXT NULL,
  metadata JSONB NULL
);
```

**Semantics**

* Acts as aggregation root for messages
* Created lazily on first `/chat` request
* No hard deletes assumed

---

### A.2 `messages`

```sql
CREATE TABLE messages (
  id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conversation_created
  ON messages(conversation_id, created_at);
```

**Semantics**

* Ordering guaranteed by `(conversation_id, created_at)`
* FK enforces existence of conversation
* `system` role reserved for orchestration

---

### A.3 `usage_events`

```sql
CREATE TABLE usage_events (
  id UUID PRIMARY KEY,
  provider TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  request_id UUID NULL,
  conversation_id UUID NULL REFERENCES conversations(id),
  message_id UUID NULL REFERENCES messages(id),
  input_tokens INTEGER NULL,
  output_tokens INTEGER NULL,
  total_tokens INTEGER NULL,
  latency_ms INTEGER NULL,
  status TEXT NOT NULL,
  error_message TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_usage_events_request_id ON usage_events(request_id);
CREATE INDEX idx_usage_events_conversation_ts ON usage_events(conversation_id, created_at);
CREATE INDEX idx_usage_events_message_id ON usage_events(message_id);
```

**Critical design note**

* `conversation_id` and `message_id` are **nullable by design**
* Error telemetry must never depend on business data success

---

## Appendix B — `/chat` sequence diagram (textual)

### B.1 Happy path

```
Client
  └─ POST /chat
       └─ generate request_id
       └─ start timer
       └─ BEGIN TRANSACTION
            └─ create Conversation (if needed)
            └─ flush → conversation_id
            └─ insert Message(role=user)
            └─ flush → user_message_id
            └─ execute model (stub)
            └─ insert Message(role=assistant)
            └─ flush → assistant_message_id
            └─ insert UsageEvent (with FKs)
       └─ COMMIT
       └─ return ChatResponse
```

Guarantees:

* Atomic write-path
* No partial persistence
* Telemetry consistent with business data

---

### B.2 Error path (unexpected failure)

```
Client
  └─ POST /chat
       └─ generate request_id
       └─ BEGIN TRANSACTION
            └─ failure occurs
       └─ ROLLBACK
       └─ BEGIN (best-effort)
            └─ insert UsageEvent(status=error, no FKs)
       └─ COMMIT
       └─ re-raise exception
```

Guarantees:

* Database consistency preserved
* Error observability retained

---

## Appendix C — Router & import map

### C.1 Canonical router layout

```
app/main.py
  ├─ include_router(ops_router, prefix="/ops")
  └─ include_router(chat_router, prefix="/chat")

app/api/routes/chat.py
  └─ router = APIRouter(tags=["chat"])
```

**Invariant**

* Only one authoritative chat router
* No shadow routers or duplicate includes

---

### C.2 Known anti-patterns (resolved)

* Importing non-existent `app.api.chat`
* Multiple routers defining `/chat`
* Dynamic router discovery

---

## Appendix D — Debug playbook

### D.1 `/chat` missing from OpenAPI

**Symptoms**

* `/chat` not present in `/openapi.json`

**Checks**

```bash
curl -s http://localhost:8001/openapi.json | jq '.paths | keys'
```

**Likely causes**

* Router not included in `main.py`
* Import-time crash in container

---

### D.2 Container exits immediately

**Symptoms**

* `docker compose ps` shows API exited

**Checks**

```bash
docker compose logs api
```

**Common causes**

* Indentation errors
* Invalid imports
* Missing dependencies

---

### D.3 FK violation on `usage_events`

**Symptoms**

```
ForeignKeyViolationError: Key (conversation_id) not present
```

**Cause**

* Logging usage events with FKs after rollback

**Resolution**

* Success telemetry inside transaction
* Error telemetry without FKs

---

### D.4 Verifying DB state

```bash
docker compose exec -T postgres psql -U llmchat -d llmchat -c \
"select role, count(*) from messages group by role;"
```

```bash
docker compose exec -T postgres psql -U llmchat -d llmchat -c \
"select provider, status, conversation_id, message_id from usage_events order by created_at desc limit 5;"
```

---

## Appendix E — Operational sanity checklist

* [ ] Alembic current == heads
* [ ] API container running
* [ ] `/health` responds
* [ ] `/chat` persists messages
* [ ] `usage_events` populated

---

**End of appendix — complements the live LLD document**
