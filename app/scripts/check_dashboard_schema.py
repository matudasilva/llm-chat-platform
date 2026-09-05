"""AC5 — every field the dashboard artifact references exists in the schema.

The dashboard is a versioned artifact rather than a hosted instance (D-4: no
Compose service, no provisioned backend), so nothing renders it during
implementation and a panel referencing a field nobody emits would go unnoticed
until someone opened a dashboard that quietly showed nothing. This script is
what replaces that missing feedback.

It checks three things against `app/core/observability/schema.py`, which is the
single source AC4 also asserts emissions against:

* every ``spans`` entry is a declared span name;
* every ``attributes`` entry is an allow-listed attribute key;
* every ``span_fields`` entry is a span-intrinsic field, not an attribute.

The third exists because of a real trap. Duration is intrinsic to a span, so
``stage.duration_ms`` was removed from the allow-list rather than left declared
and unemitted -- a declared-but-unemitted key would let a panel pass this check
and then render empty, which is the exact failure the check is here to prevent.
Panels must therefore read duration as a span field, and a panel that lists it
as an attribute fails.

Usage:
    python3 app/scripts/check_dashboard_schema.py [path/to/dashboard.json]

Exit 0 when every reference resolves, 1 otherwise. Output is raw and lists each
unresolved reference with its panel, which is the evidence AC5 asks for.
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.observability.schema import (  # noqa: E402
    ALLOWED_ATTRIBUTE_KEYS,
    SPAN_NAMES,
)

DEFAULT_DASHBOARD = REPO_ROOT / "docs" / "observability" / "dashboard.json"

# Fields every span carries by construction. Not attributes, and deliberately
# not in the allow-list: the exporter provides them, so declaring them as
# attributes would mean emitting data the span already holds.
SPAN_INTRINSIC_FIELDS = frozenset({"name", "duration", "status", "start_time", "end_time"})

VALID_STATUSES = frozenset({"active", "pending"})


def check(dashboard_path: pathlib.Path) -> tuple[list[str], dict[str, int]]:
    findings: list[str] = []
    try:
        raw = json.loads(dashboard_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"dashboard artifact not found: {dashboard_path}"], {}
    except json.JSONDecodeError as exc:
        return [f"dashboard artifact is not valid JSON: {exc}"], {}

    if not isinstance(raw, dict) or "panels" not in raw:
        return ["dashboard artifact has no `panels` key"], {}

    panels = raw["panels"]
    if not isinstance(panels, list) or not panels:
        return ["dashboard artifact declares no panels"], {}

    seen_ids: set[str] = set()
    counts = {"panels": len(panels), "active": 0, "pending": 0, "references": 0}

    for index, panel in enumerate(panels):
        panel_id = panel.get("id") or f"<panel #{index}>"
        if panel_id in seen_ids:
            findings.append(f"{panel_id}: duplicate panel id")
        seen_ids.add(panel_id)

        status = panel.get("status")
        if status not in VALID_STATUSES:
            findings.append(
                f"{panel_id}: status {status!r} is not one of {sorted(VALID_STATUSES)}"
            )
        else:
            counts[status] += 1
        if status == "pending" and not panel.get("pending_reason"):
            findings.append(f"{panel_id}: pending panels must carry a pending_reason")

        for name in panel.get("spans", []):
            counts["references"] += 1
            if name not in SPAN_NAMES:
                findings.append(f"{panel_id}: span {name!r} is not declared in schema.py")

        for key in panel.get("attributes", []):
            counts["references"] += 1
            if key not in ALLOWED_ATTRIBUTE_KEYS:
                findings.append(
                    f"{panel_id}: attribute {key!r} is not in the schema allow-list"
                )

        for field in panel.get("span_fields", []):
            counts["references"] += 1
            if field in ALLOWED_ATTRIBUTE_KEYS:
                findings.append(
                    f"{panel_id}: {field!r} is an attribute, not a span-intrinsic field"
                )
            elif field not in SPAN_INTRINSIC_FIELDS:
                findings.append(
                    f"{panel_id}: span field {field!r} is not one of "
                    f"{sorted(SPAN_INTRINSIC_FIELDS)}"
                )

        if not panel.get("spans"):
            findings.append(f"{panel_id}: references no span")

    return findings, counts


def main(argv: list[str]) -> int:
    path = pathlib.Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_DASHBOARD
    findings, counts = check(path)

    print(f"dashboard: {path}")
    print(f"schema:    {len(SPAN_NAMES)} span names, {len(ALLOWED_ATTRIBUTE_KEYS)} attribute keys")
    if counts:
        print(
            f"panels:    {counts['panels']} "
            f"({counts['active']} active, {counts['pending']} pending), "
            f"{counts['references']} references checked"
        )

    if findings:
        print(f"RESULT dashboard_schema=failed findings={len(findings)}")
        for finding in findings:
            print(f"  - {finding}")
        return 1

    print("RESULT dashboard_schema=ok findings=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
