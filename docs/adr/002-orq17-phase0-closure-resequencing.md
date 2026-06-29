# ADR-002: ORQ-17 Phase 0 Closure — Technical Debt Resolution and ORQ Resequencing

**Date:** 2026-06-29  
**Status:** Accepted  
**ORQ reference:** ORQ-17

---

## Context

At the start of the Phase 0 closure sprint, a technical audit of the repository identified three technical debt findings (F1–F3) inherited from V1.1:

- **F1:** `tree.md` did not exist at the repository root (referenced in AGENTS.md as an orientation artifact).
- **F2:** `app/scripts/run_stub_chat.py` had a bare import (`from core.providers.stub_provider`) instead of the fully-qualified path (`from app.core.providers.stub_provider`), causing `ModuleNotFoundError` when running scripts from the repo root. The same issue was found in `export_usage_events.py` and `run_stub_determinism.py`. No CI check detected this class of regression.
- **F3:** `tests/test_cost_report_pipeline.py` had a hardcoded `pytest.skip` with the message "script not present". The script `run_cost_report.py` did exist at `app/scripts/` but the test's path resolver did not include that path as a candidate, so the test never ran.

Additionally, the number ORQ-17 was historically reserved for "RAG Baseline". A deliberate decision was made to resequence it to prioritize Phase 0 closure.

---

## Decision

### ORQ-17 Resequencing

We reassigned ORQ-17 to Phase 0 closure (V1.1 technical debt + stability tag) and moved RAG Baseline to ORQ-18. Phase 0 must be closed before introducing new features to preserve the integrity of the stability baseline.

### F1 — Regenerate tree.md

We generate `tree.md` at the repo root using `tree -I '__pycache__|*.pyc|.git'`. AGENTS.md is not modified because line 18 already states explicitly that `tree.md` is not treated as an authoritative source of truth.

### F2 — Fix imports and add CI smoke check

We fix the bare imports across all affected scripts in `app/scripts/` and add a smoke check step to `.github/workflows/ci.yml`. The step performs an AST scan over all `app/scripts/*.py` files, failing if it detects any import with a bare `core.` prefix (both `from core.*` and `import core.*` forms). This prevents the regression in the future without requiring actual script execution in CI.

### F3 — Rehabilitate the test (Option A)

We rehabilitate `tests/test_cost_report_pipeline.py` instead of deleting it. The script `run_cost_report.py` exists and the 4 tests are valid. The fix is to add the missing path candidate (`{repo_root}/app/scripts/run_cost_report.py`) as candidate 2 in `_resolve_script_path()` and remove the `pytest.skip`. The test is added to the CI baseline.

---

## Consequences

### Positive

- The repository is in a clean and auditable state as Phase 0 closed.
- The CI smoke check prevents future regressions in script import paths.
- All 4 cost report pipeline tests are active and running in CI.
- The `v1.1-stable` tag formally marks the stability baseline.
- The ORQ-17→Phase0 / ORQ-18→RAG resequencing is documented and traceable.

### Negative / Trade-offs

- The ORQ-17 number is consumed by a maintenance ORQ rather than a feature. This is intentional and deliberate.
- The AST smoke check only detects static bare imports, not dynamic or conditional imports. Accepted: the failure pattern that occurred (static bare import) is fully covered.

---

## Alternatives Considered

### Alternative A (F3): Delete test_cost_report_pipeline.py

Discard the test file because the skip had it effectively dead. Rejected because the script exists, the tests are valid, and removing them would lose coverage with no benefit.

### Alternative B (ORQ-17): Keep the reservation for RAG Baseline

Do not resequence and open a new number for Phase 0 closure. Rejected because the resequencing has a lower documentation cost than the debt of keeping the repo in a dirty state before advancing with new features.

---

## Evidence

- Findings F1–F3: technical audit pre-ORQ-17 (2026-06-29)
- Broken scripts: `app/scripts/run_stub_chat.py`, `app/scripts/export_usage_events.py`, `app/scripts/run_stub_determinism.py` (bare `core.*` imports)
- Existing but unreachable script: `app/scripts/run_cost_report.py`
- Framework version confirmed: `.framework/framework-version` = `v2.0.3`
- Stability tag: `v1.1-stable`
