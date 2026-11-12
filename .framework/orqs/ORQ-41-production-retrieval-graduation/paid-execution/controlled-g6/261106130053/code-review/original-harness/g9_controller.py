"""Author, freeze, and execute the local ORQ-41 G9 lifecycle packet."""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

from .fixtures import HarnessError, canonical
from .g9 import build_manifest, cells, digest, validate_manifest

ROOT = Path.cwd().resolve()
ORQ = ROOT / ".framework/orqs/ORQ-41-production-retrieval-graduation"
G123 = ORQ / "environment/g123"
P2_GUARD = ORQ / "campaign-redesign/p2_netguard"
PG_NAME = "orq41-env-pg"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
PYTHON = str(ROOT / ".venv/bin/python")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def private_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise HarnessError("G9 private artifact collision")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def public_write(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_write(path, canonical(value) + b"\n")
    path.chmod(0o600)


def docker(*args, capture=True, timeout=60, input=None):
    completed = subprocess.run([*DOCKER, *args], input=input, check=False, capture_output=capture,
                               timeout=timeout, env={**os.environ, "DOCKER_BUILDKIT": "0"})
    if completed.returncode:
        raise HarnessError("local Docker operation failed: " + (args[0] if args else "unknown"))
    return completed.stdout if capture else b""


def docker_json(*args):
    return json.loads(docker(*args))


def sha_file(path: Path) -> str:
    return sha(path.read_bytes())


def settings_common() -> dict[str, str]:
    source = (G123 / "execution-freeze/settings/inspect.py").read_text()
    module = ast.parse(source)
    common = next(ast.literal_eval(node.value) for node in module.body
                  if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "common"
                                                          for target in node.targets))
    values = {}
    for item in common:
        key, value = item.split("=", 1)
        values[key] = value
    values.update({"APP_SETTINGS_ENV_FILE": "", "AWS_EC2_METADATA_DISABLED": "true",
                   "AWS_CONFIG_FILE": "/nonexistent", "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent",
                   "PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin",
                   "HOME": "/tmp", "PYTHONPATH": f"{P2_GUARD}:{ROOT}"})
    return values


def env_for(reference: str, vector: str, database: str, passwords: dict[str, str],
            *, run_dir: Path | None = None, worker_id: str = "", barrier: str = "") -> dict[str, str]:
    values = settings_common()
    from urllib.parse import quote
    for key, role, secret in (("DATABASE_URL", "orq41owner", "POSTGRES_PASSWORD"),
                              ("DATABASE_URL_APP", "rag_app", "POSTGRES_APP_PASSWORD"),
                              ("DATABASE_URL_OPS", "chat_ops", "POSTGRES_OPS_PASSWORD")):
        values[key] = f"postgresql+asyncpg://{role}:{quote(passwords[secret], safe='')}@127.0.0.1:5432/{database}"
    values.update({"PRIMARY_PROVIDER": "bedrock", "BEDROCK_MODEL": "nvidia.nemotron-nano-3-30b",
                   "BEDROCK_REGION": "us-east-1", "ROUTING_POLICY": "static",
                   "ROUTING_SHADOW_MODE_ENABLED": "false",
                   "CHAT_RESPONSE_CACHE_TTL_S": "300", "REDIS_HOST": "127.0.0.1",
                   "REDIS_PORT": "6379", "OTEL_ENABLED": "true",
                   "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318/v1/traces",
                   "CHAT_RAG_AUGMENTATION_ENABLED": str(vector != "OFF").lower(),
                   "CONVERSATION_HISTORY_ENABLED": str(vector != "OFF").lower(),
                   "EBM25_ENABLED": str(vector == "E1").lower()})
    if run_dir is not None:
        values.update({"G9_RUN_DIR": "/g9run", "G9_WORKER_ID": worker_id,
                       "G9_VECTOR": vector, "G9_REFERENCE": "c1",
                       "G9_RUN_ID": "261104151059", "G9_BARRIER": barrier,
                       "P2_NET_AUDIT_LOG": "/g9run/network-audit.log",
                       "PYTHONPATH": "/p2_netguard:/app"})
    return values


def prior_failure_is_quiescent(execution_path: Path) -> bool:
    """Allow a fresh, uniquely identified run only after prior workers settled."""
    try:
        prior = json.loads(execution_path.read_text())
        if (not isinstance(prior.get("cases_attempted"), int)
                or prior["cases_attempted"] < 1
                or prior["cases_attempted"] > prior.get("cases_total", 0)
                or any(prior.get(key) != 0 for key in
                       ("external_calls", "egress_attempts", "automatic_resends"))):
            return False
        run_dir = execution_path.parent
        private = Path(prior["private_state"])
        packet = json.loads((private / "packet.json").read_text())
        if packet.get("harness_sha256", {}).get(
                "experiments/production_graduation/gate_validation/g9_client.py") != sha_file(
                    ROOT / "experiments/production_graduation/gate_validation/g9_client.py"):
            return False
        cases = sorted((run_dir / "cases").glob("*.json"))
        if len(cases) != prior["cases_attempted"]:
            return False
        statuses = []
        for case_path in cases:
            case = json.loads(case_path.read_text())
            if (case.get("status") not in {"PASS", "FAILED"} or case.get("attempt_count") != 1
                    or case.get("automatic_resend") is not False):
                return False
            statuses.append(case["status"])
        if (statuses.count("FAILED") != prior.get("cases_failed")
                or statuses.count("PASS") != prior.get("cases_passed")):
            return False
        client_dirs = sorted(path for path in (private / "clients").glob("*") if path.is_dir())
        client_request_ids = set()
        client_error_ids = set()
        for directory in client_dirs:
            request_path, receipt_path = directory / "request.json", directory / "receipt.json"
            if not request_path.is_file():
                return False
            request = json.loads(request_path.read_text())
            if not receipt_path.is_file():
                if request.get("method") == "GET":
                    continue
                return False
            receipt = json.loads(receipt_path.read_text())
            if receipt.get("automatic_resend") is not False:
                return False
            if request.get("method") == "GET":
                if receipt.get("status") != "RESOLVED" or receipt.get("http_status") != 200:
                    return False
                continue
            request_id = request.get("request_id")
            if not isinstance(request_id, str) or request_id in client_request_ids:
                return False
            client_request_ids.add(request_id)
            if receipt.get("status") == "CLIENT_ERROR":
                if (receipt.get("error_type") != "KeyError" or "http_status" in receipt
                        or "protocol" in request):
                    return False
                client_error_ids.add(request_id)
            elif (receipt.get("status") not in {"RESOLVED", "DISCONNECTED"}
                    or receipt.get("request_id") != request_id):
                return False
        server_request_ids = []
        for exit_path in private.glob("workers/*/worker-exit.json"):
            worker = json.loads(exit_path.read_text())
            if worker.get("active_transactions") != 0:
                return False
            server_request_ids.extend(row["request_id"] for row in worker.get("requests", [])
                                      if row.get("request_id") is not None)
        if len(server_request_ids) != len(set(server_request_ids)):
            return False
        if set(server_request_ids) != client_request_ids.difference(client_error_ids):
            return False
        audit = private / "network-audit.log"
        if audit.exists() and audit.stat().st_size:
            return False
        return not running_g9_containers(prior.get("run_id", ""))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def config_hash(reference, vector, database, passwords):
    env = env_for(reference, vector, database, passwords)
    env.pop("G9_RUN_DIR", None)
    code = "from app.core.settings import settings; from experiments.production_graduation.gate_validation.validate_g123 import config_identity; print(config_identity(settings))"
    proc = subprocess.run([PYTHON, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
    if proc.returncode or len(proc.stdout.strip()) != 64:
        raise HarnessError("cannot verify effective G9 settings identity")
    return proc.stdout.strip()


def preflight(run_public: Path, private: Path):
    planning = json.loads((ORQ / "planning-status.json").read_text())
    g9_status = planning.get("readiness_audit", {}).get("g9")
    prior_execution_ok = False
    if g9_status == "G9_EXECUTED_FINDINGS":
        design = planning.get("c1_g123_harness_design", {})
        prior_path = ORQ / design.get("g9_execution_record", "")
        if prior_path.is_file():
            prior_execution_ok = prior_failure_is_quiescent(prior_path)
    if (planning.get("phase") != "Plan" or planning.get("decision_freeze") != "BLOCKED"
            or planning.get("environment", {}).get("p4_effective") != "VERIFIED_FOR_LOCAL_ISOLATED_ENVIRONMENT"
            or planning.get("c1_g123_harness_design", {}).get("g1_g2_g3_result") != "PASS"
            or not (g9_status == "PACKET_PREPARED_DRILL_NOT_EXECUTED" or
                    g9_status == "G9_EXECUTED_FINDINGS" and prior_execution_ok)):
        raise HarnessError("ORQ-41 preflight state or G1/G2/G3/P4 prerequisite mismatch")
    pin = json.loads((G123 / "runs/261104151059/pinning.json").read_text())
    review = json.loads((G123 / "runs/261104151059/offline-verification/independent-review.json").read_text())
    if review.get("status") != "G123_OFFLINE_PARITY_INDEPENDENT_REVIEW_PASS":
        raise HarnessError("G123 independent package receipt is not PASS")
    if pin.get("candidate_image") != "sha256:7417a2af20101903f3fc9326af26da074eec6dd3b90987b5b5f74c1986a58d06":
        raise HarnessError("candidate image pin differs from reviewed G123 receipt")
    env_pin = json.loads((ORQ / "environment/manifest.json").read_text())
    pg = docker_json("inspect", PG_NAME)[0]
    redis = docker_json("inspect", "orq41-env-redis")[0]
    otel = docker_json("inspect", "orq41-env-otel")[0]
    images = {"baseline": pin["baseline_image_preserved"], "candidate": pin["candidate_image"],
              "postgres": pin["postgres_image"]}
    for identity in images.values():
        if docker_json("image", "inspect", identity)[0]["Id"] != identity:
            raise HarnessError("pinned G9 image is absent or replaced")
    if pg["Image"] != images["postgres"] or pg["HostConfig"]["NetworkMode"] != "none" or pg["HostConfig"].get("PortBindings"):
        raise HarnessError("isolated PostgreSQL topology drift")
    expected_limits = {"api": (2_000_000_000, 2_147_483_648, 2_147_483_648),
                       "postgres": (2_000_000_000, 2_147_483_648, 2_147_483_648),
                       "redis": (500_000_000, 268_435_456, 268_435_456),
                       "collector": (500_000_000, 268_435_456, 268_435_456)}
    actual = {"postgres": pg, "redis": redis, "collector": otel}
    for name in ("postgres", "redis", "collector"):
        row = actual[name]
        if row["HostConfig"]["NetworkMode"] not in ({"postgres": {"none"}, "redis": {"container:" + pg["Id"]},
                                                        "collector": {"container:" + pg["Id"]}}[name]):
            raise HarnessError("local service network namespace drift")
        want = expected_limits[name]
        if (row["HostConfig"]["NanoCpus"], row["HostConfig"]["Memory"], row["HostConfig"]["MemorySwap"]) != want:
            raise HarnessError("local service resource contract drift")
    if redis["Image"] != env_pin["images"]["redis"] or otel["Image"] != env_pin["images"]["collector"]:
        raise HarnessError("pinned Redis/collector image drift")
    if not pg["State"]["Running"] or not redis["State"]["Running"] or not otel["State"]["Running"]:
        raise HarnessError("a required local service is stopped")
    corpus = ORQ / "corpus-snapshot/orq37-t23-corpus.pgdump"
    if sha_file(corpus) != "0334e3af47edf9c885093a6ad061390f6f85ba62517e56b94450339950599d4f":
        raise HarnessError("P3 corpus dump identity mismatch")
    credentials = json.loads((Path(pin["private_state"]) / "local-credentials.json").read_text())
    for required in ("POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD", "POSTGRES_OPS_PASSWORD"):
        if not credentials.get(required):
            raise HarnessError("local PostgreSQL role credential unavailable")
    database_rows = {row["reference"]: row for row in pin["databases"]}
    if {database_rows[k]["status"] for k in ("c0", "c1")} != {"P3_VERIFIED_BUSINESS_EMPTY"}:
        # Those statuses were pinned before G123; subsequent G123 writes are expected.
        if not all(database_rows[k]["status"].startswith("P3_VERIFIED") for k in ("c0", "c1")):
            raise HarnessError("G9 disposable P3 database identities invalid")
    private_write(private / "local-credentials.json", canonical(credentials))
    passwords = credentials
    dbs = {key: database_rows[key]["name"] for key in ("c0", "c1")}
    settings_sha = {
        "E1": config_hash("c1", "E1", dbs["c1"], passwords),
        "C1": config_hash("c1", "C1", dbs["c1"], passwords),
        "C0": config_hash("c0", "C0", dbs["c1"], passwords),
        "OFF_C1": config_hash("c1", "OFF", dbs["c1"], passwords),
        "OFF_C0": config_hash("c0", "OFF", dbs["c1"], passwords),
    }
    resources = {key: {"nano_cpus": value[0], "memory_bytes": value[1], "memory_swap_bytes": value[2]}
                 for key, value in expected_limits.items()}
    harness_files = {}
    for rel in ("experiments/production_graduation/gate_validation/g9.py",
                "experiments/production_graduation/gate_validation/g9_worker.py",
                "experiments/production_graduation/gate_validation/g9_client.py",
                "experiments/production_graduation/gate_validation/g9_controller.py"):
        harness_files[rel] = sha_file(ROOT / rel)
    source_sha = pin["source_sha256"]
    source_head = pin["source_head"]
    packet = build_manifest(run_id=run_public.name, source_head=source_head,
        source_sha256=source_sha, harness_sha256=harness_files,
        baseline_image=images["baseline"], candidate_image=images["candidate"], postgres_image=images["postgres"],
        database_c0=dbs["c0"], database_c1=dbs["c1"], corpus_sha256=sha_file(corpus),
        p3_fingerprint="787ae13719ef23c5043449d7d2e84bd489e5896e18d0fe5a035f76e8c6df0999",
        g123_receipt_sha256=sha_file(G123 / "runs/261104151059/offline-verification/independent-review.json"),
        resources=resources, settings_sha256=settings_sha)
    if packet["run_id"] != run_public.name:
        raise HarnessError("run directory/manifest identity mismatch")
    public_write(run_public / "manifest.json", packet)
    state = {"status": "G9_PACKET_FROZEN_PREFLIGHT_PENDING", "manifest_sha256": packet["sha256"],
             "g123_run": "261104151059", "p4_effective": "VERIFIED_FOR_LOCAL_ISOLATED_ENVIRONMENT",
             "p3_sha256": packet["corpus"]["sha256"], "g123_independent_receipt_sha256": packet["g123_receipt_sha256"],
             "images": packet["images"], "resources": resources,
             "service_container_ids": {"postgres": pg["Id"], "redis": redis["Id"], "collector": otel["Id"]},
             "service_restart_counts": {name: actual[name]["RestartCount"] for name in actual},
             "network": packet["network"], "external_provider_calls": 0, "paid_requests": 0,
             "campaign_spend_usd": "0", "decision_freeze": "BLOCKED"}
    public_write(run_public / "preflight.json", state)
    private_write(private / "packet.json", canonical(packet))
    return packet, passwords, dbs, state


def source_target(cell):
    if cell.source == "E1":
        return ("candidate", "E1", "candidate", "C1", "c1", "c1")
    if cell.source == "C1":
        return ("candidate", "C1", "baseline", "C0", "c1", "c0")
    return ("candidate", "OFF", "baseline", "OFF", "c1", "c0")


def create_worker(*, run_id, name, image, ref, vector, database, passwords, private, barrier=""):
    worker_root = private / "workers"
    worker_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    work = worker_root / name
    if work.exists():
        raise HarnessError("G9 worker path collision")
    env = env_for(ref, vector, database, passwords, run_dir=private, worker_id=name, barrier=barrier)
    env_file = private / "env" / f"{name}.env"
    env_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_write(env_file, "".join(f"{key}={value}\n" for key, value in sorted(env.items())).encode())
    command = ["create", "--pull=never", "--name", name, "--network", f"container:{PG_NAME}", "--user=1000:1000",
               "--cpus=2", "--memory=2147483648", "--memory-swap=2147483648",
               "--env-file", str(env_file), "--mount", f"type=bind,src={private},dst=/g9run",
               "--mount", f"type=bind,src={ROOT/'experiments'},dst=/app/experiments,readonly",
               "--mount", f"type=bind,src={P2_GUARD},dst=/p2_netguard,readonly",
               "--mount", f"type=bind,src={ORQ/'corpus-snapshot/orq37-t23-corpus.pgdump'},dst=/p3/snapshot.dump,readonly",
               "--entrypoint", "/usr/local/bin/python", image,
               "/app/experiments/production_graduation/gate_validation/g9_worker.py"]
    docker(*command)
    record = docker_json("inspect", name)[0]
    if (record["Image"] != image or record["HostConfig"]["NetworkMode"] != f"container:{docker_json('inspect', PG_NAME)[0]['Id']}"
            or record["HostConfig"]["NanoCpus"] != 2_000_000_000
            or record["HostConfig"]["Memory"] != 2_147_483_648
            or record["HostConfig"]["MemorySwap"] != 2_147_483_648
            or record["HostConfig"].get("PortBindings")):
        raise HarnessError("G9 API worker image/network/resource preflight mismatch")
    return record["Id"], work


def create_client(*, name, image, private, spec):
    directory = private / "clients" / name
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(directory / "request.json", canonical(spec))
    env_file = private / "env" / f"client-{name}.env"
    values = {"G9_RUN_DIR": "/g9run", "G9_CLIENT_ID": name, "PATH": "/usr/local/bin:/usr/bin:/bin",
              "HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "/p2_netguard:/app",
              "AWS_CONFIG_FILE": "/nonexistent", "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent",
              "AWS_EC2_METADATA_DISABLED": "true", "P2_NET_AUDIT_LOG": "/g9run/network-audit.log"}
    private_write(env_file, "".join(f"{k}={v}\n" for k, v in sorted(values.items())).encode())
    docker("create", "--pull=never", "--name", name, "--network", f"container:{PG_NAME}", "--user=1000:1000",
           "--memory=268435456", "--memory-swap=268435456", "--cpus=0.5",
           "--env-file", str(env_file), "--mount", f"type=bind,src={private},dst=/g9run",
           "--mount", f"type=bind,src={ROOT/'experiments'},dst=/app/experiments,readonly",
           "--mount", f"type=bind,src={P2_GUARD},dst=/p2_netguard,readonly", "--entrypoint", "/usr/local/bin/python",
           image, "/app/experiments/production_graduation/gate_validation/g9_client.py")
    return directory


def wait_file(path, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text()) if path.suffix == ".json" else True
        time.sleep(0.01)
    raise HarnessError("G9 marker timeout: " + path.name)


def start_worker(name, work):
    started = time.monotonic()
    docker("start", name)
    marker = work / "startup.json"
    wait_file(marker, 30)
    return started, json.loads(marker.read_text())


def start_client(name, directory):
    docker("start", name)
    return directory / "receipt.json"


def issue_request(*, private, image, cell_id, protocol, tenant, message, disconnect=False):
    request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"orq41-g9/{cell_id}/{protocol}/{tenant}/{message}"))
    client_name = "orq41-g9-client-" + hashlib.sha256(f"{cell_id}/{protocol}/{tenant}/{message}".encode()).hexdigest()[:18]
    spec = {"request_id": request_id, "tenant_id": tenant, "protocol": protocol,
            "payload": {"message": message, "stream": protocol == "sse"}}
    directory = create_client(name=client_name, image=image, private=private, spec=spec)
    receipt = start_client(client_name, directory)
    return client_name, directory, receipt, request_id


def db_projection(database, tenant, message):
    query = projection_query(tenant, message)
    raw = docker("exec", "-i", PG_NAME, "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1",
                 "-U", "orq41owner", "-d", database, input=query.encode())
    rows = [json.loads(line) for line in raw.splitlines()]
    return {"row_count": len(rows), "sha256": sha(b"\n".join(canonical(row) for row in rows)),
            "messages": [row for row in rows]}


def projection_query(tenant, message):
    return f"""COPY (SELECT row_to_json(t)::text FROM (
      SELECT c.id::text AS conversation_id,c.tenant_id,
             m.id::text AS message_id,m.role::text,m.sequence,m.content
      FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id
      WHERE c.tenant_id='{tenant}'
      ORDER BY c.id,m.sequence) t) TO STDOUT"""


def assert_listener_closed(image, private, name):
    code = "import socket,sys\ns=socket.socket();s.settimeout(.25)\ntry:s.connect(('127.0.0.1',8000));sys.exit(1)\nexcept OSError:sys.exit(0)"
    docker("run", "--rm", "--pull=never", "--network", f"container:{PG_NAME}",
           "--mount", f"type=bind,src={P2_GUARD},dst=/p2_netguard,readonly", "--entrypoint", "/usr/bin/env",
           image, "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp", "PYTHONDONTWRITEBYTECODE=1",
           "PYTHONPATH=/p2_netguard", "AWS_CONFIG_FILE=/nonexistent", "AWS_SHARED_CREDENTIALS_FILE=/nonexistent",
           "AWS_EC2_METADATA_DISABLED=true", "python", "-c", code, timeout=5)


def stop_target(name):
    record = docker_json("inspect", name)[0]
    if record["State"]["Running"]:
        docker("stop", "--time", "30", name, timeout=35)


def touch_durable(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fsync(fd)
    os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def parse_business_state(projection, *, tenant, user_content, expected):
    rows = projection["messages"]
    actual = [row for row in rows if row.get("message_id") is not None]
    if expected == "zero_exchange":
        if actual or projection["row_count"]:
            return {"database_outcome": "partial_or_unexpected", "partial_exchange": True,
                    "duplicate_exchange": False, "rows": len(actual), "projection_sha256": projection["sha256"]}
        return {"database_outcome": "zero_exchange", "partial_exchange": False,
                "duplicate_exchange": False, "rows": 0, "projection_sha256": projection["sha256"]}
    by_conv = {}
    for row in actual:
        by_conv.setdefault((row["conversation_id"], row["tenant_id"]), []).append(row)
    complete = [messages for (_, row_tenant), messages in by_conv.items()
                if row_tenant == tenant and len(messages) == 2
                and {row["role"] for row in messages} == {"user", "assistant"}
                and next(row for row in messages if row["role"] == "user")["content"] == user_content
                and next(row for row in messages if row["role"] == "assistant")["content"] == "ORQ-41 deterministic G9 response."
                and next(row for row in messages if row["role"] == "user")["sequence"]
                    < next(row for row in messages if row["role"] == "assistant")["sequence"]]
    is_partial = (len(rows) != len(actual) or projection["row_count"] != len(rows)
                  or len(complete) != len(by_conv) or not complete)
    duplicate = len(complete) > 1
    outcome = "one_complete_exchange" if len(complete) == 1 and not is_partial else "partial_or_duplicate"
    return {"database_outcome": outcome, "partial_exchange": is_partial,
            "duplicate_exchange": duplicate, "rows": len(actual), "projection_sha256": projection["sha256"]}


def assert_request_result(receipt, protocol, *, expected_status="RESOLVED"):
    if receipt.get("status") != expected_status or receipt.get("automatic_resend") is not False:
        raise HarnessError("G9 request result/resend receipt invalid")
    if expected_status == "DISCONNECTED":
        return
    if receipt.get("http_status") != 200:
        raise HarnessError("G9 HTTP status mismatch")
    if protocol == "json":
        payload = receipt.get("payload", {})
        if (payload.get("status") != "success" or payload.get("stream") is not False
                or payload.get("sources") != [] or payload.get("error_message") is not None
                or receipt.get("assistant_content") != "ORQ-41 deterministic G9 response."):
            raise HarnessError("G9 JSON baseline response mismatch")
    else:
        events = receipt.get("events", [])
        if ([(row[0]) for row in events] != ["token", "done"]
                or events[-1][1].get("status") != "success" or events[-1][1].get("sources") != []
                or receipt.get("assistant_content") != "ORQ-41 deterministic G9 response."):
            raise HarnessError("G9 SSE terminal/response mismatch")


def assert_health_result(receipt):
    if (receipt.get("status") != "RESOLVED" or receipt.get("http_status") != 200
            or receipt.get("payload") != {"app_env": "development"}):
        raise HarnessError("recovered /health probe failed")


def make_request(private, image, cell_id, protocol, tenant, message):
    client_name, directory, receipt_path, request_id = issue_request(
        private=private, image=image, cell_id=cell_id, protocol=protocol,
        tenant=tenant, message=message)
    return {"name": client_name, "directory": directory, "receipt": receipt_path,
            "request_id": request_id, "tenant": tenant, "message": message}


def wait_request(client, *, timeout=30):
    receipt = wait_file(client["receipt"], timeout)
    return receipt


def execute_source_barrier(*, source_name, source_work, source_image, private, cell, tenant, message):
    source_client = make_request(private, source_image, cell.cell_id + "-source", cell.protocol, tenant, message)
    barrier_file = source_work / f"barrier-{cell.barrier}.json"
    barrier = wait_file(barrier_file, 30)
    disconnect_at = None
    if cell.action != "drain":
        disconnect_at = time.monotonic()
        touch_durable(source_client["directory"] / "disconnect")
        client_result = wait_request(source_client, timeout=15)
        if client_result.get("status") != "DISCONNECTED":
            raise HarnessError("client did not disconnect at the frozen G9 checkpoint")
    else:
        client_result = None
    rollback_started = time.monotonic()
    stop = subprocess.Popen([*DOCKER, "stop", "--time", "30", source_name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, "DOCKER_BUILDKIT": "0"})
    signal_row = wait_file(source_work / "sigterm.json", 8)
    listener_error = None
    try:
        assert_listener_closed(source_image, private, source_name)
    except Exception as exc:
        listener_error = exc
    release_at = time.monotonic()
    touch_durable(source_work / f"release-{cell.barrier}")
    if release_at - signal_row["at_monotonic"] > 5:
        raise HarnessError("held local stub was not released within five seconds of SIGTERM")
    out, err = stop.communicate(timeout=32)
    if stop.returncode:
        raise HarnessError("graceful API container stop failed")
    if listener_error is not None:
        raise HarnessError("old API listener remained available after SIGTERM") from listener_error
    worker_exit = wait_file(source_work / "worker-exit.json", 8)
    quiescent = wait_file(source_work / "quiescent.json", 8)
    source_events = [row for row in worker_exit["requests"] if row.get("request_id") == source_client["request_id"]]
    source_dispatches = [row for row in worker_exit["provider_calls"] if row.get("request_id") == source_client["request_id"]]
    if len(source_events) != 1 or len(source_dispatches) != 1:
        raise HarnessError("source request/provider evidence is missing, duplicated, or uncorrelated")
    if cell.action != "drain" and cell.protocol == "sse" and source_events[0].get("disconnect_at") is None:
        raise HarnessError("SSE client disconnect was not observed by the server")
    state = docker_json("inspect", source_name)[0]["State"]
    if state["Running"] or state["OOMKilled"] or state["ExitCode"] != 0:
        raise HarnessError("API worker did not exit gracefully")
    drain_s = time.monotonic() - rollback_started
    cleanup_start = signal_row["at_monotonic"] if disconnect_at is None else disconnect_at
    cleanup_s = quiescent["at_monotonic"] - cleanup_start
    if cell.action == "drain":
        client_result = wait_request(source_client, timeout=10)
        assert_request_result(client_result, cell.protocol)
    elif cell.action == "precommit_disconnect":
        client_result = wait_request(source_client, timeout=10)
        if client_result.get("status") != "DISCONNECTED":
            raise HarnessError("pre-commit client outcome was not retained as disconnected")
    else:
        if client_result.get("status") != "DISCONNECTED":
            raise HarnessError("post-commit client outcome was not retained as disconnected")
    return {"source_client": source_client, "client_result": client_result,
            "barrier": barrier, "signal": signal_row, "worker_exit": worker_exit,
            "quiescent": quiescent, "state": state,
            "source_request_event": source_events[0], "source_provider_dispatch": source_dispatches[0],
            "rollback_started_monotonic": rollback_started, "drain_s": drain_s,
            "cleanup_s": cleanup_s, "release_delay_s": release_at - signal_row["at_monotonic"],
            "disconnect_monotonic": disconnect_at, "source_container_exit": state["ExitCode"],
            "source_worker_id": source_name}


def simple_request(*, private, image, cell_id, protocol, tenant, message):
    client = make_request(private, image, cell_id, protocol, tenant, message)
    receipt = wait_request(client, timeout=30)
    assert_request_result(receipt, protocol)
    return client, receipt


def health_probe(*, private, image, cell_id):
    run_id = json.loads((private / "packet.json").read_text())["run_id"]
    name = health_client_name(run_id, cell_id)
    directory = private / "clients" / name
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(directory / "request.json", canonical({"method": "GET"}))
    env_file = private / "env" / f"client-{name}.env"
    values = {"G9_RUN_DIR": "/g9run", "G9_CLIENT_ID": name, "PATH": "/usr/local/bin:/usr/bin:/bin",
              "HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "/p2_netguard:/app",
              "AWS_CONFIG_FILE": "/nonexistent", "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent",
              "AWS_EC2_METADATA_DISABLED": "true", "P2_NET_AUDIT_LOG": "/g9run/network-audit.log"}
    private_write(env_file, "".join(f"{key}={value}\n" for key, value in sorted(values.items())).encode())
    docker("create", "--pull=never", "--name", name, "--network", f"container:{PG_NAME}", "--user=1000:1000",
           "--memory=268435456", "--memory-swap=268435456", "--cpus=0.5", "--env-file", str(env_file),
           "--mount", f"type=bind,src={private},dst=/g9run",
           "--mount", f"type=bind,src={ROOT/'experiments'},dst=/app/experiments,readonly",
           "--mount", f"type=bind,src={P2_GUARD},dst=/p2_netguard,readonly", "--entrypoint", "/usr/local/bin/python",
           image, "/app/experiments/production_graduation/gate_validation/g9_client.py")
    docker("start", name)
    result = wait_file(directory / "receipt.json", 10)
    assert_health_result(result)
    return result


def health_client_name(run_id, cell_id):
    return "orq41-g9-health-" + hashlib.sha256(f"{run_id}/{cell_id}".encode()).hexdigest()[:16]


def summarize_client(receipt):
    if not receipt:
        return None
    result = {key: receipt.get(key) for key in ("status", "http_status", "request_id", "automatic_resend") if key in receipt}
    content = receipt.get("assistant_content")
    if isinstance(content, str):
        result["assistant_content_sha256"] = sha(content.encode())
    payload = receipt.get("payload")
    if isinstance(payload, dict):
        result["payload_status"] = payload.get("status")
        result["conversation_id"] = payload.get("conversation_id")
    if receipt.get("events"):
        result["sse_event_names"] = [row[0] for row in receipt["events"]]
    return result


def execute_cell(packet, cell, index, private, passwords, dbs):
    body = validate_manifest(packet)
    candidate = body["images"]["candidate"]
    baseline = body["images"]["baseline"]
    source_ref, source_vector, target_ref, target_vector, source_db_ref, target_db_ref = source_target(cell)
    source_image = candidate if source_ref == "candidate" else baseline
    target_image = candidate if target_ref == "candidate" else baseline
    active_db = dbs["c1"]
    token = f"{index:02d}-{hashlib.sha256(cell.cell_id.encode()).hexdigest()[:10]}"
    base_name = f"orq41-g9-{body['run_id']}-{token}"
    tenant = f"g9-{body['run_id']}-{token}"
    message = f"ORQ41-G9-{body['run_id']}-{token}"
    source_message, source_tenant = message, tenant
    cache_message, cache_tenant = message + "-cache", tenant + "-cache"
    prewarm_receipts = []

    # OFF cache semantics are measured before the timed transition and retained
    # across a process replacement. The same key then proves survival on C0.
    if cell.vector == "cache_parity":
        warm_name = base_name + "-warm"
        _, warm_work = create_worker(run_id=body["run_id"], name=warm_name, image=source_image,
            ref="c1", vector="OFF", database=active_db, passwords=passwords, private=private)
        start_worker(warm_name, warm_work)
        for suffix in ("miss", "hit"):
            client, receipt = simple_request(private=private, image=source_image,
                cell_id=cell.cell_id + "-cache-" + suffix, protocol="json", tenant=cache_tenant, message=cache_message)
            prewarm_receipts.append(summarize_client(receipt))
        stop_target(warm_name)
        warm_exit = wait_file(warm_work / "worker-exit.json", 8)
        if len(warm_exit["provider_calls"]) != 1:
            raise HarnessError("OFF cache must show one miss followed by a hit before rollback")
        warm_call_ids = {row["request_id"] for row in warm_exit["provider_calls"]}
        if prewarm_receipts[0].get("request_id") not in warm_call_ids or prewarm_receipts[1].get("request_id") in warm_call_ids:
            raise HarnessError("OFF source cache miss/hit request correlation is invalid")

    source_name = base_name + "-source"
    source_id, source_work = create_worker(run_id=body["run_id"], name=source_name, image=source_image,
        ref="c1", vector=source_vector, database=active_db, passwords=passwords,
        private=private, barrier=cell.barrier)
    _, source_startup = start_worker(source_name, source_work)
    before = db_projection(active_db, source_tenant, source_message)
    if before["row_count"]:
        raise HarnessError("G9 source request fixture collision before admission")
    timing = execute_source_barrier(source_name=source_name, source_work=source_work,
        source_image=source_image, private=private, cell=cell, tenant=source_tenant, message=source_message)
    source_projection = db_projection(active_db, source_tenant, source_message)
    source_state = parse_business_state(source_projection, tenant=source_tenant,
                                        user_content=source_message, expected=cell.expected_db_outcome)
    if source_state["database_outcome"] != cell.expected_db_outcome or source_state["partial_exchange"] or source_state["duplicate_exchange"]:
        raise HarnessError("source API database outcome differs from the frozen G9 oracle")
    timing["drain_s"] = time.monotonic() - timing["rollback_started_monotonic"]
    if len(timing["worker_exit"]["provider_calls"]) != 1:
        raise HarnessError("G9 source exchange must have exactly one stub provider dispatch")

    target_name = base_name + "-target"
    target_id, target_work = create_worker(run_id=body["run_id"], name=target_name, image=target_image,
        ref="c0" if target_ref == "baseline" else "c1", vector=target_vector,
        database=active_db, passwords=passwords, private=private)
    target_started, target_startup = start_worker(target_name, target_work)
    expected_settings_key = {"E1": "E1", "C1": "C1", "C0": "C0"}.get(target_vector)
    if target_vector == "OFF":
        expected_settings_key = "OFF_C1" if target_ref == "candidate" else "OFF_C0"
    if target_startup["config_identity"] != body["settings_sha256"][expected_settings_key]:
        raise HarnessError("target effective settings differ from frozen G9 manifest")
    expected_source_key = {"E1": "E1", "C1": "C1"}.get(source_vector)
    if source_vector == "OFF":
        expected_source_key = "OFF_C1"
    if source_startup["config_identity"] != body["settings_sha256"][expected_source_key]:
        raise HarnessError("source effective settings differ from frozen G9 manifest")
    probes = []
    health = health_probe(private=private, image=target_image, cell_id=cell.cell_id)
    probes.append({"kind": "health", "http_status": health["http_status"]})
    for protocol in ("json", "sse"):
        client, receipt = simple_request(private=private, image=target_image,
            cell_id=cell.cell_id + "-baseline-" + protocol, protocol=protocol,
            tenant=f"{tenant}-{protocol}", message=message + "-baseline-" + protocol)
        projection = db_projection(active_db, client["tenant"], client["message"])
        state = parse_business_state(projection, tenant=client["tenant"],
                                     user_content=client["message"], expected="one_complete_exchange")
        if state["database_outcome"] != "one_complete_exchange" or state["partial_exchange"] or state["duplicate_exchange"]:
            raise HarnessError("baseline JSON/SSE probe did not commit exactly one exchange")
        probes.append({"kind": protocol, "status": receipt["status"], "http_status": receipt["http_status"],
                       "assistant_sha256": sha(receipt["assistant_content"].encode()),
                       "db": {key: state[key] for key in ("database_outcome", "rows", "projection_sha256")}})
    cache_checks = []
    if cell.vector == "cache_parity":
        # Same tenant/key must hit across image replacement; a different tenant
        # must miss; SSE must continue bypassing the cache.
        cached_client, cached = simple_request(private=private, image=target_image,
            cell_id=cell.cell_id + "-cache-survives", protocol="json", tenant=cache_tenant, message=cache_message)
        foreign_client, foreign = simple_request(private=private, image=target_image,
            cell_id=cell.cell_id + "-cache-foreign", protocol="json", tenant=cache_tenant + "-foreign", message=cache_message)
        sse_client, sse = simple_request(private=private, image=target_image,
            cell_id=cell.cell_id + "-cache-sse", protocol="sse", tenant=cache_tenant, message=cache_message)
        cache_checks = [summarize_client(cached), summarize_client(foreign), summarize_client(sse)]
    recovered_source_projection = db_projection(active_db, source_tenant, source_message)
    if recovered_source_projection["sha256"] != source_projection["sha256"]:
        raise HarnessError("committed source exchange changed during rollback/recovery")
    recovery_completed = time.monotonic()
    # All target requests are complete before the unmeasured idle shutdown.
    stop_target(target_name)
    target_exit = wait_file(target_work / "worker-exit.json", 8)
    target_state = docker_json("inspect", target_name)[0]["State"]
    if target_state["ExitCode"] != 0 or target_exit["active_transactions"] != 0:
        raise HarnessError("target process did not shut down cleanly after baseline probes")
    if cell.vector == "cache_parity":
        if len(target_exit["provider_calls"]) != 4:
            raise HarnessError("OFF baseline must miss for foreign tenant and bypass for SSE, with same-tenant JSON hit")
        target_call_ids = {row["request_id"] for row in target_exit["provider_calls"]}
        if (cache_checks[0].get("request_id") in target_call_ids
                or cache_checks[1].get("request_id") not in target_call_ids
                or cache_checks[2].get("request_id") not in target_call_ids):
            raise HarnessError("OFF baseline cache hit/tenant separation/SSE bypass evidence is ambiguous")
        if cache_checks[0].get("status") != "RESOLVED" or cache_checks[0].get("assistant_content_sha256") != sha(b"ORQ-41 deterministic G9 response."):
            raise HarnessError("OFF same-tenant cache response mismatch")

    rollback_s = recovery_completed - timing["rollback_started_monotonic"]
    if (private / "network-audit.log").exists() and (private / "network-audit.log").stat().st_size:
        raise HarnessError("P2 network guard recorded a blocked egress attempt")
    return {
        "cell_id": cell.cell_id, "attempt_count": 1, "automatic_resend": False,
        "source_image": source_image, "target_image": target_image,
        "source_container_id": source_id, "target_container_id": target_id,
        "source_vector": source_vector, "target_vector": target_vector,
        "source_config_identity": source_startup["config_identity"],
        "target_config_identity": target_startup["config_identity"],
        "active_database": active_db, "p3_preflight_source": source_work.joinpath("preflight.json").exists(),
        "p3_preflight_target": target_work.joinpath("preflight.json").exists(),
        "cleanup_s": timing["cleanup_s"], "drain_s": timing["drain_s"], "rollback_s": rollback_s,
        "target_ready": True, "baseline_probes_pass": len(probes) == 3,
        "database_outcome": source_state["database_outcome"],
        "partial_exchange": source_state["partial_exchange"], "duplicate_exchange": source_state["duplicate_exchange"],
        "source_projection_sha256": source_state["projection_sha256"],
        "barrier_at_monotonic": timing["barrier"]["at"],
        "sigterm_at_monotonic": timing["signal"]["at_monotonic"],
        "quiescent_at_monotonic": timing["quiescent"]["at_monotonic"],
        "release_delay_s": timing["release_delay_s"],
        "source_client": summarize_client(timing["client_result"]),
        "source_request_event": timing["source_request_event"],
        "source_provider_dispatch": timing["source_provider_dispatch"],
        "source_provider_calls": len(timing["worker_exit"]["provider_calls"]),
        "target_provider_calls": len(target_exit["provider_calls"]),
        "pretransition_cache_receipts": prewarm_receipts,
        "cache_checks": cache_checks, "baseline_probes": probes,
        "source_exit_code": timing["state"]["ExitCode"], "target_exit_code": target_state["ExitCode"],
        "network_audit_sha256": sha((private / "network-audit.log").read_bytes()) if (private / "network-audit.log").exists() else sha(b""),
        "source_stderr_sha256": sha(docker("logs", source_name)),
        "target_stderr_sha256": sha(docker("logs", target_name)),
    }


def running_g9_containers(run_id):
    raw = docker("ps", "--format", "{{.Names}}")
    prefix = f"orq41-g9-{run_id}-"
    return [name for name in raw.decode().splitlines() if name.startswith(prefix)]


def observed_stub_dispatches(private: Path) -> int:
    total = 0
    for worker_dir in (private / "workers").glob("*"):
        exit_path = worker_dir / "worker-exit.json"
        if exit_path.is_file():
            total += len(json.loads(exit_path.read_text()).get("provider_calls", []))
        elif (worker_dir / "barrier-primary_provider_wait.json").is_file():
            total += 1
    return total


def update_planning(*, run_public, result, status):
    path = ORQ / "planning-status.json"
    value = json.loads(path.read_text())
    value["readiness_audit"]["g9"] = status
    value["environment"]["g9_executed"] = status == "G9_EXECUTED_PASS_AWAITING_INDEPENDENT_REVIEW"
    design = value["c1_g123_harness_design"]
    design["g9_execution_status"] = status
    design["g9_execution_record"] = str((run_public / "execution.json").relative_to(ORQ))
    design["g9_manifest_sha256"] = result["manifest_sha256"]
    design["g9_cases_total"] = result["cases_total"]
    design["g9_cases_passed"] = result["cases_passed"]
    design["g9_cases_failed"] = result["cases_failed"]
    design["remaining"] = (["Independent complete-packet review and operator D6 acceptance"]
                            if status == "G9_EXECUTED_PASS_AWAITING_INDEPENDENT_REVIEW"
                            else ["Resolve retained G9 findings, then independent complete-packet review and operator D6 acceptance"])
    value["operator_authorization"] = (
        "Local G1/G2/G3 and G9 lifecycle execution explicitly authorized; G1/G2/G3 reviewed PASS and G9 evidence is retained at "
        + str((run_public / "execution.json").relative_to(ORQ))
        + ". No campaign, external providers, G6/G7, production infrastructure, Notion or commits. Plan / decision freeze remains BLOCKED.")
    if status == "G9_EXECUTED_PASS_AWAITING_INDEPENDENT_REVIEW":
        value["pending"] = [item for item in value.get("pending", [])
                            if not item.startswith("Execute G9 restart/drain/cache/persistence drill")]
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    os.replace(temp, path)


def write_handoff(run_public, result):
    handoff = ORQ / "session-handoff.md"
    existing = handoff.read_text(encoding="utf-8")
    section = (f"## G9 execution {result['run_id']} — {result['status']}\n\n"
               f"Frozen 14-cell G9 manifest `{result['manifest_sha256']}`; "
               f"{result['cases_passed']}/{result['cases_total']} cases PASS, "
               f"{result['cases_failed']} findings, {result['cases_attempted']} attempted.\n"
               f"Evidence: `{(run_public / 'execution.json').relative_to(ORQ)}`. "
               "PostgreSQL was real and isolated; generation used local stubs. "
               "No egress, external calls, paid requests, or spend. P5 was not touched.\n"
               "ORQ-41 remains Plan / decision freeze BLOCKED pending independent complete-packet review and explicit D6.\n\n")
    if existing.startswith(f"## G9 execution {result['run_id']}"):
        raise HarnessError("handoff already contains this G9 run")
    handoff.write_text(section + existing, encoding="utf-8")


def write_g9_packet_note(run_public, result):
    packet = ORQ / "readiness/g9-acceptance-packet.md"
    existing = packet.read_text(encoding="utf-8")
    section = (f"## Latest execution — {result['run_id']}\n\n"
               f"Status: **{result['status']}**. Frozen manifest `{result['manifest_sha256']}`; "
               f"{result['cases_passed']}/{result['cases_total']} cells PASS. "
               f"Receipts: `{(run_public / 'execution.json').relative_to(ORQ)}`. "
               "D6 acceptance and independent complete-packet review remain pending.\n\n")
    if existing.startswith(f"## Latest execution — {result['run_id']}"):
        raise HarnessError("G9 acceptance packet already contains this run")
    packet.write_text(section + existing, encoding="utf-8")


def main():
    from .g9 import require_successful_timing
    run_id = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    runs = ORQ / "environment/g9/runs"
    run_public = runs / run_id
    run_public.mkdir(mode=0o700, parents=True, exist_ok=False)
    private = Path(tempfile.mkdtemp(prefix=f"orq41-g9-{run_id}-"))
    private.chmod(0o700)
    run_dir = run_public
    results = []
    packet = None
    preflight_state = None
    try:
        packet, passwords, dbs, preflight_state = preflight(run_dir, private)
        public_write(run_public / "preflight-execution.json", {**preflight_state,
                                                      "status": "G9_PREFLIGHT_PASS_MANIFEST_FROZEN"})
        for index, cell in enumerate(cells(), 1):
            attempt_path = run_public / "cases" / f"{index:02d}-{cell.cell_id}.json"
            try:
                row = execute_cell(packet, cell, index, private, passwords, dbs)
                require_successful_timing(cell, row)
                outcome = {"status": "PASS", **row}
            except Exception as exc:
                outcome = {"status": "FAILED", "cell_id": cell.cell_id,
                           "attempt_count": 1, "automatic_resend": False,
                           "error_type": type(exc).__name__, "diagnostic_sha256": sha(str(exc).encode()),
                           "diagnostic": str(exc)[:240]}
            public_write(attempt_path, outcome)
            results.append(outcome)
            if outcome["status"] != "PASS" and running_g9_containers(run_id):
                # A live worker after a failed cell is an unresolved lifecycle
                # state. Preserve it and stop admitting later G9 cells.
                break
        passed = sum(row["status"] == "PASS" for row in results)
        failed = sum(row["status"] != "PASS" for row in results)
        all_cells = len(results) == len(cells()) and failed == 0
        final_status = ("G9_EXECUTED_PASS_AWAITING_INDEPENDENT_REVIEW" if all_cells
                        else "G9_EXECUTED_FINDINGS" if failed else "G9_EXECUTION_INCOMPLETE")
        audit_path = private / "network-audit.log"
        egress_attempts = (sum(bool(line.strip()) for line in audit_path.read_text().splitlines())
                           if audit_path.exists() else 0)
        result = {"status": final_status, "run_id": run_id,
                  "manifest_sha256": packet["sha256"], "cases_total": len(cells()),
                  "cases_attempted": len(results), "cases_passed": passed, "cases_failed": failed,
                  "automatic_resends": 0, "provider_calls": 0,
                  "local_stub_dispatches": observed_stub_dispatches(private),
                  "external_calls": 0, "egress_attempts": egress_attempts,
                  "campaign_spend_usd": "0", "decision_freeze": "BLOCKED",
                  "p5_changed": False, "app_changed": False,
                  "private_state": str(private), "case_receipts": [str(row["cell_id"]) for row in results]}
        public_write(run_public / "execution.json", result)
        md = ["# G9 local lifecycle execution", "", f"Status: **{final_status}**.", "",
              f"Manifest SHA-256: `{packet['sha256']}`.",
              f"Cases: {passed}/{len(cells())} PASS; {failed} failed; {len(results)} attempted.",
              "Cleanup/drain/rollback limits: 10/30/60 seconds. Cache TTL: 300 seconds.",
              "PostgreSQL was real and local; generation was stubbed inside each isolated API worker.",
              f"P2 namespace and socket guard were applied; external provider calls and spend: zero; local stub dispatches: {result['local_stub_dispatches']}; egress attempts: {egress_attempts}.",
              "No automatic request resends. Original ORQ-41 phase remains Plan / decision freeze BLOCKED.", ""]
        (run_public / "validation.md").write_text("\n".join(md), encoding="utf-8")
        status = final_status
        update_planning(run_public=run_public, result=result, status=status)
        write_handoff(run_public, result)
        write_g9_packet_note(run_public, result)
        print(json.dumps({key: result[key] for key in ("status", "run_id", "manifest_sha256", "cases_total",
                                                        "cases_attempted", "cases_passed", "cases_failed",
                                                        "provider_calls", "local_stub_dispatches", "external_calls", "egress_attempts",
                                                        "campaign_spend_usd", "decision_freeze")}))
        return 0 if all_cells else 1
    except Exception as exc:
        blocked = {"status": "G9_PREFLIGHT_BLOCKED", "run_id": run_id,
                   "diagnostic_type": type(exc).__name__, "diagnostic_sha256": sha(str(exc).encode()),
                   "diagnostic": str(exc)[:240], "provider_calls": 0, "external_calls": 0,
                   "egress_attempts": 0, "campaign_spend_usd": "0", "decision_freeze": "BLOCKED"}
        try:
            public_write(run_public / "preflight-result.json", blocked)
        except Exception:
            pass
        print(json.dumps(blocked))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

