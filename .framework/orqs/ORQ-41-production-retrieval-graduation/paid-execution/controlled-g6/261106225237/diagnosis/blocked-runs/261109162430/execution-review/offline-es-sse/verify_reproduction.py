"""Reproduce deterministic file-only outputs in scratch, without services."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

out = Path(__file__).resolve().parent
run = out.parents[1]
sha = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
manifest = json.loads((out / "inputs.json").read_text())
assert sha(out / "analyze.py") == manifest["script_sha256"]
for relative, digest in manifest["files_sha256"].items():
    assert sha(run / relative) == digest
compared = {}
with tempfile.TemporaryDirectory(prefix="orq41-offline-replay-") as scratch:
    copy = Path(scratch) / "packet"
    for relative in manifest["files_sha256"]:
        target = copy / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run / relative, target)
    script = copy / "execution-review/offline-es-sse/analyze.py"
    shutil.copyfile(out / "analyze.py", script)
    execution = subprocess.run([sys.executable, str(script)],
        check=True, capture_output=True, timeout=30)
    assert b"OFFLINE_ES_SSE_DESCRIPTIVE_ANALYSIS_COMPLETE" in execution.stdout
    for name in ("analysis.json", "paired-deltas.json", "requests.csv", "inputs.json"):
        original, reproduced = out / name, script.parent / name
        assert original.read_bytes() == reproduced.read_bytes(), name
        compared[name] = sha(original)
for relative, digest in manifest["files_sha256"].items():
    assert sha(run / relative) == digest
baseline = json.loads((run / "execution-scope-before.json").read_text())
assert len(baseline) == 500
assert all(sha(Path(name)) == digest for name, digest in baseline.items())
result = dict(status="OFFLINE_ANALYSIS_SCRATCH_REPRODUCTION_PASS",
    input_files_unchanged=len(manifest["files_sha256"]), outputs_byte_identical=compared,
    protected_source_files_unchanged=500, new_application_requests=0,
    services_started=0, new_measurements=0, external_provider_calls=0, spend_usd="0")
with (out / "reproduction.json").open("x") as f:
    f.write(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
