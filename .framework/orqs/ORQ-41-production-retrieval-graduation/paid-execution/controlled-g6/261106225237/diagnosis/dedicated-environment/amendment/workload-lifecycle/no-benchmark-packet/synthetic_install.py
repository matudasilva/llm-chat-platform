"""Offline-only, exclusive installer seam for one bound synthetic run.

There is no CLI. Production installation uses a fixed root-owned parent and an
explicit caller-supplied staging authorization. The private directory-fd seam
is used only by tests with fresh temporary directories.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import PurePosixPath

from experiments.production_graduation.gate_validation import dedicated_lifecycle as life


PARENT = "/var/lib/orq41-cpuset"
CORE_SHA = "9d8547bd60265c883ae46a1987776f6138f7c1a62dacb2f07dba26d8fc488545"
LEGACY_SHA = "8064e669e1921475167fb70fb73d3746cb4c034fa02fe207c7ffa749346b2be2"
LANE = (".framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/"
        "controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/"
        "workload-lifecycle/no-benchmark-packet/")
REVIEWED = {
    "core.py": "experiments/production_graduation/gate_validation/dedicated_lifecycle.py",
    "host.py": "experiments/production_graduation/gate_validation/dedicated_lifecycle_host.py",
    "environment.py": "experiments/production_graduation/gate_validation/dedicated_environment.py",
    "host_helper.py": (".framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/"
                       "controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/"
                       "workload-lifecycle/host_helper.py"),
}
ADAPTERS = ("controller", "worker", "packet", "bootstrap")
SOURCE_FILES = {
    "admin.py", "core.py", "environment.py", "host.py", "host_helper.py",
    "source-review.json", "synthetic/core.py",
    "synthetic/synthetic_bootstrap.py", "synthetic/synthetic_controller.py",
    "synthetic/synthetic_packet.py", "synthetic/synthetic_worker.py",
    "synthetic/synthetic_install.py", "synthetic/synthetic_launch.py",
    "synthetic/synthetic_create.py",
}
FINAL_DESTINATIONS = {
    "plan.json": (0, 0, "0600"),
    "deployment.json": (0, 0, "0600"),
    "journal/manifest.json": (0, 0, "0600"),
    "journal/events.jsonl": (0, 0, "0600"),
    "journal/head.json": (0, 0, "0600"),
    "journal/lock": (0, 0, "0600"),
    "journal/installation-complete.json": (0, 0, "0600"),
    "synthetic/plan.json": (0, 1000, "0640"),
}
DIRECTORIES = {
    ".": (0, 0, "0711"),
    "journal": (0, 0, "0700"),
    "synthetic": (0, 1000, "0750"),
    "receipts": (1000, 1000, "0700"),
}
MAX_FILES = 24
MAX_DIRECTORIES = 4
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check_relative(name: str) -> None:
    path = PurePosixPath(name)
    life.require(isinstance(name, str) and name and not path.is_absolute()
                 and all(part not in ("", ".", "..") for part in name.split("/"))
                 and str(path) == name, "Unsafe installer destination")


def prepare_review(run_id, source_payloads):
    """Build a content-pinned preparation manifest with no identity-late files."""
    life.require(isinstance(run_id, str) and re.fullmatch(r"[0-9]{12}", run_id),
                 "Invalid synthetic run identity")
    life.require(isinstance(source_payloads, dict) and set(source_payloads) == SOURCE_FILES,
                 "Preparation must pin the exact approved source set")
    files = {}
    total = 0
    for name, value in source_payloads.items():
        _check_relative(name)
        life.require(isinstance(value, bytes), "Preparation sources must be bytes")
        life.require(len(value) <= MAX_FILE_BYTES, "Preparation source exceeds file limit")
        total += len(value)
        uid, gid, mode = (0, 1000, "0640") if name.startswith("synthetic/") else (0, 0, "0600")
        files[name] = {"content": value.decode("utf-8"), "sha256": _sha(value),
                       "uid": uid, "gid": gid, "mode": mode}
    life.require(total <= MAX_TOTAL_BYTES, "Preparation sources exceed total byte limit")
    return {"status": "PREPARATION_ONLY_NOT_EXECUTABLE", "executable": False,
        "writes_performed": 0, "state_path": PARENT + "/" + run_id,
        "files": files, "final_destinations": {
            name: {"uid": uid, "gid": gid, "mode": mode}
            for name, (uid, gid, mode) in FINAL_DESTINATIONS.items()},
        "directories": [{"path": name, "uid": uid, "gid": gid, "mode": mode}
                        for name, (uid, gid, mode) in DIRECTORIES.items()],
        "authorization": None}


def _approval(review, approval):
    life.require(isinstance(review, dict) and review.get("status") == "PREPARATION_ONLY_NOT_EXECUTABLE"
                 and review.get("executable") is False and review.get("authorization") is None,
                 "Expected offline preparation manifest")
    run_id = review.get("state_path", "").rsplit("/", 1)[-1]
    life.require(re.fullmatch(r"[0-9]{12}", run_id) and review.get("state_path") == PARENT + "/" + run_id,
                 "Preparation run path is not fixed")
    expected = {"status": "OPERATOR_AUTHORIZED_SYNTHETIC_STAGING",
                "review_sha256": life.digest(review), "run_id": run_id,
                "dormant_controller": True}
    life.require(approval == expected, "Missing or mismatched caller-supplied staging authorization")
    files, destinations, dirs = (review.get("files"), review.get("final_destinations"),
                                  review.get("directories"))
    life.require(isinstance(files, dict) and set(files) == SOURCE_FILES
                 and isinstance(destinations, dict) and set(destinations) == set(FINAL_DESTINATIONS)
                 and isinstance(dirs, list) and len(dirs) == len(DIRECTORIES),
                 "Preparation allowlist differs")
    life.require(len(files) + len(destinations) <= MAX_FILES and len(dirs) <= MAX_DIRECTORIES,
                 "Preparation exceeds count limits")
    total = 0
    source_bytes = {}
    for name, entry in files.items():
        _check_relative(name)
        life.require(name in SOURCE_FILES and isinstance(entry, dict)
                     and set(entry) == {"content", "sha256", "uid", "gid", "mode"},
                     "Invalid preparation source entry")
        raw = entry["content"].encode("utf-8") if isinstance(entry.get("content"), str) else None
        life.require(raw is not None and len(raw) <= MAX_FILE_BYTES and entry["sha256"] == _sha(raw),
                     "Prepared source length or hash mismatch")
        total += len(raw)
        source_bytes[name] = raw
    life.require(total <= MAX_TOTAL_BYTES, "Preparation sources exceed byte limit")
    expected_destinations = {name: {"uid": uid, "gid": gid, "mode": mode}
                             for name, (uid, gid, mode) in FINAL_DESTINATIONS.items()}
    expected_dirs = [{"path": name, "uid": uid, "gid": gid, "mode": mode}
                     for name, (uid, gid, mode) in DIRECTORIES.items()]
    life.require(destinations == expected_destinations and dirs == expected_dirs,
                 "Prepared modes, owners, or destination schema differs")
    return run_id, source_bytes


def _open_fixed_parent():
    """Open the fixed root-owned parent through no-follow directory descriptors."""
    fd = os.open("/", _FLAGS)
    try:
        for component in PARENT.strip("/").split("/"):
            child = os.open(component, _FLAGS, dir_fd=fd)
            info = os.fstat(child)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
                os.close(child)
                raise ValueError("Installer ancestry must be root-owned real directories")
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        life.require(info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o700,
                     "Fixed installer parent must remain root:root 0700")
        return fd
    except BaseException:
        os.close(fd)
        raise


def begin_install(review, stage_authorization):
    """Create the approved fresh run's directories and presealed sources."""
    life.require(os.geteuid() == 0, "Production installation requires root")
    parent_fd = _open_fixed_parent()
    try:
        return _begin_at(parent_fd, review, stage_authorization, owner_uid=0,
                         owner_gid=0, production=True)
    finally:
        os.close(parent_fd)


def _begin_at(parent_fd, review, stage_authorization, *, owner_uid, owner_gid, production=False):
    """Private low-level primitive for isolated tests; never accepts arbitrary paths."""
    run_id, source_bytes = _approval(review, stage_authorization)
    os.mkdir(run_id, 0o711, dir_fd=parent_fd)
    run_fd = os.open(run_id, _FLAGS, dir_fd=parent_fd)
    directory_fds = {".": run_fd}
    try:
        if production:
            os.fchown(run_fd, 0, 0)
        os.fchmod(run_fd, 0o711)
        os.fsync(run_fd)
        os.fsync(parent_fd)
        for name, (uid, gid, mode_text) in DIRECTORIES.items():
            if name == ".":
                continue
            mode = int(mode_text, 8)
            actual_uid = owner_uid if not production and uid == 1000 else uid
            actual_gid = owner_gid if not production and gid == 1000 else gid
            os.mkdir(name, mode, dir_fd=run_fd)
            child = os.open(name, _FLAGS, dir_fd=run_fd)
            if production:
                os.fchown(child, actual_uid, actual_gid)
            os.fchmod(child, mode)
            os.fsync(child)
            os.fsync(run_fd)
            directory_fds[name] = child
        for name, raw in source_bytes.items():
            _write_file(directory_fds, name, raw, review["files"][name], production=production,
                        test_uid=owner_uid, test_gid=owner_gid)
        for fd in directory_fds.values():
            os.fsync(fd)
        receipt_fd = os.dup(directory_fds["receipts"])
        info = os.fstat(receipt_fd)
        expected_uid = 1000 if production else owner_uid
        expected_gid = 1000 if production else owner_gid
        life.require(stat.S_ISDIR(info.st_mode) and info.st_uid == expected_uid
                     and info.st_gid == expected_gid and stat.S_IMODE(info.st_mode) == 0o700,
                     "Receipts directory identity differs")
        tx = InstallTransaction(run_id, review, source_bytes, directory_fds, receipt_fd,
                                production, owner_uid, owner_gid)
        tx.handoff = {"run_id": run_id, "review_sha256": life.digest(review),
                      "receipt_identity": {"dev": info.st_dev, "ino": info.st_ino,
                          "uid": info.st_uid, "gid": info.st_gid,
                          "mode": stat.S_IMODE(info.st_mode)}}
        return tx
    except BaseException:
        for fd in directory_fds.values():
            if fd != run_fd:
                os.close(fd)
        os.close(run_fd)
        raise


def _write_file(directory_fds, name, raw, entry, *, production, test_uid, test_gid):
    _check_relative(name)
    parent_name, leaf = name.rsplit("/", 1) if "/" in name else (".", name)
    parent_fd = directory_fds[parent_name]
    mode = int(entry["mode"], 8)
    fd = os.open(leaf, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 mode, dir_fd=parent_fd)
    try:
        os.fchmod(fd, mode)
        uid, gid = entry["uid"], entry["gid"]
        if production:
            os.fchown(fd, uid, gid)
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(raw)
            stream.flush()
        info = os.fstat(fd)
        life.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == len(raw)
                     and stat.S_IMODE(info.st_mode) == mode
                     and (not production or (info.st_uid == uid and info.st_gid == gid))
                     and _hash_fd(fd) == _sha(raw), "Prepared file readback mismatch")
        os.fsync(fd)
        os.fsync(parent_fd)
    finally:
        os.close(fd)


def _hash_fd(fd):
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _proc_identity(pid):
    """Read a live process identity and all credential slots from procfs."""
    life.require(type(pid) is int and pid > 0, "Invalid controller PID")
    with open(f"/proc/{pid}/stat", "rb") as stream:
        raw = stream.read(8192)
    close = raw.rfind(b")")
    life.require(close > 0, "Malformed controller stat")
    fields = raw[close + 2:].split()
    life.require(len(fields) > 19, "Incomplete controller stat")
    start = int(fields[19])
    credentials = {}
    with open(f"/proc/{pid}/status", "rt", encoding="ascii") as stream:
        for line in stream:
            if line.startswith(("Uid:", "Gid:")):
                key, values = line.split(":", 1)
                credentials[key] = [int(value) for value in values.split()]
    uids, gids = credentials.get("Uid", []), credentials.get("Gid", [])
    life.require(len(uids) == len(gids) == 4 and len(set(uids)) == len(set(gids)) == 1,
                 "Controller credential slots differ")
    return {"pid": pid, "uid": uids[0], "gid": gids[0], "start": start}


class InstallTransaction:
    """One-shot finalizer handle. Created state is never automatically removed."""
    def __init__(self, run_id, review, source_bytes, directory_fds, receipt_fd,
                 production, owner_uid, owner_gid):
        self.run_id = run_id
        self.review = review
        self.source_bytes = dict(source_bytes)
        self._fds = directory_fds
        self.run_fd = os.dup(directory_fds["."])
        self.receipt_fd = receipt_fd
        self.production = production
        self.owner_uid, self.owner_gid = owner_uid, owner_gid
        self.handoff = None
        self._finalized = False

    def _read_source(self, name):
        raw = self.source_bytes[name]
        parent_name, leaf = name.rsplit("/", 1) if "/" in name else (".", name)
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=self._fds[parent_name])
        try:
            info = os.fstat(fd)
            life.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                         and info.st_size == len(raw) and _hash_fd(fd) == _sha(raw),
                         "Prepared on-disk source differs")
            return raw
        finally:
            os.close(fd)

    def _validate_plan(self, plan, manifest, actual_peer):
        life.require(isinstance(plan, dict) and plan.get("run_id") == self.run_id
                     and plan.get("packet_kind") == "synthetic_no_benchmark_v1",
                     "Final plan is not bound to this synthetic run")
        life.require(manifest.get("run_id") == self.run_id
                     and manifest.get("plan_sha256") == life.digest(plan)
                     and manifest.get("controller") == actual_peer,
                     "Final manifest/controller binding differs")
        life.validate_manifest(manifest)
        adapter_pins = plan.get("synthetic_adapter_sha256")
        life.require(isinstance(adapter_pins, dict) and set(adapter_pins) == set(ADAPTERS),
                     "Synthetic adapter pin set differs")
        adapter_names = {"controller": "synthetic_controller.py", "worker": "synthetic_worker.py",
                         "packet": "synthetic_packet.py", "bootstrap": "synthetic_bootstrap.py"}
        for key, leaf in adapter_names.items():
            life.require(adapter_pins[key] == _sha(self._read_source("synthetic/" + leaf)),
                         "Final plan adapter source hash differs")
        life.require(plan.get("synthetic_core_sha256") == CORE_SHA
                     and _sha(self._read_source("synthetic/core.py")) == CORE_SHA,
                     "Final plan core source differs")
        harness = plan.get("harness_sha256")
        life.require(isinstance(harness, dict), "Final plan harness pins are missing")
        for key, leaf in adapter_names.items():
            life.require(harness.get(LANE + "synthetic_" + key + ".py") == adapter_pins[key],
                         "Final plan synthetic harness pin differs")
        for leaf in ("synthetic_install.py", "synthetic_launch.py", "synthetic_create.py"):
            name = "synthetic/" + leaf
            life.require(harness.get(LANE + leaf) == _sha(self._read_source(name)),
                         "Final plan installation harness pin differs")
        support = plan.get("support_files_sha256")
        life.require(isinstance(support, dict) and not (set(harness) & set(support)),
                     "Final plan source pins overlap")
        # Source review binds the reviewed five-file deployment bundle.
        review = life.decode(self._read_source("source-review.json"))
        life.require(review.get("status") == "WORKLOAD_LIFECYCLE_SOURCE_REVIEW_PASS"
                     and review.get("new_blocker_high_medium_findings") == []
                     and all(review.get("technical_files_sha256", {}).get(path)
                             == _sha(self._read_source(name))
                             for name, path in REVIEWED.items())
                     and _sha(self._read_source("admin.py")) == LEGACY_SHA
                     and _sha(self._read_source("core.py")) == CORE_SHA,
                     "Reviewed source identity differs")

    def finalize(self, plan, manifest, controller_peer):
        life.require(not self._finalized, "Installer transaction is already finalized")
        actual_peer = _proc_identity(controller_peer.get("pid") if isinstance(controller_peer, dict) else None)
        life.require(controller_peer == actual_peer, "Controller peer identity is not current")
        self._validate_plan(plan, manifest, actual_peer)
        for name in SOURCE_FILES:
            self._read_source(name)
        plan_raw, manifest_raw = life.encode(plan), life.encode(manifest)
        reviewed = {name: self._read_source(name) for name in
                    ("admin.py", "core.py", "environment.py", "host.py", "host_helper.py")}
        source_review = self._read_source("source-review.json")
        deployment = life.encode({"schema": 1, "files": {name: _sha(raw) for name, raw in reviewed.items()},
            "plan_sha256": _sha(plan_raw), "manifest_sha256": _sha(manifest_raw),
            "source_review_sha256": _sha(source_review)})
        payloads = {"plan.json": plan_raw, "deployment.json": deployment,
            "journal/manifest.json": manifest_raw, "journal/events.jsonl": b"",
            "journal/head.json": life.encode({"count": 0, "hash": "0" * 64}),
            "journal/lock": b"", "synthetic/plan.json": plan_raw}
        completion = life.encode({"status": "INSTALL_COMPLETE", "run_id": self.run_id,
            "review_sha256": life.digest(self.review), "plan_sha256": _sha(plan_raw),
            "manifest_sha256": _sha(manifest_raw), "controller": actual_peer,
            "files_sha256": {name: _sha(raw) for name, raw in payloads.items()}})
        payloads["journal/installation-complete.json"] = completion
        for name, raw in payloads.items():
            _write_file(self._fds, name, raw, self.review["final_destinations"][name],
                        production=self.production, test_uid=self.owner_uid, test_gid=self.owner_gid)
        for fd in self._fds.values():
            os.fsync(fd)
        self._finalized = True
        receipt_info = os.fstat(self.receipt_fd)
        return {"status": "INSTALL_COMPLETE", "review_sha256": life.digest(self.review),
            "plan_sha256": _sha(plan_raw), "manifest_sha256": _sha(manifest_raw),
            "controller": actual_peer, "receipt_dev": receipt_info.st_dev,
            "receipt_ino": receipt_info.st_ino}

    def close(self):
        """Close retained descriptors while preserving all staged state."""
        for fd in (*self._fds.values(), self.run_fd, self.receipt_fd):
            try:
                os.close(fd)
            except OSError:
                pass
