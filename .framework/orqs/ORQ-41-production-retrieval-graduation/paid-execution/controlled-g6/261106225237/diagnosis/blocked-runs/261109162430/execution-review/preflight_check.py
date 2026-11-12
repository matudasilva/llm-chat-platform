"""Read-only admission proof for the single operator-authorized local A/A."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from experiments.production_graduation.gate_validation import blocked_latency as h
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

p = Path(__file__).resolve().parent.parent
review_dir = p / "execution-review"
check_p2()
assert h.sha_file(p / "plan.json") == "b3d7cbe4aa4587ca20a3dadd79e2a10d7813981b8a33550d661c58af6f19026b"
assert h.sha_file(p / "independent-review.json") == "8f447eae61aac94704a6c5700a595df520e3f8192ed1a49b8440b1f8002019a2"
assert not (p / "execution-started.json").exists()
baseline = json.loads((h.DESIGN / "namespace-remediation/preparation-scope-before.json").read_text())
for name, digest in baseline.items():
    assert h.sha_file(h.ROOT / name) == digest, "Protected source changed: " + name
assert len(baseline) == 500
h.write_json(p / "execution-scope-before.json", baseline)
h.write_json(p / "execution-authorization.json", dict(
    status="OPERATOR_AUTHORIZED_BLOCKED_AA_EXECUTION",
    authorized_at=datetime.now(timezone.utc).isoformat(),
    operator_message="autorizado",
    antecedent="Single local-stub A/A on reviewed packet261109162430, 1440 requests; prior failed attempt cannot resume.",
    plan_sha256=h.sha_file(p / "plan.json"),
    fixtures_sha256=h.sha_file(p / "fixtures.json"),
    packet_review_sha256=h.sha_file(p / "independent-review.json"),
    total_requests=1440, measured=800, warmups=640, workers=32,
    repetitions=1, concurrency=1, attempts_per_identity=1,
    external_provider_calls_authorized=0, spend_usd="0",
    formal_g6_authorized=False, paid_admission_authorized=False,
    historical_failures_preserved=True
))
plan, fixtures, prep = h.preflight(p)
resources = h.aa.inspect_environment(plan)
db = h.aa.Database(plan["containers"]["postgres"])
proof = h.verify_databases(db, plan, fixtures)
assert proof == prep["databases"], "Prepared business data changed"
for analysis in prep["analyses"]:
    actual = json.loads(h.readonly(db, analysis["database"], h.SETTINGS_SQL))
    assert actual == analysis["settings"], "Database planner/autovacuum settings changed"
configs = []
private = Path(prep["private_state"])
code = ("import json;from experiments.production_graduation.gate_validation.blocked_latency "
        "import configuration_probe;print(json.dumps(configuration_probe()))")
for index, arm in enumerate(h.ARMS):
    raw = h.docker("run", "--rm", "--pull=never", "--network", "none",
        "--env-file", str(private / (arm + ".env")),
        "--cpus=2", "--cpuset-cpus", "0,2", "--memory=2147483648",
        "--memory-swap=2147483648",
        "--mount", f"type=bind,src={h.ROOT/'experiments'},dst=/app/experiments,readonly",
        "--mount", f"type=bind,src={h.P2_GUARD},dst=/p2_netguard,readonly",
        "--entrypoint", "/usr/local/bin/python", plan["images"][arm], "-c", code)
    value = json.loads(raw)
    assert value["config"] == plan["config_sha256"][arm]
    assert value["normalized"] == plan["normalized_config_sha256"]
    assert value["seed"] == plan["seed_probe"]
    assert value["resources"]["topology"] == plan["cpu_topology"]
    configs.append(value)
h.check_local_services(plan, private / "c0.env")
space = shutil.disk_usage(h.ROOT)
assert space.free > 5 * 1024**3, "Insufficient local evidence space"
h.write_json(review_dir / "pre-execution-proof.json", dict(
    status="BLOCKED_AA_EXECUTION_PREFLIGHT_PASS",
    checked_at=datetime.now(timezone.utc).isoformat(),
    plan_sha256=h.sha_file(p / "plan.json"),
    authorization_sha256=h.sha_file(p / "execution-authorization.json"),
    packet_review_sha256=h.sha_file(p / "independent-review.json"),
    protected_source_files=500, databases=proof, resources=resources, configs=configs,
    disk_free_bytes=space.free, application_requests=0,
    external_provider_calls=0, spend_usd="0"
))
print("BLOCKED_AA_EXECUTION_PREFLIGHT_PASS")
