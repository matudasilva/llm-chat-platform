from __future__ import annotations

from pathlib import Path

import pytest

from app.scripts import guardrails_scan
from app.scripts.guardrails_scan import main, scan_file


def test_scan_file_flags_sensitive_local_paths(tmp_path: Path) -> None:
    target = tmp_path / "evidence.md"
    target.write_text("Trace:\n/home/alice/project/app/main.py:12: warning\n", encoding="utf-8")

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "local-path"
    assert findings[0].line == 2


def test_scan_file_ignores_placeholders_but_flags_real_secret(tmp_path: Path) -> None:
    target = tmp_path / "secrets.md"
    token = "sk-" + "1234567890ABCDEFGHIJKLMNOP"
    target.write_text(
        f"export OPENAI_API_KEY=\"***\"\nexport OPENAI_API_KEY=\"{token}\"\n",
        encoding="utf-8",
    )

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "secret-token"
    assert findings[0].line == 2


def test_scan_file_ignores_variable_references(tmp_path: Path) -> None:
    target = tmp_path / "provider_factory.py"
    target.write_text("api_key=cfg.openai_api_key\n", encoding="utf-8")

    findings = scan_file(target)

    assert findings == []


# --- `secret-assignment`: an unquoted call result is not an embedded secret ---
#
# The rule matched `token = _set_tenant("acme")` by capturing the *identifier*
# `_set_tenant` as the secret value. The only escape hatch was for unquoted
# values containing a dot (`cfg.openai_api_key`), which a plain call does not
# have. That produced eight findings across two tenant test files and turned
# every new-branch Guardrails run red on debt nobody had introduced.
#
# Relaxing a security rule is only safe if the other direction is pinned too,
# so these tests assert both what must stop firing and what must keep firing.


def test_call_results_are_not_flagged_as_secret_assignments(tmp_path: Path) -> None:
    """The exact shapes behind the eight real findings."""
    target = tmp_path / "test_tenant.py"
    target.write_text(
        'token = _set_tenant("acme")\n'
        'token = _make_bearer({"tenant_id": "beta-corp", "sub": "user1"})\n'
        "password = build_password()\n"
        "api_key = factory ()\n",  # whitespace before the call
        encoding="utf-8",
    )

    assert scan_file(target) == []


def test_quoted_literal_secrets_are_still_flagged(tmp_path: Path) -> None:
    """The escape must not extend to quoted values -- those are real literals."""
    target = tmp_path / "config.py"
    # Assembled rather than written inline, so this file does not itself trip
    # the rule it is testing -- the same reason the `sk-` literal above is
    # split in two.
    literal = "aB3dEf9" + "hIjKlMnOp"
    target.write_text(f'token = "{literal}"\n', encoding="utf-8")

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "secret-assignment"


def test_quoted_dotted_literals_are_still_flagged(tmp_path: Path) -> None:
    """The attribute-access escape must stay scoped to *unquoted* values.

    A quoted literal containing dots is a very common real secret shape -- a
    JWT is three dotted segments. Dropping the quote guard would exempt it
    along with `cfg.openai_api_key`, which is why the guard is not redundant
    with the call check below it.
    """
    target = tmp_path / "config.py"
    literal = "aB3dEf9" + ".hIjKlMnOp"
    target.write_text(f'token = "{literal}"\n', encoding="utf-8")

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "secret-assignment"


def test_unquoted_bare_identifiers_are_still_flagged(tmp_path: Path) -> None:
    """Pins the boundary of the relaxation: only *calls* are exempt, not every
    unquoted value. Widening the escape to every unquoted value would silently
    stop flagging a hardcoded bare value assigned to `password`."""
    target = tmp_path / "config.py"
    bare = "hunter2" + "hunter2"
    target.write_text(f"password = {bare}\n", encoding="utf-8")

    findings = scan_file(target)

    assert len(findings) == 1
    assert findings[0].rule == "secret-assignment"


def test_a_real_key_inside_a_call_is_still_caught(tmp_path: Path) -> None:
    """The call escape applies to `secret-assignment` only. A genuine key
    passed as a call argument must still be caught by `secret-token`."""
    target = tmp_path / "config.py"
    key = "sk-" + "1234567890ABCDEFGHIJKLMNOP"
    target.write_text(f'token = decrypt("{key}")\n', encoding="utf-8")

    findings = scan_file(target)

    assert [f.rule for f in findings] == ["secret-token"]


def test_the_two_real_tenant_test_files_are_clean(tmp_path: Path) -> None:
    """The decisive regression: the eight findings reported by CI are gone.

    Scans the shipped files, not a reconstruction of them, so a future edit
    that reintroduces the shape fails here.
    """
    repo_root = guardrails_scan.REPO_ROOT
    targets = [
        repo_root / "tests/api/test_chat_tenant.py",
        repo_root / "tests/http/middleware/test_tenant_middleware.py",
    ]

    for target in targets:
        assert target.is_file(), target
        assert scan_file(target) == [], target


def test_main_without_args_scans_default_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guardrails_scan, "default_scan_paths", lambda: [])

    assert main([]) == 0
