# ORQ-12 Criterios de Aceptación

## Fase 1: Design-only (Design Review)

### D1.1: Especificación clara

**Criterio:** spec.md documentó la decisión MCP, arquitectura, boundaries y alcance sin ambigüedad.

**Verificación:**
- [ ] spec.md define por qué se usa MCP (reuse prior art, token isolation)
- [ ] spec.md define por qué NO es un generic tools runtime (hardcoded allowlist)
- [ ] spec.md lista explícitamente IN SCOPE y OUT OF SCOPE
- [ ] Riesgos están identificados y mitigados

**Observación:** Design review debe confirmar que spec.md es claro.

### D1.2: Arquitectura de boundary

**Criterio:** Diagrama y descripción de cómo llm-chat-platform interactúa con notion-mcp-read está documentado.

**Verificación:**
- [ ] ControlledNotionReadClient está documentado como wrapper acotado
- [ ] MCP server es externo (subprocess/network), no embebido
- [ ] Tool allowlist es hardcoded (notion_get_page, not "*")
- [ ] Respons

e sanitization está documentada

**Observación:** Design review debe confirmar que el boundary es claro y defensible.

### D1.3: Alcance acotado

**Criterio:** ORQ-12 está claramente limitada a `GET /notion-read/page` (MVP).

**Verificación:**
- [ ] `GET /notion-read/database` está marcado como Phase 2 candidate
- [ ] `notion_query_database` está marcado como future
- [ ] No hay mención de RAG, embeddings, agent orchestration
- [ ] spec.md confirma `/notion-read` separado de `/chat`

**Observación:** Design review debe confirmar que alcance es minimal.

---

## Fase 2: MVP Implementation

### I2.1: Settings configurados

**Criterio:** `app/core/settings.py` tiene NOTION_* config fields con validators.

**Verificación:**
```bash
grep -A 2 "notion_read_enabled\|notion_mcp_enabled\|notion_mcp_server_command" app/core/settings.py
```

**Expected (Metadata-only MVP):** 
- `notion_read_enabled: bool = False`
- `notion_mcp_enabled: bool = False`
- `notion_mcp_server_command: str = "notion-mcp-read"`
- `notion_mcp_server_args: list[str] = []`
- `notion_mcp_server_cwd: str | None = None`
- `notion_mcp_timeout_s: float = 10.0`
- `notion_allowed_page_ids: list[str] = []` (CSV parsed, dashes normalized)
- **NOT in MVP:** ~~notion_mcp_allowed_tools~~ (hardcoded in code)
- **NOT in MVP:** ~~notion_allowed_database_ids~~ (deferred to Phase 2)
- Validators para timeout (> 0), command (non-empty), page_ids (CSV parser)

**Observación:** Tool allowlist es hardcoded (notion_get_page), no configurable.

### I2.2: ControlledNotionReadClient implementado

**Criterio:** `app/services/notion_read_client.py` existe con interfaz mínima.

**Verificación:**
```bash
grep -n "class ControlledNotionReadClient\|async def get_page\|async def health_check" app/services/notion_read_client.py
```

**Expected (MVP):**
- Clase existe
- Métodos: `get_page()`, `health_check()`, `start()`, `stop()`
- Subprocess lifecycle management (start, stop via app.lifespan())
- Error taxonomy by layer: NotionMCPTimeoutError, NotionMCPProtocolError, NotionMCPExecutionError
- Timeout enforcement via asyncio.wait_for()
- **NOT in MVP:** ~~query_database()~~ (deferred to Phase 2)

**Observación:** Tests deben usar mocks (no llamadas reales a MCP).

### I2.3: NotionReadService implementado

**Criterio:** `app/services/notion_read.py` existe con orchestración.

**Verificación:**
```bash
grep -n "class NotionReadService\|def.*allow\|def.*normaliz" app/services/notion_read.py
```

**Expected (MVP):**
- Clase existe
- Allowlist enforcement (page_ids only)
- ID normalization (remove dashes for comparison)
- Response sanitization (metadata-only: page_id, title, url, created_time, last_edited_time)
- **NOT in MVP:** ~~database_ids~~ (deferred to Phase 2)
- **NOT in MVP:** ~~limit enforcement (max_text_chars)~~ (no text in MVP)

**Observación:** Lógica de allowlist debe estar clara y testeable.

### I2.4: HTTP Routes implementadas

**Criterio:** `GET /notion-read/page?page_id=<id>` endpoint existe y es registrado.

**Verificación:**
```bash
curl http://localhost:8000/notion-read/page?page_id=test 2>/dev/null | jq .
```

**Expected responses (Metadata-only MVP):**
- 200 with `{page_id, title, url, created_time, last_edited_time}` (metadata-only)
- 422 with detail (missing/invalid page_id - FastAPI auto-validation)
- 403 with detail (page_id not in allowlist)
- 502 with detail (MCP protocol/Notion API error)
- 504 with detail (timeout)
- 503 with detail (MCP unavailable - graceful degradation)
- **NOT in MVP:** ~~text, blocks_read, truncated~~ (metadata-only, no content)

**Observación:** Router registration debe estar en `api/router.py`.

### I2.5: Tests existentes sin regresión

**Criterio:** Tests existentes (core, API baseline) siguen pasando.

**Verificación:**
```bash
python -m pytest -q tests/core tests/api/test_health_readyz.py tests/api/test_request_ids.py -v
```

**Expected:** Todos pasan (zero regression).

**Observación:** CI baseline debe pasar.

---

## Fase 3: Testing & Closure

### T3.1: Core tests para ControlledNotionReadClient

**Criterio:** `tests/core/test_notion_read_client.py` tiene cobertura de happy path + boundary.

**Verification:**
```bash
python -m pytest tests/core/test_notion_read_client.py -v
```

**Expected:**
- Health check works (mocked MCP response)
- get_page() calls MCP with correct tool + params
- Timeout handling works
- Error handling works (MCP errors → NotionReadError)

**Observación:** Todos los tests deben usar mocks (pytest fixtures for MCP).

### T3.2: Core tests para NotionReadService

**Criterio:** `tests/core/test_notion_read_service.py` tiene cobertura de allowlist + normalization.

**Verification:**
```bash
python -m pytest tests/core/test_notion_read_service.py -v
```

**Expected (Metadata-only MVP):**
- Allowlist enforcement: denied page_id → NotionReadBlockedError (403)
- **NOT in MVP:** ~~denied database_id~~ (deferred to Phase 2)
- ID normalization: "abc-123" == "abc123" in allowlist
- **NOT in MVP:** ~~truncation~~ (no text field, metadata-only)
- Response sanitization: only page_id, title, url, created_time, last_edited_time

**Observación:** Tests deben cubrir boundaries y error cases.

### T3.3: API tests para endpoint

**Criterio:** `tests/api/test_notion_read_endpoint.py` tiene route validation.

**Verification:**
```bash
python -m pytest tests/api/test_notion_read_endpoint.py -v
```

**Expected (Metadata-only MVP, status codes per FastAPI conventions):**
- GET /notion-read/page is registered
- Missing or empty page_id → 422 (FastAPI auto-validation, NOT 400)
- Denied page_id (not in allowlist) → 403
- Valid page_id (mocked) → 200 with NotionPageOut (5 metadata fields)
- MCP protocol/upstream error (mocked) → 502
- MCP timeout (mocked) → 504
- MCP unavailable (no service in app.state) → 503

**Observación:** Todos mocks, sin llamadas reales.

### T3.4: Integración verificada

**Criterio:** `/notion-read` está registrado en router sin conflictos.

**Verification:**
```bash
curl http://localhost:8000/openapi.json 2>/dev/null | jq '.paths | keys | .[]' | grep notion-read
```

**Expected:** `/notion-read/page` appears in OpenAPI.

**Observación:** `/chat` debe permanecer sin cambios.

### T3.5: Documentación completada

**Criterio:** README.md, `.env.example`, docstrings actualizado.

**Verification:**
```bash
grep -i "notion" README.md .env.example
grep -n "Controlled Notion" README.md
```

**Expected:**
- README.md tiene sección "Controlled Notion Read via MCP"
- `.env.example` tiene NOTION_* template
- Docstrings en services explican allowlist, normalization

**Observación:** Debe documentar que esto no es RAG ni agent tools.

---

## Fase 4: ORQ Closure

### C4.1: Evidence reproducible documentada

**Criterio:** `execution.md` documenta el baseline de evidencia reproducible.

**Verification:**
- [ ] execution.md lista commands para reproducir tests
- [ ] execution.md lista expected output
- [ ] execution.md documenta cualquier setup manual (workspace, token)

**Observación:** Evidence debe ser verificable por terceros.

### C4.2: Learnings capturados

**Criterio:** `closure.md` documenta learnings de implementación.

**Verification:**
- [ ] closure.md lista qué funcionó bien
- [ ] closure.md lista qué fue difícil
- [ ] closure.md sugiere mejoras para futuras ORQs (Phase 2 candidates)

**Observación:** Learnings pueden ser sincronizados a Framework Learning.

### C4.3: Estado de cierre explícito

**Criterio:** `closure.md` declara el estado de la ORQ (Closed, Deferred, Escalated).

**Verification:**
- [ ] closure.md documenta "Closed ORQ"
- [ ] closure.md lista qué fue completado
- [ ] closure.md lista qué fue postergado (Phase 2 candidates)
- [ ] closure.md sugiere próximo paso

**Observación:** Dejar claro qué fue done vs. future.

---

## Criterios Transversales

### Invariantes Preservados

- [ ] `/chat` no fue modificado (write-path intacto)
- [ ] ProviderPort no fue modificado
- [ ] Providers no fueron modificados
- [ ] Persistencia no fue modificada (no new DB schema)
- [ ] Streaming no fue modificado
- [ ] Redis no fue modificado
- [ ] Routing runtime no fue modificado

**Verificación:**
```bash
git diff HEAD~10 --name-only | grep -E "chat\.py|provider|persistence|streaming|redis|routing"
```

**Expected:** Ninguno de estos archivos debe estar modificado.

### Tests Pasan

**Criterio:** CI baseline pasa sin fallos.

**Verification:**
```bash
python -m pytest -q tests/core tests/api/test_health_readyz.py tests/api/test_request_ids.py tests/api/test_request_size_limit.py tests/api/test_structured_logging.py
docker build -t llm-chat-platform:ci .
```

**Expected:** Todos pasan, exit code 0.

### Documentación Actualizada

- [ ] CLAUDE.md refleja cualquier cambio de reglas (unlikely)
- [ ] AGENTS.md no fue modificado (invariantes intactos)
- [ ] README.md tiene nueva sección Notion Read
- [ ] ORQ-12 docs completos

**Observación:** Documentación debe estar alineada con implementación.

---

## Matriz de Aceptación Final

| Criterio | Phase | Status | Owner | Evidence |
|----------|-------|--------|-------|----------|
| Spec claro sin ambigüedad | 1 | ⏳ | orchestrator | spec.md |
| Design review realizado | 1 | ⏳ | design-reviewer | review.md |
| Settings + validators | 2 | ⏳ | executor | grep output |
| ControlledNotionReadClient | 2 | ⏳ | executor | class definition |
| NotionReadService | 2 | ⏳ | executor | class definition |
| GET /notion-read/page | 2 | ⏳ | executor | curl test |
| Tests existentes sin regresión | 2 | ⏳ | executor | pytest output |
| Core tests | 3 | ⏳ | executor | pytest output |
| API tests | 3 | ⏳ | executor | pytest output |
| Documentación | 3 | ⏳ | executor | grep output |
| Invariantes preservados | 3 | ⏳ | execution-reviewer | git diff |
| CI baseline pasa | 3 | ⏳ | execution-reviewer | pytest output |
| Evidence reproducible | 4 | ⏳ | closer | execution.md |
| Learnings capturados | 4 | ⏳ | closer | closure.md |
| ORQ closed | 4 | ⏳ | closer | closure.md |
