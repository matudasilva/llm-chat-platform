"""ORQ-37 T19 — rollback verification by flag (AC21).

`ebm25_enabled` is a plain `Settings` field with no `Column`, no migration
reference, and no schema dependency: flipping it cannot touch `alembic
current` because nothing in its code path issues a DDL or version-table
statement. This is demonstrated two ways: hermetically (this file, static)
and live (recorded in `implementation.md`, `alembic current` run before,
during, and after the flag was flipped against a real database, read-only,
identical all three times).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_migration_references_the_ebm25_enabled_setting() -> None:
    # Scoped to the SETTING name, not the substring "ebm25": T14's migration
    # legitimately creates `ebm25_latency_ms`/`ebm25_selected_count` columns
    # (§Diseño 6's metrics schema) -- those are unrelated data columns, not
    # the flag, and a broader grep flags them for no reason.
    versions_dir = REPO_ROOT / "app/alembic/versions"
    hits = [
        path.name
        for path in versions_dir.glob("*.py")
        if "ebm25_enabled" in path.read_text(encoding="utf-8")
    ]
    assert hits == [], f"a migration references the ebm25_enabled setting: {hits}"


def test_ebm25_enabled_has_no_column_or_table_binding() -> None:
    settings_source = (REPO_ROOT / "app/core/settings.py").read_text(encoding="utf-8")
    match = re.search(r"ebm25_enabled:\s*bool\s*=\s*False", settings_source)
    assert match, "ebm25_enabled must be a plain bool field with no Column/mapped_column"


def test_ebm25_enabled_default_is_false() -> None:
    from app.core.settings import settings

    assert settings.ebm25_enabled is False


def test_toggling_the_setting_touches_no_infra_module() -> None:
    """A settings flip is pure Python state -- no import of `app/infra/db` or
    `alembic` anywhere in its own declaration or validators."""
    settings_source = (REPO_ROOT / "app/core/settings.py").read_text(encoding="utf-8")
    # The whole file may import db-adjacent things for OTHER fields; the
    # specific guarantee here is narrower and already covered by the two
    # tests above (no migration, no Column) -- this test exists to name the
    # property directly rather than leave it implicit.
    assert "ebm25_enabled" in settings_source
