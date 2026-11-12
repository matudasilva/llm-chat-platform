"""Explicitly invoked synthetic controller seam; no CLI, installer or service start.

Live use requires a separately sealed, reviewed caller and staging/execution
permissions. Tests exercise temporary pipes and injected inspection only.
"""
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import select
import stat
import struct
import subprocess
import sys
import time
import types

CORE_SHA = "9d8547bd60265c883ae46a1987776f6138f7c1a62dacb2f07dba26d8fc488545"
MAX_FRAME = 1024 * 1024
COMMAND_SECONDS = 5
PREPARATION_SECONDS = 300
UID = GID = 1000


def require(ok, message):
    if not ok:
        raise ValueError(message)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate frame field")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite frame")))
    require(encode(value) == raw, "Noncanonical frame")
    return value


def _transfer(fd, *, deadline, raw=None, size=None):
    """Bound every partial read/write by the same monotonic deadline."""
    result = bytearray()
    offset = 0
    while offset < (len(raw) if raw is not None else size):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Private controller channel deadline")
        readable, writable, _ = select.select([fd] if raw is None else [],
                                              [fd] if raw is not None else [], [], remaining)
        if not readable and not writable:
            raise TimeoutError("Private controller channel deadline")
        try:
            if raw is None:
                chunk = os.read(fd, min(size - offset, 65536))
                require(bool(chunk), "Private controller channel EOF")
                result.extend(chunk)
                offset += len(chunk)
            else:
                count = os.write(fd, raw[offset:offset + 65536])
                require(count > 0, "Private controller channel closed")
                offset += count
        except BlockingIOError:
            continue
    return bytes(result)


def send_frame(fd, value, deadline):
    raw = encode(value)
    require(0 < len(raw) <= MAX_FRAME, "Oversized controller frame")
    _transfer(fd, raw=struct.pack("!I", len(raw)) + raw, deadline=deadline)


def receive_frame(fd, deadline):
    length = struct.unpack("!I", _transfer(fd, size=4, deadline=deadline))[0]
    require(0 < length <= MAX_FRAME, "Oversized controller frame")
    return decode(_transfer(fd, size=length, deadline=deadline))


def verify_unprivileged(status):
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    require(fields.get("Uid", "").split() == [str(UID)] * 4
            and fields.get("Gid", "").split() == [str(GID)] * 4
            and not fields.get("Groups", "missing").split()
            and fields.get("NoNewPrivs", "").strip() == "1", "Controller privilege drop incomplete")
    for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        require(key in fields and int(fields[key], 16) == 0, "Controller retained capabilities")


def _drop_privileges():
    """Called only in the forked child of an explicitly authorized root launcher."""
    libc = ctypes.CDLL(None, use_errno=True)
    def prctl(option, arg=0):
        if libc.prctl(option, arg, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Controller privilege operation failed")
    last = int(Path("/proc/sys/kernel/cap_last_cap").read_text())
    require(0 <= last <= 63, "Unsupported capability layout")
    for capability in range(last + 1):
        prctl(24, capability)  # PR_CAPBSET_DROP; retain effective authority until setresuid.
    prctl(47, 4)  # PR_CAP_AMBIENT_CLEAR_ALL
    prctl(8, 0)  # PR_SET_KEEPCAPS
    class Header(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32),
                    ("inheritable", ctypes.c_uint32)]
    header, data = Header(0x20080522, 0), (Data * 2)()
    require(libc.capget(ctypes.byref(header), ctypes.byref(data)) == 0, "capget failed")
    for row in data:
        row.inheritable = 0
    require(libc.capset(ctypes.byref(header), ctypes.byref(data)) == 0, "capset failed")
    os.setgroups([])
    os.setresgid(GID, GID, GID)
    os.setresuid(UID, UID, UID)
    prctl(38, 1)  # PR_SET_NO_NEW_PRIVS
    verify_unprivileged(Path("/proc/self/status").read_text())
    require(os.getresuid() == (UID,) * 3 and os.getresgid() == (GID,) * 3
            and os.getgroups() == [], "Saved controller credentials differ")


def receipt_identity(fd):
    info = os.fstat(fd)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == UID and info.st_gid == GID
            and stat.S_IMODE(info.st_mode) == 0o700, "Untrusted receipt directory descriptor")
    return dict(dev=info.st_dev, ino=info.st_ino, uid=info.st_uid, gid=info.st_gid, mode=0o700)


def _module(name, raw):
    module = types.ModuleType(name)
    module.__file__ = "<sealed-" + name + ">"
    module.__package__ = name.rpartition(".")[0]
    sys.modules[name] = module
    try:
        exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def load_controller(core_raw, controller_raw, controller_sha256):
    """Never reopen a path while loading verified controller/core bytes."""
    require(digest(core_raw) == CORE_SHA and digest(controller_raw) == controller_sha256,
            "Controller source pin mismatch")
    core = _module("_orq41_launch_core", core_raw)
    controller = _module("_orq41_launch_controller", controller_raw)
    controller.life = core
    return core, controller


def _read_at(directory_fd, name):
    require(name in ("plan.json", "deployment.json", "execution-authorization.json",
                     "journal/manifest.json"), "Unknown sealed file")
    parent = directory_fd
    owned = None
    if name.startswith("journal/"):
        owned = os.open("journal", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
        parent, name = owned, "manifest.json"
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                    and not stat.S_IMODE(info.st_mode) & 0o077 and info.st_size <= MAX_FRAME,
                    "Unsealed controller input")
            chunks, size = [], 0
            while True:
                chunk = os.read(fd, min(65536, MAX_FRAME + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                require(size <= MAX_FRAME, "Sealed input exceeds limit")
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        if owned is not None:
            os.close(owned)


def _inspect_fixed(worker_id):
    """Fixed read-only command; no caller-controlled operation or argument vector."""
    require(isinstance(worker_id, str) and len(worker_id) == 64
            and all(c in "0123456789abcdef" for c in worker_id), "Invalid frozen worker")
    process = subprocess.Popen(
        ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "inspect", worker_id],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, close_fds=True,
    )
    deadline = time.monotonic() + COMMAND_SECONDS
    raw = bytearray()
    try:
        fd = process.stdout.fileno()
        os.set_blocking(fd, False)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], max(0, remaining))[0]:
                raise TimeoutError("Worker inspection deadline")
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw.extend(chunk)
            require(len(raw) <= MAX_FRAME, "Worker inspection exceeds limit")
        require(process.wait(timeout=max(.001, deadline-time.monotonic())) == 0,
                "Worker inspection failed")
        return json.loads(raw)
    finally:
        # Only reap our read-only docker CLI; never signal a container or service.
        if process.poll() is None:
            process.kill()
            process.wait(timeout=COMMAND_SECONDS)
        process.stdout.close()


def inspect_reply(request, worker_id, frozen_projection, host, *, inspect_fn=_inspect_fixed):
    require(request == {"op": "inspect"}, "Broker accepts only fixed worker inspection")
    values = inspect_fn(worker_id)
    require(type(values) is list and len(values) == 1
            and values[0].get("Id") == worker_id
            and host.projection(values[0]) == frozen_projection, "Frozen worker inspection drift")
    return host.read_state(values[0])


def _clean_child_fds(keep):
    null = os.open("/dev/null", os.O_RDWR)
    try:
        for fd in (0, 1, 2):
            os.dup2(null, fd)
    finally:
        if null > 2:
            os.close(null)
    for value in os.listdir("/proc/self/fd"):
        fd = int(value)
        if fd > 2 and fd not in keep:
            try:
                os.close(fd)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise
    os.environ.clear()
    os.chdir("/")
    os.umask(0o077)


def _child(receipt_fd, incoming, outgoing, source_bytes, controller_sha, expected_identity, deadline):
    _clean_child_fds({receipt_fd, incoming, outgoing})
    _drop_privileges()
    require(receipt_identity(receipt_fd) == expected_identity, "Receipt descriptor changed")
    core, controller = load_controller(source_bytes["synthetic/core.py"],
                                       source_bytes["synthetic/synthetic_controller.py"], controller_sha)
    peer = core.process_peer(os.getpid(), UID, GID)
    send_frame(outgoing, {"op": "ready", "peer": peer}, deadline)
    frame = receive_frame(incoming, deadline)
    require(set(frame) == {"op", "plan", "plan_sha256", "peer"} and frame["op"] == "sealed"
            and frame["peer"] == peer and core.digest(frame["plan"]) == frame["plan_sha256"],
            "Controller release binding differs")
    plan = frame["plan"]
    activation = receive_frame(incoming, deadline)
    require(activation == {"op": "execute", "plan_sha256": frame["plan_sha256"]},
            "Separate execution release missing")
    public = Path("/run/orq41-lifecycle") / plan["run_id"]
    while not (public / "server.json").exists():
        require(time.monotonic() < deadline, "Supervisor readiness exceeded preparation lease")
        time.sleep(.05)
    client = core.ControllerClient(plan)
    def inspect():
        command_deadline = min(client.descriptor["deadline"] + core.DRAIN + core.RESTORE + core.COMMAND,
                               time.monotonic() + COMMAND_SECONDS)
        send_frame(outgoing, {"op": "inspect"}, command_deadline)
        reply = receive_frame(incoming, command_deadline)
        require(set(reply) == {"running", "exit_code"}, "Invalid broker state")
        return reply
    result = controller.finish_after_worker_exit(client, plan["synthetic_worker_id"], inspect,
                                                "/proc/self/fd/" + str(receipt_fd))
    send_frame(outgoing, {"op": "done", "result": result}, time.monotonic() + COMMAND_SECONDS)


class ControllerHandle:
    """One-shot release/activation; any uncertain outcome consumes that operation."""
    def __init__(self, pid, incoming, outgoing, peer, deadline, handoff, host=None):
        self.pid, self.incoming, self.outgoing = pid, incoming, outgoing
        self.peer, self.deadline, self.handoff = peer, deadline, handoff
        self.host = host
        self.released = self.activated = False
        self.plan = self.manifest = self.deployment_raw = None

    def release(self, transaction):
        require(not self.released and not self.activated, "Controller already released")
        self.released = True
        require(transaction.handoff == self.handoff, "Foreign installation transaction")
        plan_raw = _read_at(transaction.run_fd, "plan.json")
        manifest_raw = _read_at(transaction.run_fd, "journal/manifest.json")
        deployment_raw = _read_at(transaction.run_fd, "deployment.json")
        plan, manifest, deployment = map(decode, (plan_raw, manifest_raw, deployment_raw))
        require(plan["run_id"] == self.handoff["run_id"] == manifest["run_id"]
                and manifest["controller"] == self.peer and manifest["plan_sha256"] == digest(plan_raw)
                and deployment["plan_sha256"] == digest(plan_raw)
                and deployment["manifest_sha256"] == digest(manifest_raw), "Sealed controller binding differs")
        require(_process_peer(self.pid) == self.peer, "Dormant controller identity changed")
        self.plan, self.manifest, self.deployment_raw = plan, manifest, deployment_raw
        send_frame(self.outgoing, {"op": "sealed", "plan": plan,
                                  "plan_sha256": digest(plan_raw), "peer": self.peer}, self.deadline)

    def serve(self, transaction):
        """No service starts: caller must separately arrange approved supervisor start."""
        require(self.released and not self.activated and transaction.handoff == self.handoff,
                "Controller not eligible for activation")
        self.activated = True
        approval = decode(_read_at(transaction.run_fd, "execution-authorization.json"))
        require(approval == dict(status="OPERATOR_AUTHORIZED_LOCAL_LIFECYCLE_DRILL",
                                 deployment_sha256=digest(self.deployment_raw), run_id=self.plan["run_id"]),
                "Separate deployment-bound execution authorization missing")
        require(_process_peer(self.pid) == self.peer and time.monotonic() < self.deadline,
                "Controller preparation lease expired")
        send_frame(self.outgoing, {"op": "execute", "plan_sha256": digest(encode(self.plan))}, self.deadline)
        worker = self.plan["synthetic_worker_id"]
        frozen = self.manifest["owned"][worker]["inspect"]
        end = time.monotonic() + 7200 + 390 + 60 + COMMAND_SECONDS
        while True:
            request = receive_frame(self.incoming, end)
            if isinstance(request, dict) and request.get("op") == "done":
                require(set(request) == {"op", "result"}, "Invalid completion frame")
                return self._completed(request["result"])
            reply = inspect_reply(request, worker, frozen, self.host)
            send_frame(self.outgoing, reply, min(end, time.monotonic() + COMMAND_SECONDS))

    def _completed(self, result):
        deadline = time.monotonic() + COMMAND_SECONDS
        while time.monotonic() < deadline:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                require(os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0,
                        "Controller did not exit successfully")
                return result
            time.sleep(.01)
        raise TimeoutError("Controller exit unresolved; no restart or signal")

    def close(self):
        """Closing pipes requests no container action; a dormant child observes EOF."""
        for name in ("incoming", "outgoing"):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)


def _process_peer(pid):
    status = Path(f"/proc/{pid}/status").read_text()
    verify_unprivileged(status)
    raw = Path(f"/proc/{pid}/stat").read_text()
    return dict(pid=pid, uid=UID, gid=GID, start=int(raw[raw.rfind(")") + 2:].split()[19]))


def start_controller(review, stage_authorization, transaction):
    """Explicit live boundary: never invoked in offline tests or by module import."""
    require(os.geteuid() == 0 and sys.flags.isolated and sys.dont_write_bytecode,
            "Sealed root launcher requires isolated Python -I -B")
    expected = dict(status="OPERATOR_AUTHORIZED_SYNTHETIC_STAGING", review_sha256=digest(encode(review)),
                    run_id=transaction.handoff["run_id"], dormant_controller=True)
    require(stage_authorization == expected
            and transaction.handoff["review_sha256"] == expected["review_sha256"],
            "Separate dormant-controller staging authorization missing")
    sources = dict(transaction.source_bytes)
    required = ("synthetic/core.py", "synthetic/synthetic_controller.py", "synthetic/synthetic_launch.py")
    for name in required:
        require(digest(sources[name]) == review["files"][name]["sha256"], "Presealed source differs")
    require(digest(sources["synthetic/core.py"]) == CORE_SHA
            and digest(Path(__file__).read_bytes()) == digest(sources["synthetic/synthetic_launch.py"]),
            "Launcher/core identity differs")
    identity = receipt_identity(transaction.receipt_fd)
    require(identity == transaction.handoff["receipt_identity"], "Foreign receipt descriptor")
    source_path = Path(__file__)
    expected_path = Path("/var/lib/orq41-cpuset") / expected["run_id"] / "synthetic/synthetic_launch.py"
    require(source_path == expected_path, "Launcher must execute from the sealed run")
    for path in (*reversed(source_path.parents), source_path):
        info = path.lstat()
        require(info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o022
                and (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                     if path == source_path else stat.S_ISDIR(info.st_mode)), "Unsealed launcher ancestry")
    # Load only already-read approved bytes for the broker's unchanged validators.
    for name in ("core.py", "host.py", "environment.py"):
        require(digest(sources[name]) == review["files"][name]["sha256"], "Broker source differs")
    require(digest(sources["core.py"]) == CORE_SHA, "Broker core differs")
    package = types.ModuleType("_orq41_broker")
    package.__path__ = []
    sys.modules[package.__name__] = package
    for module_name, source_name in (("dedicated_lifecycle", "core.py"),
                                     ("dedicated_environment", "environment.py"),
                                     ("dedicated_lifecycle_host", "host.py")):
        module = _module(package.__name__ + "." + module_name, sources[source_name])
        setattr(package, module_name, module)
    host = package.dedicated_lifecycle_host
    child_in, to_child = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
    from_child, child_out = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
    deadline = time.monotonic() + PREPARATION_SECONDS
    pid = os.fork()
    if pid == 0:
        try:
            _child(transaction.receipt_fd, child_in, child_out, sources,
                   review["files"]["synthetic/synthetic_controller.py"]["sha256"], identity, deadline)
        except BaseException:
            os._exit(1)
        os._exit(0)
    os.close(child_in)
    os.close(child_out)
    try:
        ready = receive_frame(from_child, min(deadline, time.monotonic() + COMMAND_SECONDS))
        peer = _process_peer(pid)
        require(ready == {"op": "ready", "peer": peer}, "Dormant controller handshake differs")
        return ControllerHandle(pid, from_child, to_child, peer, deadline, dict(transaction.handoff), host)
    except BaseException:
        os.close(from_child)
        os.close(to_child)
        # Child is bounded by EOF/preparation lease. Never replace an uncertain PID.
        raise
