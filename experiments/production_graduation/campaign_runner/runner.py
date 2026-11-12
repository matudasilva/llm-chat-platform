"""Serial campaign execution, with transport/evidence seams for P2 simulations."""
import argparse
import http.client
import io
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from .admission import NORMAL, R_MAX, charges, may_admit
from .evidence import Evidence, parse
from .ledger import Ledger, RunnerLock, canonical, digest, durable_directory
from .preflight import SOURCES, campaign_tenant, validate
from .states import State, transition


@dataclass(frozen=True)
class Completion:
    success: bool
    request_id: str


@dataclass(frozen=True)
class LogWindow:
    lines: list[str]
    complete: bool
    container_id: str


def utc():
    return datetime.now(timezone.utc).isoformat()


def request_uuid(campaign_id, entry):
    return str(uuid5(UUID(campaign_id), canonical(entry).decode()))


class Runner:
    def __init__(self, root, directory, campaign_id, manifest, pins, driver,
                 *, simulation=False, sleep=time.sleep, now=utc):
        self.root, self.directory = Path(root), Path(directory)
        self.campaign_id = str(UUID(campaign_id))
        self.manifest, self.pins, self.driver = manifest, pins, driver
        self.simulation, self.sleep, self.now = simulation, sleep, now
        self.state = State.INIT
        self.trace = [self.state]
        self.reason = None
        self.ledger = None
        self.recorded_campaign_state = None

    def move(self, target):
        self.state = transition(self.state, target)
        self.trace.append(self.state)

    def finish(self, state, reasons):
        self.reason = reasons
        if self.ledger and self.ledger.open_campaign == self.campaign_id:
            if state != State.COMPLETE:
                self.ledger.append(self.campaign_id, "STOP", reasons=reasons, state=state)
            self.ledger.append(self.campaign_id, "CAMPAIGN_CLOSED", state=state, reasons=reasons)
            self.recorded_campaign_state = state
        self.move(state)
        return self.state

    def recover(self):
        campaign = self.ledger.open_campaign
        for entry in self.ledger.pending:
            self.ledger.append(entry["campaign_id"], "REQUEST_SETTLED",
                               request_id=entry["payload"]["request_id"],
                               status="CRASH_RECOVERED", conservative_usd=str(R_MAX),
                               charges=charges(True), retry=False, evaluator=False,
                               reasons=["CRASH_RECOVERED"])
        self.ledger.append(campaign, "STOP", state=State.FAILED, reasons=["CRASH_RECOVERED"])
        self.ledger.append(campaign, "CAMPAIGN_CLOSED", state=State.FAILED,
                           reasons=["CRASH_RECOVERED"])
        self.recorded_campaign_state = State.FAILED
        self.reason = ["CRASH_RECOVERED"]
        self.move(State.FAILED)
        return self.state

    def run(self):
        self.move(State.PREFLIGHT)
        try:
            durable_directory(self.directory.resolve())
            with RunnerLock(self.directory / "runner.lock"):
                self.ledger = Ledger(self.directory / "ledger.jsonl")
                if self.ledger.open_campaign:
                    return self.recover()
                if any(e["campaign_id"] == self.campaign_id for e in self.ledger.entries):
                    return self.finish(State.FAILED, ["CAMPAIGN_ALREADY_RECORDED"])
                identities = validate(self.root, self.manifest, self.pins,
                                      simulation=self.simulation)
                recorder = getattr(self.driver, "measurements", None)
                if self.pins.get("client_measurements", {}).get("required") is True or recorder is not None:
                    if (recorder is None or recorder.campaign_id != self.campaign_id
                            or recorder.manifest_sha256 != self.pins["manifest_sha256"]):
                        raise ValueError("Missing or mismatched client measurement recorder")
                self.ledger.append(self.campaign_id, "CAMPAIGN_OPENED", **identities)
                self.move(State.READY)
                previous = None
                for entry in self.manifest["entries"]:
                    block = entry["block"]
                    if block != previous:
                        # This seam waits for operator restart; never restarts a container.
                        observed = self.driver.observe(block, previous)
                        validate(self.root, self.manifest, self.pins, simulation=self.simulation)
                        if observed != self.pins["blocks"][block]:
                            return self.finish(State.FAILED, ["BLOCK_PIN_MISMATCH"])
                        previous = block
                    if not may_admit(self.ledger.total):
                        return self.finish(State.INCOMPLETE_BUDGET, ["ADMISSION_CAP"])
                    rid = request_uuid(self.campaign_id, entry)
                    started = self.now()
                    self.ledger.append(self.campaign_id, "REQUEST_ADMITTED",
                                       request_id=rid, seq_in_manifest=entry["seq"],
                                       reserve=str(R_MAX), admission_utc=started, block=block)
                    self.move(State.IN_FLIGHT)
                    evidence = Evidence()
                    evidence_identity = None
                    status = "RESOLVED"
                    try:
                        barrier = self.driver.execute(entry, rid, deadline=300)
                        completed = self.now()
                        # Drain the completion grace before any new admission.
                        self.sleep(2)
                        window = self.driver.logs(started, completed, grace=2)
                        evidence_identity = {"container_id": window.container_id,
                                             "sha256": digest(window.lines),
                                             "complete": window.complete,
                                             "admission_utc": started, "completion_utc": completed,
                                             "grace_seconds": 2}
                        evidence = parse(window.lines, rid, complete=window.complete)
                        if window.container_id != self.pins["blocks"][block]["container_id"]:
                            evidence.reasons.append("LOG_SOURCE_CHANGED")
                        if not barrier.success or barrier.request_id != rid:
                            evidence.reasons.append("INVALID_COMPLETION_BARRIER")
                    except Exception as exc:
                        status = "UNRESOLVED"
                        evidence.reasons.append(f"UNRESOLVED_{type(exc).__name__}")
                    self.move(State.SETTLE)
                    stopping = bool(evidence.reasons or evidence.retry or evidence.evaluator)
                    reasons = [*evidence.reasons]
                    if evidence.retry:
                        reasons.append("S1_RETRY")
                    if evidence.evaluator:
                        reasons.append("S2_EVALUATOR")
                    self.ledger.append(self.campaign_id, "REQUEST_SETTLED", request_id=rid,
                                       status=status, conservative_usd=str(R_MAX if stopping else NORMAL),
                                       charges=charges(stopping), retry=evidence.retry,
                                       evaluator=evidence.evaluator, reasons=reasons,
                                       evidence_identity=evidence_identity)
                    if evidence.reasons:
                        return self.finish(State.FAILED, reasons)
                    if evidence.retry:
                        return self.finish(State.INCOMPLETE_STOP_RETRY, reasons)
                    if evidence.evaluator:
                        return self.finish(State.INCOMPLETE_STOP_EVALUATOR, reasons)
                    self.move(State.READY)
                return self.finish(State.COMPLETE, [])
        except (Exception, KeyboardInterrupt) as exc:
            # An economic write fault may leave an admitted request pending. Do not
            # risk another append; next startup verifies/recovers under the lock.
            self.reason = [*(self.reason or []), f"RUNNER_FAILURE_{type(exc).__name__}"]
            # Operational failure takes precedence even after durable closure.
            # Do not reopen/rewrite that receipt or write after a durability fault.
            if self.state != State.FAILED:
                self.state = State.FAILED
                self.trace.append(self.state)
            return self.state

    def output(self):
        return {"state": self.state.value, "reasons": self.reason,
                "settled_usd": str(self.ledger.total) if self.ledger else None,
                "recorded_campaign_state": self.recorded_campaign_state,
                "gates_measured": False}


class Deadline:
    def __init__(self, seconds):
        self.end = time.monotonic() + seconds

    def remaining(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Client deadline")
        return remaining


class DeadlineReader(io.RawIOBase):
    def __init__(self, raw, sock, deadline):
        self.raw, self.sock, self.deadline = raw, sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(self.deadline.remaining())
        size = self.raw.readinto(buffer)
        self.deadline.remaining()
        return size

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def sendall(self, data):
        self.sock.settimeout(self.deadline.remaining())
        self.sock.sendall(data)
        self.deadline.remaining()

    def makefile(self, mode, *args):
        self.deadline.remaining()
        raw = self.sock.makefile(mode, buffering=0)
        return io.BufferedReader(DeadlineReader(raw, self.sock, self.deadline))


class StrictHTTPResponse(http.client.HTTPResponse):
    """Require complete chunk framing instead of accepting premature trailer EOF."""

    def _read_next_chunk_size(self):
        line = self.fp.readline(http.client._MAXLINE + 1)
        if len(line) > http.client._MAXLINE:
            raise http.client.LineTooLong("chunk size")
        size = line[:-2].split(b";", 1)[0]
        if (not line.endswith(b"\r\n") or not size
                or any(c not in b"0123456789abcdefABCDEF" for c in size)):
            raise http.client.IncompleteRead(b"")
        return int(size, 16)

    def _read_and_discard_trailer(self):
        while True:
            line = self.fp.readline(http.client._MAXLINE + 1)
            if len(line) > http.client._MAXLINE:
                raise http.client.LineTooLong("trailer line")
            if not line.endswith(b"\r\n"):
                raise http.client.IncompleteRead(b"")
            if line == b"\r\n":
                return

    def _get_chunk_left(self):
        # The stdlib discards these two bytes without checking their value.
        # Validate once, then delegate size/trailer handling to HTTPResponse.
        if self.chunk_left == 0:
            if self._safe_read(2) != b"\r\n":
                raise http.client.IncompleteRead(b"")
            self.chunk_left = None
        return super()._get_chunk_left()


class LocalAPI:
    """HTTP to an operator-pinned loopback API; stdout via local Docker CLI."""
    def __init__(self, base_url, pins, *, operator=input, measurements=None):
        url = urlsplit(base_url)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1")
                or url.path not in ("", "/") or url.username or url.query or url.fragment):
            raise ValueError("API must be an isolated loopback HTTP endpoint")
        self.host, self.port = url.hostname, url.port or 80
        self.pins, self.operator = pins, operator
        self.container = None
        self.measurements = measurements
        if measurements is not None and measurements.manifest_sha256 != pins.get("manifest_sha256"):
            raise ValueError("Measurement manifest identity mismatch")
        if pins.get("client_measurements", {}).get("required") is True and measurements is None:
            raise ValueError("Required client measurements missing")

    def observe(self, block, previous):
        if previous is not None:
            if self.operator(f"Restart for {block}; type RESTARTED {block}: ") != f"RESTARTED {block}":
                raise ValueError("Operator abort")
        expected = self.pins["blocks"][block]
        self.container = expected["container_id"]
        image = subprocess.run(["docker", "inspect", "--format", "{{.Image}}", self.container],
                               capture_output=True, text=True, check=True).stdout.strip()
        keys = list(expected["config"])
        script = (
            "import json,os; from app.core.settings import settings; "
            f"keys={keys!r}; "
            "print(json.dumps({k:(os.environ.get('LOG_LEVEL','INFO') if k=='log_level' "
            "else getattr(settings,k)) for k in keys}))"
        )
        config = json.loads(subprocess.run(["docker", "exec", self.container, "python", "-c", script],
                                          capture_output=True, text=True, check=True).stdout)
        # Hash deployed source without importing providers or accessing secrets.
        hashes = subprocess.run(["docker", "exec", self.container, "sha256sum", *SOURCES],
                                capture_output=True, text=True, check=True).stdout.splitlines()
        observed_hashes = dict(line.split(maxsplit=1)[::-1] for line in hashes)
        if any(observed_hashes.get(path) != self.pins["files"][path] for path in SOURCES):
            raise ValueError("Deployed source identity changed")
        return {**expected, "image_id": image, "config": config}

    def execute(self, entry, request_id, *, deadline):
        from .measurements import RequestTiming
        timing = RequestTiming() if self.measurements is not None else None
        limit = Deadline(deadline)
        def complete(success, returned_id):
            if timing is not None:
                timing.mark("complete")
                self.measurements.record(entry, request_id, returned_id, success, timing)
                limit.remaining()
            return Completion(success, returned_id)
        # Loopback-only transport: avoid resolver/address fallback time outside
        # the socket deadline. localhost uses the explicit IPv4 loopback.
        host = "127.0.0.1" if self.host == "localhost" else self.host
        connection = http.client.HTTPConnection(host, self.port, timeout=limit.remaining())
        connection.response_class = StrictHTTPResponse
        connect = connection.connect

        def bounded_connect():
            connection.timeout = limit.remaining()
            connect()
            limit.remaining()
            connection.sock = DeadlineSocket(connection.sock, limit)

        connection.connect = bounded_connect
        try:
            connection.request("POST", "/chat", body=canonical(entry["payload"]), headers={
                "Content-Type": "application/json", "X-Request-ID": request_id,
                "X-Tenant-ID": campaign_tenant(entry),
            })
            response = None

            def remaining_timeout():
                remaining = limit.remaining()
                sock = connection.sock
                # HTTP/1.0 may detach the socket into the response after headers.
                if sock is None and response is not None:
                    sock = getattr(getattr(response.fp, "raw", None), "_sock", None)
                if sock:
                    sock.settimeout(remaining)
                return remaining

            remaining_timeout()
            response = connection.getresponse()
            limit.remaining()
            if timing is not None:
                timing.mark("headers")
            if response.status != 200:
                return complete(False, request_id)
            if not entry["payload"]["stream"]:
                chunks = []
                while not response.isclosed():
                    remaining_timeout()
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                if response.length not in (None, 0):
                    raise http.client.IncompleteRead(b"", response.length)
                body = json.loads(b"".join(chunks))
                limit.remaining()
                return complete(body.get("status") == "success", body.get("request_id", ""))
            event, data, terminal, buffer = None, [], None, b""
            while True:
                remaining_timeout()
                chunk = response.read1(65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    line = raw_line.decode().rstrip("\r")
                    if terminal is not None and line:
                        raise ValueError("SSE data after terminal event")
                    if not line:
                        if timing is not None and event is not None:
                            timing.mark("first_event")
                            if event == "token" and "\n".join(data):
                                timing.mark("first_content")
                            if event == "done":
                                timing.mark("done")
                        if event == "error":
                            return complete(False, request_id)
                        if event == "done":
                            terminal = json.loads("\n".join(data))
                            if not isinstance(terminal, dict):
                                raise ValueError("Invalid SSE terminal")
                        event, data = None, []
                    elif line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        data.append(line[6:])
            limit.remaining()
            if response.length not in (None, 0):
                raise http.client.IncompleteRead(b"", response.length)
            if buffer or event is not None or data:
                raise ValueError("Incomplete SSE fragment")
            return complete(bool(terminal and terminal.get("status") == "success"),
                              terminal.get("request_id", "") if terminal else "")
        finally:
            # Close after the barrier/error/deadline; never cancel an active
            # request merely because a stop signal appeared in stdout.
            connection.close()

    def logs(self, started, completed, *, grace):
        from datetime import timedelta
        until = (datetime.fromisoformat(completed) + timedelta(seconds=grace)).isoformat()
        result = subprocess.run(["docker", "logs", "--timestamps", "--since", started,
                                 "--until", until, self.container],
                                capture_output=True, text=True, check=True)
        if result.stderr:
            raise ValueError("Ambiguous container stderr window")
        return LogWindow(result.stdout.splitlines(), True, self.container)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--measurements", type=Path)
    args = parser.parse_args()
    try:
        manifest, pins = json.loads(args.manifest.read_text()), json.loads(args.pins.read_text())
        if args.measurements is None or pins.get("client_measurements", {}).get("required") is not True:
            raise ValueError("Paid client measurements must be pinned")
        from .measurements import MeasurementRecorder
        recorder = MeasurementRecorder(args.measurements, args.campaign_id, pins["manifest_sha256"])
        runner = Runner(args.root, args.directory, args.campaign_id, manifest, pins,
                        LocalAPI(args.api, pins, measurements=recorder))
        runner.run()
        output = runner.output()
    except (Exception, KeyboardInterrupt) as exc:
        output = {"state": State.FAILED.value, "reasons": [f"INPUT_FAILURE_{type(exc).__name__}"],
                  "settled_usd": None, "gates_measured": False}
    print(json.dumps(output, sort_keys=True))
    return 0 if output["state"] == State.COMPLETE.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
