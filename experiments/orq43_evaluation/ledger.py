"""Offline-only durable reservation ledger for the isolated ORQ-43 evaluator.

SQLite locking and durability are supported here only on verified ext4 mounts.
Other and unverified filesystems are rejected. This local-filesystem guard is
not certification against arbitrary power loss or hostile modification. This
module makes no provider calls. A call left ``dispatching`` is permanently
ambiguous.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Iterable


_VERIFIED_FILESYSTEMS = {"ext4"}


_SCHEMA = {
    "settings": "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "runs": """CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        manifest_hash TEXT NOT NULL,
        reservation TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','complete','failed'))
    )""",
    "calls": """CREATE TABLE calls (
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        call_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','dispatching','succeeded','failed')),
        PRIMARY KEY (run_id, call_id)
    )""",
    "call_bindings": """CREATE TABLE call_bindings (
        run_id TEXT NOT NULL,
        call_id TEXT NOT NULL,
        binding_json TEXT NOT NULL,
        PRIMARY KEY (run_id, call_id),
        FOREIGN KEY (run_id, call_id) REFERENCES calls(run_id, call_id)
    )""",
    "call_results": """CREATE TABLE call_results (
        run_id TEXT NOT NULL,
        call_id TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        PRIMARY KEY (run_id, call_id),
        FOREIGN KEY (run_id, call_id) REFERENCES calls(run_id, call_id)
    )""",
}


class LedgerError(RuntimeError):
    """Admission or state transition refused because safety is uncertain."""


def _mount_filesystem(path: Path) -> str:
    """Return the filesystem type for path using Linux mountinfo, or fail closed."""
    if not os.path.exists("/proc/self/mountinfo"):
        raise LedgerError("cannot verify ledger filesystem; refusing operation")
    target = path.resolve(strict=False)

    def unescape_mount_field(value: str) -> str:
        return (value.replace("\\040", " ").replace("\\011", "\t")
                .replace("\\012", "\n").replace("\\134", "\\"))

    candidates: list[tuple[int, str]] = []
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as mountinfo:
            for line in mountinfo:
                fields = line.rstrip("\n").split(" - ", 1)
                if len(fields) != 2:
                    continue
                before, after = fields
                mount_fields = before.split()
                filesystem_fields = after.split()
                if len(mount_fields) < 5 or not filesystem_fields:
                    continue
                mountpoint = Path(unescape_mount_field(mount_fields[4]))
                if target == mountpoint or mountpoint in target.parents:
                    candidates.append((len(mountpoint.parts), filesystem_fields[0]))
    except (OSError, UnicodeError) as exc:
        raise LedgerError("cannot verify ledger filesystem; refusing operation") from exc
    if not candidates:
        raise LedgerError("cannot verify ledger filesystem; refusing operation")
    deepest = max(depth for depth, _ in candidates)
    filesystems = [filesystem for depth, filesystem in candidates if depth == deepest]
    if len(filesystems) != 1:
        raise LedgerError("ambiguous ledger mount; refusing operation")
    return filesystems[0]


def _amount(value: Decimal | str) -> Decimal:
    if isinstance(value, (float, bool)):
        raise LedgerError("reservation must use exact decimal arithmetic")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LedgerError("invalid decimal amount") from exc
    if (not amount.is_finite() or amount < 0 or amount.adjusted() > 20
            or amount.as_tuple().exponent < -18 or len(amount.as_tuple().digits) > 40):
        raise LedgerError("amount must be finite and non-negative")
    return amount


class ReservationLedger:
    """SQLite ledger. Use :meth:`create` once and :meth:`open` thereafter."""

    def __init__(self, path: str | Path, *, mode: str,
                 ceiling_usd: Decimal | str | None = None):
        self.path = Path(path).absolute()
        if mode not in {"create", "open"}:
            raise LedgerError("use explicit create() or open()")
        if mode == "create" and ceiling_usd is None:
            raise LedgerError("create requires an approved ceiling")
        if mode == "open" and ceiling_usd is not None:
            raise LedgerError("open uses the immutable ceiling stored in the ledger")
        try:
            if mode == "create":
                if _mount_filesystem(self.path.parent) not in _VERIFIED_FILESYSTEMS:
                    raise LedgerError("ledger filesystem is not verified local ext4; refusing operation")
                self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect(create=(mode == "create"))) as db:
                db.execute("BEGIN EXCLUSIVE")
                names = self._table_names(db)
                if mode == "create":
                    if names:
                        raise LedgerError("ledger already exists; refusing reinitialization")
                    self.ceiling = _amount(ceiling_usd)
                    for statement in _SCHEMA.values():
                        db.execute(statement)
                    db.execute("INSERT INTO settings VALUES ('ceiling_usd', ?)", (str(self.ceiling),))
                    db.commit()
                else:
                    if not set(_SCHEMA).issubset(names):
                        raise LedgerError("ledger missing or schema invalid; refusing to initialize")
                    self._check_schema(db)
                    self.ceiling = self._read_ceiling(db)
                    self._check_state(db, self.ceiling)
                    db.commit()
        except (sqlite3.DatabaseError, OSError) as exc:
            raise LedgerError("ledger unavailable or corrupt; refusing to initialize") from exc

    @classmethod
    def create(cls, path: str | Path, *, ceiling_usd: Decimal | str) -> "ReservationLedger":
        return cls(path, mode="create", ceiling_usd=ceiling_usd)

    @classmethod
    def open(cls, path: str | Path) -> "ReservationLedger":
        return cls(path, mode="open")

    def _connect(self, *, create: bool) -> sqlite3.Connection:
        if _mount_filesystem(self.path.parent) not in _VERIFIED_FILESYSTEMS:
            raise LedgerError("ledger filesystem is not verified local ext4; refusing operation")
        if self.path.is_symlink():
            raise LedgerError("symlink ledger paths are unsupported")
        if self.path.exists() and _mount_filesystem(self.path) not in _VERIFIED_FILESYSTEMS:
            raise LedgerError("ledger filesystem is not verified local ext4; refusing operation")
        if create:
            db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        else:
            if not self.path.is_file():
                raise LedgerError("ledger missing; open never creates state")
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                                 timeout=30, isolation_level=None)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=30000")
            journal_mode = db.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            db.execute("PRAGMA synchronous=FULL")
            if journal_mode.lower() != "delete" or db.execute("PRAGMA synchronous").fetchone()[0] != 2:
                raise LedgerError("SQLite durability settings unavailable; refusing operation")
        except BaseException:
            db.close()
            raise
        return db

    @staticmethod
    def _table_names(db: sqlite3.Connection) -> set[str]:
        return {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

    @staticmethod
    def _check_schema(db: sqlite3.Connection) -> None:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise LedgerError("ledger integrity check failed")
        # Require the exact schema created by this version, including constraints.
        # Whitespace is immaterial; unknown or missing state is never repaired here.
        for name, expected in _SCHEMA.items():
            row = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            normalize = lambda sql: "".join(sql.lower().split())
            if row is None or row[0] is None or normalize(row[0]) != normalize(expected):
                raise LedgerError("ledger schema invalid; refusing to open")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise LedgerError("ledger foreign key integrity check failed")

    @staticmethod
    def _read_ceiling(db: sqlite3.Connection) -> Decimal:
        row = db.execute("SELECT value FROM settings WHERE key='ceiling_usd'").fetchone()
        if row is None:
            raise LedgerError("ledger ceiling missing")
        return _amount(row[0])

    @staticmethod
    def _check_state(db: sqlite3.Connection, ceiling: Decimal) -> None:
        if db.execute("SELECT COUNT(*) FROM runs WHERE status='active'").fetchone()[0] > 1:
            raise LedgerError("ledger has multiple active runs; refusing to open")
        with localcontext() as context:
            context.prec = 100
            total = sum((_amount(row[0]) for row in db.execute(
                "SELECT reservation FROM runs")), Decimal(0))
        if total > ceiling:
            raise LedgerError("stored reservations exceed approved ceiling; refusing to open")

    def admit(self, run_id: str, manifest_hash: str, reservation_usd: Decimal | str,
              calls: Iterable[str], *, bindings: dict[str, dict] | None = None) -> None:
        """Atomically reserve the complete run and register unique call IDs."""
        amount = _amount(reservation_usd)
        call_ids = tuple(calls)
        if not run_id or not manifest_hash or not call_ids or any(not x for x in call_ids):
            raise LedgerError("run identity and at least one call ID are required")
        if len(set(call_ids)) != len(call_ids):
            raise LedgerError("duplicate call ID")
        if bindings is not None and set(bindings) != set(call_ids):
            raise LedgerError("bindings must cover every call")
        try:
            serialized_bindings = ({key: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
                                    for key, value in bindings.items()} if bindings is not None else {})
        except (TypeError, ValueError) as exc:
            raise LedgerError("invalid call bindings") from exc
        try:
            with closing(self._connect(create=False)) as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                    raise LedgerError("run ID already exists; replay refused")
                if db.execute("SELECT 1 FROM runs WHERE status='active'").fetchone():
                    raise LedgerError("another run is active")
                ceiling = self._read_ceiling(db)
                if ceiling != self.ceiling:
                    raise LedgerError("ledger ceiling changed; refusing admission")
                with localcontext() as context:
                    context.prec = 100
                    total = sum((_amount(row[0]) for row in db.execute(
                        "SELECT reservation FROM runs")), Decimal(0))
                    if total + amount > ceiling:
                        raise LedgerError("reservation exceeds approved ceiling")
                db.execute("INSERT INTO runs VALUES (?, ?, ?, 'active')",
                           (run_id, manifest_hash, str(amount)))
                db.executemany("INSERT INTO calls VALUES (?, ?, 'pending')",
                               ((run_id, call_id) for call_id in call_ids))
                db.executemany("INSERT INTO call_bindings VALUES (?, ?, ?)",
                               ((run_id, key, value) for key, value in serialized_bindings.items()))
                db.commit()
        except sqlite3.DatabaseError as exc:
            raise LedgerError("ledger transaction failed; refusing admission") from exc

    def mark_dispatching(self, run_id: str, call_id: str) -> None:
        """Durably consume the call's sole dispatch opportunity before network I/O."""
        self._transition(run_id, call_id, "pending", "dispatching")

    def record_outcome(self, run_id: str, call_id: str, *, succeeded: bool,
                       evidence: dict | None = None) -> None:
        """Record a known result; a failure atomically stops all pending calls."""
        if not isinstance(succeeded, bool):
            raise LedgerError("succeeded must be boolean")
        try:
            evidence_json = json.dumps(evidence, sort_keys=True, separators=(',', ':'), allow_nan=False) if evidence is not None else None
        except (TypeError, ValueError) as exc:
            raise LedgerError("invalid result evidence") from exc
        try:
            with closing(self._connect(create=False)) as db:
                db.execute("BEGIN IMMEDIATE")
                self._require_active(db, run_id)
                changed = db.execute(
                    "UPDATE calls SET status=? WHERE run_id=? AND call_id=? AND status='dispatching'",
                    ("succeeded" if succeeded else "failed", run_id, call_id),
                ).rowcount
                if changed != 1:
                    raise LedgerError("call is absent or not dispatching")
                if evidence_json is not None:
                    db.execute("INSERT INTO call_results VALUES (?, ?, ?)",
                               (run_id, call_id, evidence_json))
                if not succeeded:
                    db.execute("UPDATE calls SET status='failed' WHERE run_id=? AND status='pending'",
                               (run_id,))
                    db.execute("UPDATE runs SET status='failed' WHERE run_id=?", (run_id,))
                db.commit()
        except sqlite3.DatabaseError as exc:
            raise LedgerError("ledger transaction failed") from exc

    def finish_run(self, run_id: str, *, failed: bool = False) -> None:
        """Close a successful run only after every call has a known outcome."""
        if not isinstance(failed, bool):
            raise LedgerError("failed must be boolean")
        try:
            with closing(self._connect(create=False)) as db:
                db.execute("BEGIN IMMEDIATE")
                self._require_active(db, run_id)
                if db.execute("SELECT 1 FROM calls WHERE run_id=? AND status NOT IN ('succeeded','failed') LIMIT 1",
                              (run_id,)).fetchone():
                    raise LedgerError("run has pending or ambiguous calls")
                db.execute("UPDATE runs SET status=? WHERE run_id=?",
                           ("failed" if failed else "complete", run_id))
                db.commit()
        except sqlite3.DatabaseError as exc:
            raise LedgerError("ledger transaction failed") from exc

    @staticmethod
    def _require_active(db: sqlite3.Connection, run_id: str) -> None:
        if db.execute("SELECT 1 FROM runs WHERE run_id=? AND status='active'",
                      (run_id,)).fetchone() is None:
            raise LedgerError("run is absent or no longer active")

    def _transition(self, run_id: str, call_id: str, old: str, new: str) -> None:
        try:
            with closing(self._connect(create=False)) as db:
                db.execute("BEGIN IMMEDIATE")
                self._require_active(db, run_id)
                if old == "pending" and db.execute(
                    "SELECT 1 FROM calls WHERE run_id=? AND status='dispatching' LIMIT 1",
                    (run_id,),
                ).fetchone():
                    raise LedgerError("another call is dispatching or ambiguous")
                changed = db.execute(
                    "UPDATE calls SET status=? WHERE run_id=? AND call_id=? AND status=?",
                    (new, run_id, call_id, old),
                ).rowcount
                if changed != 1:
                    raise LedgerError("call is absent, not ready, or already consumed")
                db.commit()
        except sqlite3.DatabaseError as exc:
            raise LedgerError("ledger transaction failed") from exc
