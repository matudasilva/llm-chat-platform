"""Descriptive offline analysis only; never admits or changes measured requests."""
import calendar
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics

OUT = Path(__file__).resolve().parent
RUN = OUT.parents[1]
inputs = {}


def read(path):
    raw = path.read_bytes()
    inputs[str(path.relative_to(RUN))] = hashlib.sha256(raw).hexdigest()
    return raw.decode()


def load(path):
    return json.loads(read(path))


def write(name, value):
    with (OUT / name).open("x") as f:
        json.dump(value, f, indent=2)
        f.write("\n")


def quantile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def stats(values):
    return dict(n=len(values), mean=statistics.mean(values),
                p50=quantile(values, .5), p95=quantile(values, .95),
                maximum=max(values), minimum=min(values))


def timestamp(value):
    m = re.fullmatch(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.(\d{1,9}) \+0000 UTC", value)
    assert m, value
    seconds = calendar.timegm(datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").timetuple())
    return seconds * 10**9 + int(m[2].ljust(9, "0"))


assert os.environ.get("APP_SETTINGS_ENV_FILE") == ""
assert os.environ.get("AWS_EC2_METADATA_DISABLED") == "true"
assert not any(os.environ.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN", "AWS_PROFILE", "OPENAI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"))
assert {s.split(":")[0].strip() for s in Path("/proc/self/net/dev").read_text().splitlines()[2:]} <= {"lo"}
import sitecustomize
assert "p2_netguard" in str(sitecustomize.__file__)

plan = load(RUN / "plan.json")
assert hashlib.sha256((RUN / "plan.json").read_bytes()).hexdigest() == "b3d7cbe4aa4587ca20a3dadd79e2a10d7813981b8a33550d661c58af6f19026b"
result = load(RUN / "result.json")
assert result["status"] == "AA_CALIBRATION_FAIL"
receipt = load(RUN / "execution-review/receipt.json")
assert receipt["status"] == "BLOCKED_AA_EXECUTION_INDEPENDENT_REPLAY_VERIFIED_FAIL"
provenance = load(OUT / "collector-log-provenance.json")
raw = read(OUT / "retained-collector-stderr.log")
assert inputs["execution-review/offline-es-sse/retained-collector-stderr.log"] == provenance["streams"]["stderr"]["sha256"]
spans, current = [], None
for line in raw.splitlines():
    if re.fullmatch(r"Span #\d+", line):
        if current is not None:
            spans.append(current)
        current = {"attributes": {}}
    elif current is not None:
        field = re.match(r"    (Trace ID|Parent ID|ID|Name|Start time|End time|Status code)\s*:\s*(.*)", line)
        attribute = re.match(r"     -> ([a-z_.]+): (Str|Int|Bool)\((.*)\)$", line)
        if field:
            current[field[1]] = field[2]
        elif attribute:
            # Resource attributes cannot occur inside a span's attribute section.
            if attribute[1].startswith(("request.", "rag.", "memory.", "provider.")):
                current["attributes"][attribute[1]] = attribute[3]
if current is not None:
    spans.append(current)
traces = defaultdict(list)
for s in spans:
    assert all(k in s for k in ("Trace ID", "Parent ID", "ID", "Name", "Start time", "End time", "Status code"))
    s["start_ns"], s["end_ns"] = timestamp(s["Start time"]), timestamp(s["End time"])
    assert s["end_ns"] >= s["start_ns"]
    traces[s["Trace ID"]].append(s)
roots = {}
for trace, group in traces.items():
    candidates = [s for s in group if s["Name"] == "request"]
    assert len(candidates) == 1 and len({s["ID"] for s in group}) == len(group)
    root = candidates[0]
    assert root["Parent ID"] == "" and all(s is root or s["Parent ID"] == root["ID"] for s in group)
    assert all(root["start_ns"] <= s["start_ns"] <= s["end_ns"] <= root["end_ns"] for s in group)
    uid = root["attributes"]["request.instance_id"]
    assert uid not in roots
    assert all(s["Status code"] == "Unset" for s in group)
    roots[uid] = (root, group)

rows, block_rows, worker_sources = [], [], {}
for index, entry in enumerate(plan["arm_cell_order"]):
    arm, cell, block = entry["arm"], entry["cell"], entry["block"]
    key = f"{arm}-{cell}-b{block}"
    worker = load(RUN / (key + ".json"))
    obs = load(RUN / (key + "-observations.json"))
    assert inputs[key + ".json"] == result["worker_receipts"][key + ".json"]
    assert inputs[key + "-observations.json"] == receipt["observation_receipts"][key + "-observations.json"]
    worker_sources[key] = inputs[key + ".json"]
    first = next(e["arm"] for e in plan["arm_cell_order"] if e["cell"] == cell and e["block"] == block)
    local_rows = []
    for sample in worker["samples"]:
        assert sample["status"] == "PASS" and sample["error"] is None
        row = dict(sample, arm=arm, cell=cell, worker=key, first=arm == first, worker_index=index)
        root, group = roots[sample["accounting_instance_id"]]
        assert root["attributes"]["request.correlation_id"] == sample["request_id"]
        counts = Counter(s["Name"] for s in group)
        expected = dict.fromkeys(("request", "rag.rewrite", "rag.retrieve", "memory.assemble", "rag.generate"), 1)
        if sample["category"] in ("document", "combined"):
            expected["rag.rerank"] = 1
        assert counts == expected, (key, sample["sample_id"], counts)
        row["stages_ns"] = {s["Name"]: s["end_ns"] - s["start_ns"] for s in group}
        local_rows.append(row)
        rows.append(row)
    assert len(local_rows) == 45
    maintenance = []
    for db_arm in ("c0", "c1"):
        for a, b in zip(obs["db_before"][db_arm]["maintenance"], obs["db_after"][db_arm]["maintenance"]):
            assert a["relname"] == b["relname"]
            for k in ("last_analyze", "last_autoanalyze", "last_vacuum", "last_autovacuum"):
                if a[k] != b[k]:
                    maintenance.append(dict(arm=db_arm, table=a["relname"], field=k, before=a[k], after=b[k]))
    loads = {}
    for cpu, ticks in obs["host_delta"].items():
        total = sum(ticks[:8])  # guest/guest_nice already included in user/nice.
        loads[cpu] = 100 * (total - ticks[3] - ticks[4]) / total
    block_rows.append(dict(worker=key, arm=arm, cell=cell, block=block, first=arm == first,
        measured=stats([r["preparation_ns"] for r in local_rows if not r["warmup"]]),
        warmup=stats([r["preparation_ns"] for r in local_rows if r["warmup"]]),
        api_cpu_delta=worker["cpu_stat_delta"], pg_cpu_delta=obs["pg_delta"],
        database_delta=obs["db_delta"], maintenance_changes=maintenance,
        wall_window_ns=obs["host_after"]["end_ns"]-obs["host_before"]["start_ns"],
        coarse_busy_percent=loads,
        frequency_before_khz=obs["host_before"]["reported_frequency_khz"],
        frequency_after_khz=obs["host_after"]["reported_frequency_khz"]))
assert len(rows) == len(roots) == 1440
assert len({r["accounting_instance_id"] for r in rows}) == 1440
indexed = {(r["arm"], r["sample_id"]): r for r in rows}
pairs = []
for a in (r for r in rows if r["arm"] == "c0"):
    b = indexed["c1", a["sample_id"]]
    assert a["case_id"] == b["case_id"] and a["dispatches"] == b["dispatches"]
    pairs.append(dict(sample_id=a["sample_id"], cell=a["cell"], category=a["category"],
        case_id=a["case_id"], block=a["block"], warmup=a["warmup"],
        c0_preparation_ns=a["preparation_ns"], c1_preparation_ns=b["preparation_ns"],
        delta_preparation_ns=b["preparation_ns"]-a["preparation_ns"],
        stage_delta_ns={k:b["stages_ns"][k]-a["stages_ns"][k] for k in a["stages_ns"]}))

categories, cases, cells = [], [], []
for cell in ("EN-json", "EN-sse", "ES-json", "ES-sse"):
    summary = dict(cell=cell)
    for arm in ("c0", "c1"):
        selected = [r for r in rows if r["cell"] == cell and r["arm"] == arm and not r["warmup"]]
        assert len(selected) == 100
        summary[arm] = stats([r["preparation_ns"] for r in selected])
        expected = next(c for c in result["cells"] if c["cell"] == cell)
        assert summary[arm]["p95"] == expected[arm+"_p95_ns"]
        for category in ("document", "history", "combined", "empty"):
            group = [r for r in selected if r["category"] == category]
            assert len(group) == 25
            categories.append(dict(cell=cell, arm=arm, category=category,
                preparation_ns=stats([r["preparation_ns"] for r in group]),
                stages_ns={k:stats([r["stages_ns"][k] for r in group]) for k in group[0]["stages_ns"]}))
        for case in sorted({r["case_id"] for r in selected}):
            group = [r for r in selected if r["case_id"] == case]
            assert len(group) == 5
            cases.append(dict(cell=cell, arm=arm, case_id=case,
                preparation_ns=stats([r["preparation_ns"] for r in group]),
                distinct_primary_payload_hashes=len({r["dispatches"][1]["sha256"] for r in group}),
                distinct_rewrite_payload_hashes=len({r["dispatches"][0]["sha256"] for r in group})))
    cells.append(summary)

es = [r for r in rows if r["cell"] == "ES-sse" and not r["warmup"]]
tails = {}
c0_limit_numerator = next(c for c in cells if c["cell"] == "ES-sse")["c0"]["p95"]*105
for arm in ("c0", "c1"):
    selected = sorted([r for r in es if r["arm"] == arm], key=lambda r:r["preparation_ns"], reverse=True)
    tails[arm] = dict(top10=selected[:10], p95_row=selected[5],
        above_frozen_c0_p95_plus5pct=[r for r in selected if 100*r["preparation_ns"]>c0_limit_numerator])

with (OUT / "requests.csv").open("x") as f:
    writer = csv.writer(f)
    stages = ("request", "rag.rewrite", "rag.retrieve", "rag.rerank", "memory.assemble", "rag.generate")
    writer.writerow(["arm", "cell", "block", "ordinal", "warmup", "category", "case_id",
                     "request_id", "accounting_instance_id", "first", "preparation_ns", *[k+"_ns" for k in stages]])
    for r in rows:
        writer.writerow([r[k] for k in ("arm", "cell", "block", "ordinal", "warmup", "category", "case_id",
                         "request_id", "accounting_instance_id", "first", "preparation_ns")]
                        + [r["stages_ns"].get(k, "") for k in stages])
write("paired-deltas.json", pairs)
write("analysis.json", dict(status="OFFLINE_ES_SSE_DESCRIPTIVE_ANALYSIS_COMPLETE",
    original_outcome_unchanged=result["status"], requests=1440, measured=800, warmups=640,
    spans=len(spans), request_roots=len(roots), trace_coverage_complete=True,
    cells=cells, blocks=block_rows, categories=categories, cases=cases, es_sse_tail=tails,
    no_causal_claim=True, no_new_measurements=True, new_application_requests=0,
    external_calls=0, spend_usd="0"))
write("inputs.json", dict(schema="orq41-offline-inputs-v1", files_sha256=inputs,
    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
print(json.dumps(dict(status="OFFLINE_ES_SSE_DESCRIPTIVE_ANALYSIS_COMPLETE",
    span_count=len(spans), root_count=len(roots), matched_request_count=len(rows),
    top6_c1_categories=Counter(r["category"] for r in tails["c1"]["top10"][:6]),
    original_calibration="AA_CALIBRATION_FAIL", new_application_requests=0, spend_usd="0"), indent=2))
