"""Preserve raw streams, verify persisted results and replay the one local A/A."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from uuid import UUID

from experiments.production_graduation.gate_validation import blocked_latency as h
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

check_p2()
p = Path(__file__).resolve().parent.parent
out = p / "execution-review"
plan = json.loads((p / "plan.json").read_text())
result = json.loads((p / "result.json").read_text())
rows = {arm: [] for arm in ("c0", "c1")}
instances = set()
workers = {}
for entry in plan["arm_cell_order"]:
    key = f'{entry["arm"]}-{entry["cell"]}-b{entry["block"]}'
    file = p / (key + ".json")
    worker = json.loads(file.read_text())
    h.validate_worker(worker, plan, entry)
    assert h.sha_file(file) == result["worker_receipts"][file.name]
    assert json.loads((p / (key + "-started.json")).read_text())["entry"] == entry
    assert (p / (key + "-observations.json")).is_file()
    rows[entry["arm"]].extend(worker["samples"])
    name = "orq41-blocked-" + plan["run_id"] + "-" + key.lower()
    log = subprocess.run(["docker", "--host", "unix:///var/run/docker.sock", "logs", name],
                         capture_output=True, check=True, timeout=60)
    h.private_write(out / (key + "-stdout.log"), log.stdout)
    h.private_write(out / (key + "-stderr.log"), log.stderr)
    state = json.loads(h.docker("inspect", name))[0]
    assert not state["State"]["Running"] and state["State"]["ExitCode"] == 0
    workers[key] = dict(container=name, id=state["Id"], exit_code=0,
        stdout_sha256=h.sha_file(out / (key + "-stdout.log")),
        stderr_sha256=h.sha_file(out / (key + "-stderr.log")))
for arm, samples in rows.items():
    assert len(samples) == 720
    assert len({r["sample_id"] for r in samples}) == 720
    assert sum(not r["warmup"] for r in samples) == 400
    for r in samples:
        assert r["status"] == "PASS" and r["error"] is None
        uid = r["accounting_instance_id"]
        assert str(UUID(uid)) == uid and uid not in instances
        instances.add(uid)
        assert r["preparation_ns"] == r["primary_dispatch_ns"] - r["start_ns"]
        assert r["preparation_ns"] >= 0
cells = []
for cell in ("EN-json", "EN-sse", "ES-json", "ES-sse"):
    values = {}
    for arm in ("c0", "c1"):
        subset = [r for r in rows[arm] if not r["warmup"]
                  and r["language"] + "-" + r["protocol"] == cell]
        assert len(subset) == 100
        assert Counter(r["category"] for r in subset) == dict.fromkeys(
            ("document", "history", "combined", "empty"), 25)
        values[arm] = sorted(r["preparation_ns"] for r in subset)[94]
    a, b = values["c0"], values["c1"]
    status = "PASS" if 100*a <= 105*b and 100*b <= 105*a else "FAIL"
    expected = next(r for r in result["cells"] if r["cell"] == cell)
    assert (a, b, status) == (expected["c0_p95_ns"], expected["c1_p95_ns"], expected["status"])
    cells.append(dict(cell=cell, n_per_arm=100, c0_p95_ns=a, c1_p95_ns=b,
                      ratio_percent=100*max(a,b)/min(a,b), status=status))
replayed = "AA_CALIBRATION_PASS" if all(c["status"] == "PASS" for c in cells) else "AA_CALIBRATION_FAIL"
assert replayed == result["status"]
h.write_json(out / "parent-replay.json", dict(
    status="BLOCKED_AA_RAW_REPLAY_VERIFIED", calibration_outcome=replayed,
    plan_sha256=h.sha_file(p / "plan.json"), result_sha256=h.sha_file(p / "result.json"),
    request_count=1440, measured=800, warmups=640, accounting_instances=len(instances),
    formula="sorted100[index94]; max(P95)/min(P95)<=1.05, exact integer cross-products",
    cells=cells, worker_streams=workers, new_application_requests=0, spend_usd="0"))
db = h.aa.Database(plan["containers"]["postgres"])
final = h.verify_databases(db, plan, json.loads((p / "fixtures.json").read_text()), final=True)
assert final == json.loads((p / "database-final-verification.json").read_text())["databases"]
counts = {}
for arm, database in plan["databases"].items():
    counts[arm] = h.readonly(db, database,
        "SELECT (SELECT count(*) FROM conversations),(SELECT count(*) FROM messages),"
        "(SELECT count(*) FROM usage_events),(SELECT count(*) FROM rag_request_metrics);").strip()
baseline = json.loads((p / "execution-scope-before.json").read_text())
assert all(h.sha_file(h.ROOT / name) == digest for name, digest in baseline.items())
audits = [p / "network-audit.log", Path("/tmp/orq41-blocked-261109162430-execution-network.log")]
assert all(not f.exists() or f.stat().st_size == 0 for f in audits)
h.write_json(out / "post-execution-proof.json", dict(
    status="BLOCKED_AA_POST_EXECUTION_PROOF_PASS", checked_at=datetime.now(timezone.utc).isoformat(),
    plan_sha256=h.sha_file(p / "plan.json"), databases=final, database_counts=counts,
    protected_files_unchanged=len(baseline), network_audit_bytes=0,
    provider_dispatch_transport="Frozen native SDK/HTTP memory stubs only",
    external_provider_calls=0, paid_requests=0, spend_usd="0",
    automatic_resends=0, execution_markers_retained=True))
cleanup = {}
for service in ("collector", "redis", "postgres"):
    name = plan["containers"][service]
    h.docker("stop", "--time", "10", name)
    info = json.loads(h.docker("inspect", name))[0]
    assert not info["State"]["Running"]
    cleanup[service] = dict(container=name, id=info["Id"], running=False, data_retained=True)
source = json.loads(h.docker("inspect", "orq41-env-pg"))[0]
assert source["State"]["Running"]
h.write_json(out / "cleanup.json", dict(status="BLOCKED_AA_OWN_SERVICES_STOPPED_DATA_RETAINED",
    services=cleanup, source_postgres_id=source["Id"], source_postgres_running=True,
    worker_containers_retained=32, markers_retained=True, no_resume=True))
print(json.dumps(dict(status="BLOCKED_AA_POST_EXECUTION_PROOF_PASS",
    calibration_outcome=replayed, cells=cells, external_provider_calls=0, spend_usd="0"), indent=2))
