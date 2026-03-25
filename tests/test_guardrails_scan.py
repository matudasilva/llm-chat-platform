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


def test_main_without_args_scans_default_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guardrails_scan, "default_scan_paths", lambda: [])

    assert main([]) == 0
