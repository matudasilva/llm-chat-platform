#!/usr/bin/env python3
"""
Offline cost analytics report generator (read-only).

Input: JSONL exported usage events (no external calls, no DB writes)
Output:
  - Console summary (human-readable)
  - Deterministic CSV artifacts under reports/

Constraints:
  - Standard library only (no pandas)
  - No schema changes
  - No runtime changes to /chat
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from pathlib import Path


STATUS_CANONICAL_MAP = {
    "success": "success",
    "ok": "success",
    "error": "error",
}


def canonical_status(raw: Any) -> str:
    s = "" if raw is None else str(raw).strip().lower()
    return STATUS_CANONICAL_MAP.get(s, "other")


def parse_iso_datetime(value: Any) -> Optional[datetime]:
    """
    Best-effort parse ISO datetime from JSONL.
    Supports:
      - "2026-02-13T12:34:56.123456+00:00"
      - "2026-02-13T12:34:56+00:00"
      - "2026-02-13T12:34:56Z"
      - naive ISO (treated as UTC)
    Returns None if parsing fails.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Handle trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def extract_day_iso(event: Dict[str, Any]) -> str:
    """
    Day bucket is derived from timestamp-like fields.
    Preference order:
      1) timestamp (canonical per earlier verification)
      2) created_at
    Falls back to "unknown" if neither is parseable.
    """
    dt = parse_iso_datetime(event.get("timestamp"))
    if dt is None:
        dt = parse_iso_datetime(event.get("created_at"))
    if dt is None:
        return "unknown"
    return dt.astimezone(timezone.utc).date().isoformat()


def safe_float(x: Any) -> float:
    try:
        if x is None:
            return 0.0
        return float(x)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class AggRow:
    key: str
    events_count: int
    estimated_cost: float


def read_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSONL at line {line_no}: {e}") from e
            if not isinstance(obj, dict):
                raise ValueError(
                    f"Invalid JSONL at line {line_no}: expected object, got {type(obj).__name__}"
                )
            yield obj


def ensure_reports_dir(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

def read_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise SystemExit(f"Invalid JSON at line {line_no}: {e.msg}")

def write_csv(path: str, header: List[str], rows: Iterable[List[Any]]) -> None:
    # Deterministic output: newline="" + utf-8 + explicit header
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def aggregate(
    events: Iterable[Dict[str, Any]],
) -> Tuple[
    Dict[str, Tuple[int, float]],
    Dict[str, Tuple[int, float]],
    Dict[str, Tuple[int, float]],
    int,
    float,
]:
    """
    Returns:
      by_provider: provider -> (count, cost)
      by_status: canonical_status -> (count, cost)
      by_day: day_iso -> (count, cost)
      total_events, total_cost
    """
    by_provider: Dict[str, Tuple[int, float]] = {}
    by_status: Dict[str, Tuple[int, float]] = {}
    by_day: Dict[str, Tuple[int, float]] = {}

    total_events = 0
    total_cost = 0.0

    for ev in events:
        provider = str(ev.get("provider") or "").strip() or "unknown"
        status = canonical_status(ev.get("status"))
        day = extract_day_iso(ev)

        # Exporter should already include this, but be defensive.
        est_cost = safe_float(ev.get("estimated_cost"))

        total_events += 1
        total_cost += est_cost

        c, s = by_provider.get(provider, (0, 0.0))
        by_provider[provider] = (c + 1, s + est_cost)

        c, s = by_status.get(status, (0, 0.0))
        by_status[status] = (c + 1, s + est_cost)

        c, s = by_day.get(day, (0, 0.0))
        by_day[day] = (c + 1, s + est_cost)

    return by_provider, by_status, by_day, total_events, total_cost


def fmt_money(x: float) -> str:
    # Keep stable formatting for console; CSV keeps numeric floats.
    return f"{x:.6f}"


def print_console_summary(
    by_provider: Dict[str, Tuple[int, float]],
    by_status: Dict[str, Tuple[int, float]],
    by_day: Dict[str, Tuple[int, float]],
    total_events: int,
    total_cost: float,
) -> None:
    print("")
    print("=== Cost Report (offline, read-only) ===")
    print(f"events_total: {total_events}")
    print(f"estimated_cost_total: {fmt_money(total_cost)}")
    print("")

    print("-- cost_by_provider --")
    for provider in sorted(by_provider.keys()):
        c, s = by_provider[provider]
        print(f"{provider}\tevents={c}\tcost={fmt_money(s)}")
    print("")

    print("-- cost_by_status (canonical) --")
    for status in sorted(by_status.keys()):
        c, s = by_status[status]
        print(f"{status}\tevents={c}\tcost={fmt_money(s)}")
    print("")

    print("-- cost_by_day (UTC) --")
    for day in sorted(by_day.keys()):
        c, s = by_day[day]
        print(f"{day}\tevents={c}\tcost={fmt_money(s)}")
    print("")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Generate offline cost analytics reports from UsageEvent JSONL."
    )
    p.add_argument(
        "--in",
        dest="in_path",
        required=True,
        help="Path to input JSONL file (exported usage events).",
    )
    p.add_argument(
        "--outdir",
        dest="out_dir",
        default="reports",
        help="Output directory for CSV reports (default: reports).",
    )
    args = p.parse_args()

    in_path = args.in_path
    if not os.path.isfile(in_path):
        raise SystemExit(f"Input not found: {in_path}")

    out_dir = args.out_dir
    ensure_reports_dir(out_dir)

    events_iter = list(read_jsonl(in_path))
    by_provider, by_status, by_day, total_events, total_cost = aggregate(events_iter)

    # Console output
    print_console_summary(by_provider, by_status, by_day, total_events, total_cost)

    # CSV artifacts (deterministic ordering)
    provider_csv = os.path.join(out_dir, "cost_by_provider.csv")
    status_csv = os.path.join(out_dir, "cost_by_status.csv")
    day_csv = os.path.join(out_dir, "cost_by_day.csv")

    write_csv(
        provider_csv,
        header=["provider", "events_count", "estimated_cost"],
        rows=[[k, by_provider[k][0], by_provider[k][1]] for k in sorted(by_provider.keys())],
    )
    print(f"[OK] wrote {provider_csv}")

    write_csv(
        status_csv,
        header=["status", "events_count", "estimated_cost"],
        rows=[[k, by_status[k][0], by_status[k][1]] for k in sorted(by_status.keys())],
    )
    print(f"[OK] wrote {status_csv}")

    write_csv(
        day_csv,
        header=["day", "events_count", "estimated_cost"],
        rows=[[k, by_day[k][0], by_day[k][1]] for k in sorted(by_day.keys())],
    )
    print(f"[OK] wrote {day_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

