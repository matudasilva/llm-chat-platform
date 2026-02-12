import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, Any, Tuple

# Reuse Day 15 helper (provider-agnostic)
from core.utils.costs import estimate_cost



def _iter_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _day_bucket(created_at_iso: str) -> str:
    # created_at is ISO string
    dt = datetime.fromisoformat(created_at_iso)
    return dt.date().isoformat()


def main() -> None:
    p = argparse.ArgumentParser(description="Offline cost report from exported usage_events (JSONL).")
    p.add_argument("--in", dest="in_path", default="reports/usage_events.jsonl", help="Input JSONL export.")
    p.add_argument("--out-csv", default="reports/cost_report.csv", help="Output CSV (summary).")
    p.add_argument("--write-csv", action="store_true", help="Write CSV output file.")
    args = p.parse_args()

    total_cost = 0.0
    by_provider = defaultdict(float)
    by_status = defaultdict(float)
    by_day = defaultdict(float)

    # optional: counts for context
    counts = defaultdict(int)  # keys: total, success, error, etc.
    by_provider_count = defaultdict(int)

    for ev in _iter_jsonl(args.in_path):
        provider = (ev.get("provider") or "unknown").strip()
        status = (ev.get("status") or "unknown").strip()

        # Tokens may be null; helper clamps negatives but not None
        in_tok = ev.get("input_tokens") or 0
        out_tok = ev.get("output_tokens") or 0

        cost = float(estimate_cost(provider, in_tok, out_tok))

        total_cost += cost
        by_provider[provider] += cost
        by_status[status] += cost

        if ev.get("timestamp"):
            by_day[_day_bucket(ev["timestamp"])] += cost

        counts["total_events"] += 1
        counts[f"status:{status}"] += 1
        by_provider_count[provider] += 1

    # stdout summary (human-readable)
    print("=== Cost Report (offline) ===")
    print(f"events_total={counts['total_events']}")
    print(f"estimated_cost_total={total_cost:.6f}")

    print("\n-- Cost by provider --")
    for k in sorted(by_provider.keys()):
        print(f"{k} cost={by_provider[k]:.6f} events={by_provider_count[k]}")

    print("\n-- Cost by status --")
    for k in sorted(by_status.keys()):
        print(f"{k} cost={by_status[k]:.6f} events={counts.get(f'status:{k}', 0)}")

    if by_day:
        print("\n-- Cost by day --")
        for day in sorted(by_day.keys()):
            print(f"{day} cost={by_day[day]:.6f}")

    # optional CSV output (summary rows)
    if args.write_csv:
        rows: Iterable[Tuple[str, str, float, int]] = []

        # provider rows
        provider_rows = [("provider", p, by_provider[p], by_provider_count[p]) for p in sorted(by_provider.keys())]
        status_rows = [("status", s, by_status[s], counts.get(f"status:{s}", 0)) for s in sorted(by_status.keys())]
        day_rows = [("day", d, by_day[d], 0) for d in sorted(by_day.keys())]

        out_rows = list(provider_rows) + list(status_rows) + list(day_rows)

        import os
        os.makedirs(os.path.dirname(args.out_csv) or ".", exist_ok=True)

        with open(args.out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["dimension", "key", "estimated_cost", "event_count"])
            for dim, key, cost, cnt in out_rows:
                w.writerow([dim, key, f"{cost:.6f}", cnt])

        print(f"\n[OK] wrote {args.out_csv}")


if __name__ == "__main__":
    main()
