# Framework V3 Operational Context

## Adoption Baseline

- **Date:** 2026-11-12
- **Commit:** e63a8e5 (ORQ-41 paid campaign COMPLETE)
- **Product State:** V1.1 (stable, documented in `docs/v1_1_closure.md`)
- **Framework Scope:** Structural and governance (non-functional)
- **Framework Version:** AI Together Framework V3 3.7.0

---

## Functional Perimeter (Read-Only)

This Framework V2 adoption is **purely operational and structural**. It does NOT:

- Modify `/chat` contract or semantics
- Change provider implementations or abstractions
- Alter persistence flow or streaming boundaries
- Introduce new routing policies or observability events
- Affect runtime behavior in any way

All existing tests must pass with zero changes.

---

## What Framework V2 Adoption Brings

1. **Governance Structure**
   - Explicit constraints on architectural boundaries
   - Clear escalation paths for changes
   - Documentation-driven architecture (CLAUDE.md as guide)

2. **Operational Clarity**
   - Protected files and layers (explicit non-modification zones)
   - Scope discipline (minimal-diff, architecture-first)
   - Validation baseline (CI requirements, test coverage)

3. **Continuity**
   - V1.1 baselines preserved (AGENTS.md, LLD, evidence)
   - Zero product functional changes
   - Migration path from V1.1 to V2 clearly defined

---

## Invariants Preserved from V1.1

All invariants from `AGENTS.md` remain in force:

### Persistence
- `/chat` is the only write-path
- One transaction per request (4-step atomic pattern)
- Best-effort telemetry (failures do not break business)

### Provider Abstraction
- Provider-agnostic domain services
- ProviderPort is the sole contract
- No provider-specific logic in routes

### Streaming
- SSE contract enforced (token, done, error)
- Fallback allowed only before first token
- No fallback after partial stream emission

### Observability
- Structured JSON logging (HTTP + provider events)
- Request ID propagation (end-to-end)
- No secrets in logs

---

## Framework Governance Path

Project Context Source and governance sync targets are external references. Reading from a Project Context Source does not imply creating ORQs in that source. ORQ preparation and execution remain local/repo framework operations unless explicitly configured otherwise.

### Phase 1: Structural Adoption (This Task — Task-2)
- ✅ Create `CLAUDE.md` (codebase guide)
- ✅ Create `.framework/` directory structure
- ✅ Document operational constraints
- ✅ Preserve V1.1 baselines
- **No functional changes**

### Phase 2: Enhanced Governance (Future — Task-3+)
- Policy integration (if requested)
- Automated constraint validation (if requested)
- Process automation (if requested)
- **Still non-functional**

---

## Operational Rules Under Framework V2

1. **All changes must:**
   - Start with architectural clarity (propose before implementing)
   - Preserve invariants from AGENTS.md
   - Keep diffs minimal and reviewable
   - Pass CI baseline (tests/core + minimal API tests)
   - Remain documented (update CLAUDE.md if rules change)

2. **Changes that require escalation:**
   - Violations of invariants in AGENTS.md
   - Modifications to protected files or layers
   - Architectural redesigns
   - Functional changes outside explicit scope

3. **Documentation requirements:**
   - Repository artifacts in English
   - Architecture changes documented in LLD
   - New decision evidence in appendix
   - Operational context in CLAUDE.md

---

## Validation and Testing

**Baseline:** CI workflow from Day 32
```bash
python -m pytest -q tests/core tests/api/test_health_readyz.py tests/api/test_request_ids.py tests/api/test_request_size_limit.py tests/api/test_structured_logging.py
docker build -t llm-chat-platform:ci .
```

**Requirement:** All existing tests must pass (zero regression).

**Evidence:** See `docs/lld_apendix.md` for reproducible test runs and validation strategies.

---

## Artifact Policy

### Version-Controlled (Git)
- Source code (app/, tests/, scripts/)
- Configuration (Dockerfile, docker-compose.yml, alembic/)
- Documentation (docs/, README.md, AGENTS.md, CLAUDE.md)
- Framework structure (.framework/)
- Local settings reference (.claude/settings.local.json)

### Not Version-Controlled
- Local environment (.env, .env.dev)
- Local Puppeteer config (puppeteer-config.json)
- Generated artifacts (reports/, .pytest_cache/, .ipynb_checkpoints/, venv/)

### Immutable (Do Not Modify)
- Migration chain (alembic/versions/)
- V1.1 closure documentation (docs/v1_1_closure.md)
- Core invariants (AGENTS.md Core System Invariants section)

---

## Escalation Criteria

**Escalate to project lead if:**

- A change violates any invariant in `AGENTS.md`
- A change affects `/chat` contract, semantics, or behavior
- A change affects provider abstraction or ProviderPort contract
- A change affects persistence flow or transaction boundaries
- A change affects streaming semantics (fallback boundaries, SSE contract)
- A change breaks observability or request_id traceability
- A change requires architectural redesign
- A change falls outside the operational scope of Framework V2

---

## Next Steps

1. **For Task-2 completion:**
   - ✅ CLAUDE.md created
   - ✅ .framework/ structure initialized
   - ✅ Operational context documented
   - Validate that existing tests still pass

2. **For future operational use:**
   - Reference CLAUDE.md for codebase guidelines
   - Consult .framework/project-config.yml for governance constraints
   - Check AGENTS.md before proposing changes
   - Escalate if uncertain whether a change violates invariants

---

**Framework V2 adoption is structural and non-functional. All product behavior remains unchanged.**

Last updated: 2026-04-27
