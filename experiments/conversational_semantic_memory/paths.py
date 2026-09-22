"""Single source of every ORQ-39 path.

Code and the authored pools are versioned under this package, so a clean clone
can rebuild the experiment. Run evidence (event log, checks, ledgers, results)
lives under the ORQ folder, which is gitignored under `artifact_policy:
hybrid` -- the same split ORQ-30 used.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent

POOLS_DIR = PACKAGE_DIR / "pools"
DEV_POOL = POOLS_DIR / "dev-pool.json"
HELDOUT_POOL = POOLS_DIR / "heldout-pool.json"
DATA_DIR = PACKAGE_DIR / "data"
DEV_DATASET = DATA_DIR / "dev-dataset.json"

ORQ_DIR = REPO_ROOT / ".framework/orqs/ORQ-39-conversational-semantic-memory"
EVIDENCE_DIR = ORQ_DIR / "evidence"
EVENTS_LOG = EVIDENCE_DIR / "events.jsonl"
CHECKS_DIR = EVIDENCE_DIR / "checks"
