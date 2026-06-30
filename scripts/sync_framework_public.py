#!/usr/bin/env python3
"""
Sync a small public-facing summary of internal framework metadata.

Reads:
  .framework/framework-version  — single-line: framework_version=X.Y.Z
  .framework/project-config.yml — extracts governance_sync.targets.dashboard.ref

Writes:
  .framework-public.yml — tracked in git; used by CI drift check

Exit codes:
  0  success
  1  input file missing or parse error
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW_VERSION_FILE = ROOT / ".framework" / "framework-version"
FW_CONFIG_FILE = ROOT / ".framework" / "project-config.yml"
OUTPUT_FILE = ROOT / ".framework-public.yml"


def read_framework_version() -> str:
    if not FW_VERSION_FILE.exists():
        raise FileNotFoundError(f"Missing: {FW_VERSION_FILE}")
    for line in FW_VERSION_FILE.read_text().splitlines():
        m = re.match(r"^framework_version=(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    raise ValueError(f"framework_version= not found in {FW_VERSION_FILE}")


def read_dashboard_ref() -> str:
    if not FW_CONFIG_FILE.exists():
        raise FileNotFoundError(f"Missing: {FW_CONFIG_FILE}")
    text = FW_CONFIG_FILE.read_text()
    # Find the dashboard block and extract its ref value.
    # Looks for 'dashboard:' followed (within a few lines) by 'ref: <value>'
    in_dashboard = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "dashboard:":
            in_dashboard = True
            continue
        if in_dashboard:
            # Stop if we hit another top-level key at the same indent level
            if stripped and not stripped.startswith("type:") and not stripped.startswith("name:") and not stripped.startswith("ref:") and not line.startswith("      "):
                break
            m = re.match(r"^\s+ref:\s+(.+)$", line)
            if m:
                return m.group(1).strip()
    raise ValueError(f"dashboard.ref not found in {FW_CONFIG_FILE}")


def main() -> int:
    try:
        version = read_framework_version()
        ref = read_dashboard_ref()
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    content = f'framework_version: "{version}"\nref: {ref}\n'
    OUTPUT_FILE.write_text(content)
    print(f"Written: {OUTPUT_FILE}")
    print(f"  framework_version: {version}")
    print(f"  ref: {ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
