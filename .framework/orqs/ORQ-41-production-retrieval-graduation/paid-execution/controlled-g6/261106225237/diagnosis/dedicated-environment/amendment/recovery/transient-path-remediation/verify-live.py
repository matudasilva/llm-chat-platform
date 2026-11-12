"""Read-only archive and live restoration verification; never mutates host state."""
import hashlib
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "operator-execution-261111015223"
RUN = "261111015223"

def sha(data):
    return hashlib.sha256(data).hexdigest()

def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())

def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=20).stdout.strip()

with tarfile.open(OUT / "journal.tar") as archive:
    members = archive.getmembers()
    assert len({m.name for m in members}) == len(members)
    assert all(m.isdir() or m.isfile() for m in members)
    files = {m.name: archive.extractfile(m).read() for m in members if m.isfile()}
manifest = json.loads(files[RUN + "/baseline.json"])
assert manifest["hash"] == digest(manifest["data"])
data = manifest["data"]
assert data["schema_version"] == 2
assert sha(files[RUN + "/helper.py"]) == data["helper_sha256"] == sha((ROOT / "admin_recovery.py").read_bytes())
record_names = sorted(k for k in files if "/record-" in k)
rows = []
previous = "0" * 64
for i, name in enumerate(record_names):
    assert name == f"{RUN}/record-{i:04d}.json"
    row = json.loads(files[name])
    assert row["seq"] == i and row["previous"] == previous
    assert row["hash"] == digest({k: v for k, v in row.items() if k != "hash"})
    previous = row["hash"]
    rows.append(row)
assert rows[0]["event"] == "PREPARED"
assert rows[0]["value"] == digest(data["baseline"])
assert [r["value"] for r in rows if r["event"] == "APPLY_INTENT"] == list(range(5))
assert [r["value"] for r in rows if r["event"] == "APPLIED"] == list(range(5))
assert [r["event"] for r in rows[-3:]] == ["RESTORED", "DISARM_INTENT", "DISARMED"]
assert (OUT / "exits.txt").read_text() == "drill_exit=0 archive_exit=0\n"
assert "RESULT apply=0 readback=0 recover=0 verify=0" in (OUT / "drill.log").read_text()
base = data["baseline"]
current = {}
for unit, expected in base["units"].items():
    raw = command("systemctl", "show", *("-p" + k for k in expected), unit)
    props = dict(line.split("=", 1) for line in raw.splitlines())
    assert props == expected, (unit, props, expected)
    current[unit] = props
    if unit != "orq41bench.slice":
        kernel = Path("/sys/fs/cgroup" + props["ControlGroup"] + "/cpuset.cpus.effective").read_text().strip()
        assert kernel == "0-31"
paths = [a["path"] for a in data["actions"]]
paths.append("/run/systemd/system.control/init.scope.d/50-AllowedCPUs.conf")
for name in paths:
    assert not Path(name).exists() and not Path(name).is_symlink(), name
watchdog = {}
for kind in ("timer", "service"):
    raw = command("systemctl", "show", "-pLoadState", "-pActiveState", "-pSubState", f"orq41-cpuset-recovery-{RUN}.{kind}")
    props = dict(line.split("=", 1) for line in raw.splitlines())
    assert props["LoadState"] == "not-found" and props["ActiveState"] == "inactive"
    watchdog[kind] = props
names = [c["Name"].lstrip("/") for c in base["inventory"]["containers"]]
containers = json.loads(command("docker", "inspect", *names))
kept = [{k: row[k] for k in ("Id", "Name", "RestartCount")} |
        {"status": row["State"]["Status"], "pid": row["State"]["Pid"], "started": row["State"]["StartedAt"]} for row in containers]
assert kept == base["inventory"]["containers"]
power = {p: Path(p).read_text().strip() for p in base["inventory"]["power"]}
assert power == base["inventory"]["power"]
result = dict(status="LIVE_RESTORATION_VERIFIED_PASS", captured_at=datetime.now(timezone.utc).isoformat(),
              journal_records=len(rows), final_hash=previous, helper_sha256=data["helper_sha256"],
              archive_sha256=sha((OUT / "journal.tar").read_bytes()), units=current,
              absent_paths=paths, watchdog=watchdog, containers=kept, power=power,
              benchmark_requests=0, provider_calls=0, spend_usd="0", environment_ready=False)
(OUT / "live-verification.json").write_text(json.dumps(result, indent=2) + "\n")
print(result["status"], "records=", len(rows))
