"""Copy existing logs from the stopped, retained collector; never start services."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

p = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
plan = json.loads((p / "plan.json").read_text())
cleanup = json.loads((p / "execution-review/cleanup.json").read_text())
name = plan["containers"]["collector"]
command = ["docker", "--host", "unix:///var/run/docker.sock"]
info = json.loads(subprocess.run(command + ["inspect", name], check=True,
    capture_output=True, timeout=60).stdout)[0]
assert not info["State"]["Running"], "Collector must remain stopped"
assert info["Id"] == cleanup["services"]["collector"]["id"]
assert info["Image"] == plan["auxiliary_images"]["collector"]
raw = subprocess.run(command + ["logs", name], check=True, capture_output=True, timeout=60)
hashes = {}
for stream, data in (("stdout", raw.stdout), ("stderr", raw.stderr)):
    target = out / ("retained-collector-" + stream + ".log")
    with target.open("xb") as f:
        f.write(data)
    hashes[stream] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
receipt = dict(status="STOPPED_COLLECTOR_RETAINED_LOGS_READ_ONLY",
    captured_at=datetime.now(timezone.utc).isoformat(), container=name, id=info["Id"],
    image=info["Image"], running=False, streams=hashes, new_application_requests=0,
    provider_calls=0, services_started=0, spend_usd="0")
with (out / "collector-log-provenance.json").open("x") as f:
    f.write(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt, indent=2))
