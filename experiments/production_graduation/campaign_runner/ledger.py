"""Append-only receipts. The caller must own RunnerLock for every mutation."""
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .admission import CAP, NORMAL, R_MAX, may_admit
from .states import TERMINAL, State


class LedgerError(ValueError):
    pass


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_directory(path: Path) -> None:
    """Persist every new directory entry before any economic admission."""
    if not path.is_dir():
        durable_directory(path.parent)
        try:
            path.mkdir()
        except FileExistsError:
            if not path.is_dir():
                raise
    # An existing component may be visible after an interrupted creation;
    # persist its parent entry too before creating a child or admitting work.
    sync_directory(path)
    sync_directory(path.parent)


class RunnerLock:
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        # Never steal a stale lock; operator removal is required.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            info = os.fstat(fd)
            self.identity = (info.st_dev, info.st_ino)
            os.write(fd, f"{os.getpid()}\n".encode())
            os.fsync(fd)
            sync_directory(self.path.parent)
        except BaseException:
            os.close(fd)
            raise
        # Retain ownership of the inode until release, preventing inode reuse.
        self.fd = fd
        return self

    def __exit__(self, *exc):
        try:
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode)
                    or (info.st_dev, info.st_ino) != self.identity):
                raise LedgerError("Runner lock identity changed")
            self.path.unlink()
            sync_directory(self.path.parent)
        finally:
            os.close(self.fd)


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.head_path = self.path.with_suffix(".head")
        if self.path.is_symlink() or self.head_path.is_symlink():
            raise LedgerError("Ledger paths must not be symlinks")
        if not self.path.exists():
            if self.head_path.exists():
                raise LedgerError("Previously created ledger is missing")
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            sync_directory(self.path.parent)
        self.entries = []
        self._file = os.fdopen(os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb")
        info = os.fstat(self._file.fileno())
        if not stat.S_ISREG(info.st_mode):
            self._file.close()
            raise LedgerError("Ledger is not a regular file")
        self.identity = (info.st_dev, info.st_ino)
        # Keep the validated inode alive; a replacement cannot reuse its number.
        raw = self._file.read()
        if not self.head_path.exists():
            if raw:
                raise LedgerError("Durable ledger head is missing")
            self._save_head("0" * 64)
        if raw and not raw.endswith(b"\n"):
            raise LedgerError("Truncated ledger")
        previous = "0" * 64
        try:
            for seq, line in enumerate(raw.splitlines(), 1):
                entry = json.loads(line)
                if canonical(entry) != line:
                    raise LedgerError("Noncanonical or ambiguous receipt")
                if entry["seq"] != seq or entry["prev_sha256"] != previous:
                    raise LedgerError("Broken hash chain")
                saved_hash = entry["sha256"]
                if digest({k: v for k, v in entry.items() if k != "sha256"}) != saved_hash:
                    raise LedgerError("Invalid receipt hash")
                previous = saved_hash
                self.entries.append(entry)
            self._validate(self.entries)
            head = self.head_path.read_text()
            if head not in {"0" * 64, *(e["sha256"] for e in self.entries)}:
                raise LedgerError("Ledger truncated behind durable head")
        except (KeyError, TypeError, ArithmeticError, json.JSONDecodeError) as exc:
            raise LedgerError("Malformed ledger") from exc

    def _save_head(self, value):
        # Ledger fsync precedes the atomic head replacement. An older head may
        # be a valid prefix after a crash; it must never refer to a missing line.
        temporary = self.head_path.with_suffix(".head.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(value.encode())
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("Incomplete head write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, self.head_path)
        sync_directory(self.path.parent)

    @staticmethod
    def _validate(entries):
        campaigns, admitted, settled, indices = {}, set(), set(), set()
        total = Decimal(0)
        for entry in entries:
            campaign, kind, payload = entry["campaign_id"], entry["type"], entry["payload"]
            if not isinstance(campaign, str) or not campaign or not isinstance(payload, dict):
                raise LedgerError("Invalid receipt identity")
            if kind == "CAMPAIGN_OPENED":
                if campaign in campaigns or any(v == "open" for v in campaigns.values()):
                    raise LedgerError("Duplicate or overlapping campaign")
                if Decimal(payload["cap"]) != CAP:
                    raise LedgerError("Changed cap")
                campaigns[campaign] = "open"
            elif kind == "RECONCILED":
                if campaigns.get(campaign) != "closed":
                    raise LedgerError("Reconciliation before close")
                # Informational only: never subtract from conservative settlement.
            else:
                if campaigns.get(campaign) != "open":
                    raise LedgerError("Receipt outside open campaign")
                key = (campaign, payload.get("request_id"))
                if kind == "REQUEST_ADMITTED":
                    index = (campaign, payload["seq_in_manifest"])
                    if not key[1] or key in admitted or index in indices or admitted - settled:
                        raise LedgerError("Duplicate or concurrent admission")
                    if Decimal(payload["reserve"]) != R_MAX or not may_admit(total):
                        raise LedgerError("Admission exceeds cap")
                    admitted.add(key)
                    indices.add(index)
                elif kind == "REQUEST_SETTLED":
                    if key not in admitted or key in settled:
                        raise LedgerError("Missing admission or duplicate settlement")
                    cost = Decimal(payload["conservative_usd"])
                    if cost not in (NORMAL, R_MAX):
                        raise LedgerError("Invalid conservative settlement")
                    if (payload.get("retry") or payload.get("evaluator") or payload.get("reasons")
                            or payload["status"] != "RESOLVED") and cost != R_MAX:
                        raise LedgerError("Stopping/unresolved request undercharged")
                    components = sum((Decimal(v) for v in payload["charges"].values()), Decimal(0))
                    if components != cost:
                        raise LedgerError("Charge mismatch")
                    total += cost
                    settled.add(key)
                    if total > CAP:
                        raise LedgerError("Spend exceeds cap")
                elif kind == "CAMPAIGN_CLOSED":
                    if admitted - settled or State(payload["state"]) not in TERMINAL:
                        raise LedgerError("Invalid close")
                    campaigns[campaign] = "closed"
                elif kind != "STOP":
                    raise LedgerError("Unknown receipt type")

    @property
    def total(self):
        return sum((Decimal(e["payload"]["conservative_usd"]) for e in self.entries
                    if e["type"] == "REQUEST_SETTLED"), Decimal(0))

    @property
    def open_campaign(self):
        opened = {e["campaign_id"] for e in self.entries if e["type"] == "CAMPAIGN_OPENED"}
        closed = {e["campaign_id"] for e in self.entries if e["type"] == "CAMPAIGN_CLOSED"}
        return next(iter(opened - closed), None)

    @property
    def pending(self):
        settled = {(e["campaign_id"], e["payload"]["request_id"]) for e in self.entries
                   if e["type"] == "REQUEST_SETTLED"}
        return [e for e in self.entries if e["type"] == "REQUEST_ADMITTED"
                and (e["campaign_id"], e["payload"]["request_id"]) not in settled]

    def append(self, campaign, kind, **payload):
        entry = {"seq": len(self.entries) + 1, "campaign_id": campaign, "type": kind,
                 "utc": datetime.now(timezone.utc).isoformat(), "payload": payload,
                 "prev_sha256": self.entries[-1]["sha256"] if self.entries else "0" * 64}
        entry["sha256"] = digest(entry)
        self._validate([*self.entries, entry])
        line = canonical(entry) + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode)
                    or (info.st_dev, info.st_ino) != self.identity):
                raise LedgerError("Ledger identity changed")
            view = memoryview(line)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("Incomplete ledger write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        self._save_head(entry["sha256"])
        self.entries.append(entry)
        return entry
