from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def _resolve_script_path() -> Path:
    # Candidate 1: repo root = tests/.. (common)
    root1 = Path(__file__).resolve().parents[1]
    cand1 = root1 / "scripts" / "run_cost_report.py"
    if cand1.exists():
        return cand1

    # Candidate 2: repo root = tests/../.. (when tests live under /app/app/tests)
    root2 = Path(__file__).resolve().parents[2]
    cand2 = root2 / "scripts" / "run_cost_report.py"
    if cand2.exists():
        return cand2

    # Candidate 3: explicit path under /app/app (dev container layout)
    cand3 = Path("/app/app/scripts/run_cost_report.py")
    if cand3.exists():
        return cand3

    raise FileNotFoundError(
        f"run_cost_report.py not found. Tried: {cand1}, {cand2}, {cand3}"
    )

SCRIPT = _resolve_script_path()



def _run(tmp_path: Path, events: list[dict], *, corrupt: bool = False):
    inp = tmp_path / "usage_events.jsonl"
    outdir = tmp_path / "reports"
    outdir.mkdir(parents=True, exist_ok=True)

    with inp.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
        if corrupt:
            f.write("{ not-json }\n")

    cmd = [sys.executable, str(SCRIPT), "--in", str(inp), "--outdir", str(outdir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res, outdir


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_status_mapping_ok_unknown(tmp_path: Path):
    events = [
        {"provider": "stub", "status": "ok", "created_at": "2026-02-17T10:00:00Z", "estimated_cost": 0.01},
        {"provider": "openai", "status": "unknown", "created_at": "2026-02-16T10:00:00Z", "estimated_cost": 0.02},
    ]
    res, outdir = _run(tmp_path, events)
    assert res.returncode == 0, res.stderr

    rows = _read_csv(outdir / "cost_by_status.csv")
    statuses = [r["status"] for r in rows]
    assert "success" in statuses
    assert "other" in statuses


def test_deterministic_order_provider_status_day(tmp_path: Path):
    events = [
        {"provider": "stub", "status": "ok", "created_at": "2026-02-17T10:00:00Z", "estimated_cost": 0.01},
        {"provider": "openai", "status": "unknown", "created_at": "2026-02-16T10:00:00Z", "estimated_cost": 0.02},
        {"provider": "anthropic", "status": "ok", "created_at": "2026-02-16T11:00:00Z", "estimated_cost": 0.03},
        {"provider": "openai", "status": "ok", "created_at": "2026-02-17T12:00:00Z", "estimated_cost": 0.04},
    ]
    res, outdir = _run(tmp_path, events)
    assert res.returncode == 0, res.stderr

    by_provider = _read_csv(outdir / "cost_by_provider.csv")
    providers = [r["provider"] for r in by_provider]
    assert providers == sorted(providers)

    by_status = _read_csv(outdir / "cost_by_status.csv")
    statuses = [r["status"] for r in by_status]
    assert statuses == sorted(statuses)

    by_day = _read_csv(outdir / "cost_by_day.csv")
    days = [r["day"] for r in by_day]
    assert days == sorted(days)


def test_csv_headers(tmp_path: Path):
    events = [{"provider": "stub", "status": "ok", "created_at": "2026-02-17T10:00:00Z", "estimated_cost": 0.01}]
    res, outdir = _run(tmp_path, events)
    assert res.returncode == 0, res.stderr

    rows = _read_csv(outdir / "cost_by_provider.csv")
    assert list(rows[0].keys()) == ["provider", "events_count", "estimated_cost"]

    rows = _read_csv(outdir / "cost_by_status.csv")
    assert list(rows[0].keys()) == ["status", "events_count", "estimated_cost"]

    rows = _read_csv(outdir / "cost_by_day.csv")
    assert list(rows[0].keys()) == ["day", "events_count", "estimated_cost"]


def test_invalid_jsonl_line_fails_cleanly(tmp_path: Path):
    events = [{"provider": "stub", "status": "ok", "created_at": "2026-02-17T10:00:00Z", "estimated_cost": 0.01}]
    res, _ = _run(tmp_path, events, corrupt=True)
    assert res.returncode != 0
    msg = (res.stderr + res.stdout).lower()
    assert "invalid json" in msg
    assert "line" in msg
