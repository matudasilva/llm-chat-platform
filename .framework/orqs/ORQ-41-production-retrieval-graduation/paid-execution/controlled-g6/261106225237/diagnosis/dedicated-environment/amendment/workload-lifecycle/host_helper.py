#!/usr/bin/python3
"""Root-sealed lifecycle launcher. No installer, implicit approval or generic command."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

LEGACY_SHA = "8064e669e1921475167fb70fb73d3746cb4c034fa02fe207c7ffa749346b2be2"
NAMES = {"core.py", "host.py", "environment.py", "admin.py", "host_helper.py"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
                and info.st_nlink == 1, "Unsealed file")
        with os.fdopen(fd, "rb", closefd=False) as file:
            return file.read()
    finally:
        os.close(fd)


def load(state):
    require(os.geteuid() == 0 and not sys.flags.optimize, "Sealed root execution required")
    state = Path(state)
    require(state.parent == Path("/var/lib/orq41-cpuset") and re.fullmatch(r"[0-9]{12}", state.name),
            "Unknown lifecycle state")
    for parent in (*reversed(state.parents), state):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, "Unsealed ancestry")
    raw = read(state / "deployment.json")
    deployment = json.loads(raw)
    require(set(deployment) == {"schema", "files", "plan_sha256", "manifest_sha256", "source_review_sha256"}
            and deployment["schema"] == 1 and set(deployment["files"]) == NAMES,
            "Invalid deployment manifest")
    require(Path(__file__).resolve() == state / "host_helper.py", "Helper must run from sealed state")
    for name, expected in deployment["files"].items():
        require(hashlib.sha256(read(state / name)).hexdigest() == expected, "Sealed source changed")
    require(deployment["files"]["admin.py"] == LEGACY_SHA, "Unreviewed restoration primitive")
    require(hashlib.sha256(read(state / "plan.json")).hexdigest() == deployment["plan_sha256"]
            and hashlib.sha256(read(state / "journal/manifest.json")).hexdigest() == deployment["manifest_sha256"]
            and hashlib.sha256(read(state / "source-review.json")).hexdigest() == deployment["source_review_sha256"],
            "Sealed packet evidence changed")
    review = json.loads(read(state / "source-review.json"))
    require(review.get("status") == "WORKLOAD_LIFECYCLE_SOURCE_REVIEW_PASS"
            and not review.get("new_blocker_high_medium_findings"), "Source review is not PASS")
    source_names = {
        "core.py": "experiments/production_graduation/gate_validation/dedicated_lifecycle.py",
        "host.py": "experiments/production_graduation/gate_validation/dedicated_lifecycle_host.py",
        "environment.py": "experiments/production_graduation/gate_validation/dedicated_environment.py",
        "host_helper.py": ".framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/workload-lifecycle/host_helper.py"}
    require(all(review.get("technical_files_sha256", {}).get(name) == deployment["files"][alias]
                for alias, name in source_names.items()), "Source review does not bind deployed helpers")
    approval = json.loads(read(state / "execution-authorization.json"))
    require(set(approval) == {"status", "deployment_sha256", "run_id"}
            and approval["status"] in ("OPERATOR_AUTHORIZED_LOCAL_LIFECYCLE_DRILL",
                                       "OPERATOR_AUTHORIZED_DEDICATED_AA_EXECUTION")
            and approval["run_id"] == state.name
            and approval["deployment_sha256"] == hashlib.sha256(raw).hexdigest(),
            "Separate live execution authorization missing")
    # Only root-owned, hash-checked modules; never import executable repo code.
    package = types.ModuleType("orq41sealed");package.__path__ = []
    sys.modules[package.__name__] = package
    loaded = {}
    for name, file in (("dedicated_lifecycle", "core.py"), ("dedicated_environment", "environment.py"),
                       ("dedicated_lifecycle_host", "host.py"), ("legacy_admin", "admin.py")):
        spec = importlib.util.spec_from_file_location("orq41sealed." + name, state / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module;setattr(package, name, module)
        spec.loader.exec_module(module);loaded[name] = module
    # Supporting approval JSON is hash-validated by the read-only checker. It is
    # not executable code and cannot select arbitrary commands or source paths.
    env = loaded["dedicated_environment"]
    env.ROOT = Path("/home/matias/Cursor/llm-chat-platform")
    env.AMENDMENT = env.ROOT / (".framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/"
                              "controlled-g6/261106225237/diagnosis/dedicated-environment/amendment")
    return loaded, json.loads(read(state / "plan.json")), approval


def main(action, state):
    require(action in ("serve", "recover"), "Unknown fixed lifecycle action")
    state = Path(state)
    loaded, plan, approval = load(state)
    core, host = loaded["dedicated_lifecycle"], loaded["dedicated_lifecycle_host"]
    journal = core.Journal(state / "journal")
    manifest = core.validate_manifest(journal.manifest())
    require(manifest["run_id"] == state.name, "Lifecycle run mismatch")
    # Existing baseline/ownership evidence must be available to both paths.
    backend = None
    bridge = host.AdminBridge(loaded["legacy_admin"], state,
        lambda: backend.timer_armed())
    backend = host.HostBackend(manifest, plan, state, bridge)
    supervisor = core.Supervisor(journal, backend)
    core.sync_directory(state.parent)
    core.sync_directory(state)
    if action == "recover" or journal.has_history():
        return supervisor.recover()
    require(backend.run("/usr/bin/systemctl", "show", "-pMainPID", "--value",
                        "orq41-lifecycle-supervisor-" + state.name + ".service") == str(os.getpid()),
            "Supervisor must outlive the operator shell in its own systemd unit")
    public = Path("/run/orq41-lifecycle") / state.name
    if not public.parent.exists():
        public.parent.mkdir(mode=0o755)
    info = public.parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, "Untrusted public parent")
    public.mkdir(mode=0o750, exist_ok=False)
    core.sync_directory(public.parent)
    os.chown(public, 0, manifest["controller"]["gid"])
    def ready():
        os.chown(public / "admission.sock", 0, manifest["controller"]["gid"])
        workers = {}
        for cid, info in manifest["owned"].items():
            if info["role"] == "api":
                name = info["inspect"]["Name"].lstrip("/")
                key = name.removeprefix("orq41-blocked-" + manifest["run_id"] + "-")
                # Docker names lower-case the locale; public keys retain the plan's cell spelling.
                key = re.sub(r"-(en|es)-", lambda m: "-" + m.group(1).upper() + "-", key)
                workers[key] = cid
        descriptor = dict(run=manifest["run_id"], plan=core.digest(plan), boot=manifest["boot_id"],
                          server=core.process_peer(os.getpid(), os.geteuid(), os.getegid()), workers=workers,
                          start=supervisor.state()["start"], deadline=supervisor.state()["start"] + core.WINDOW)
        core.create_file(public / "server.json", core.encode(descriptor), 0o644)
    return core.serve(supervisor, public / "admission.sock", ready=ready)


if __name__ == "__main__":
    require(len(sys.argv) == 3, "Expected fixed action and sealed state")
    result = main(sys.argv[1], sys.argv[2])
    print(result)
    raise SystemExit(0 if result == "LIFECYCLE_PASS" else 1)
