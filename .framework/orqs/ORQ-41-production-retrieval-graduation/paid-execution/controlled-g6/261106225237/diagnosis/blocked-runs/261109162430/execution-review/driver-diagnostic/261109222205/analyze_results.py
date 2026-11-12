"""Check retained adapter records and describe observed cache transitions."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import statistics

OUT = Path(__file__).resolve().parent
PRIOR = OUT.parents[2]
sha = lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest = json.loads((OUT/"manifest.json").read_text())
worker = json.loads((OUT/"worker.json").read_text())
assert worker["status"] == "DRIVER_DIAGNOSTIC_COMPLETE"
assert len(worker["rows"]) == len(manifest["slots"]) == 30
assert worker["error"] is worker["dispose_error"] is None
assert manifest["controller_sha256"] == sha(OUT.parent/"run_driver_diagnostic.py")
assert manifest["worker_sha256"] == sha(OUT.parent/"driver_worker.py")
source_sql = (PRIOR/"execution-review/sql-diagnostic/261109212354/query-template.sql").read_text()
bind_order = []
def parameter(match):
    if match[1] not in bind_order:
        bind_order.append(match[1])
    return "$"+str(bind_order.index(match[1])+1)
expected_sql = re.sub(r":([a-z_]+)", parameter, source_sql)
records, names, pids = [], set(), set()
previous = None
for index, (row, slot) in enumerate(zip(worker["rows"],manifest["slots"])):
    assert all(row[k] == v for k,v in slot.items()) and row["status"] == "PASS"
    key = f'{index:02}-{slot["phase"]}-{slot["case_id"]}'
    admitted = json.loads((OUT/(key+"-admitted.json")).read_text())
    assert admitted["slot"] == slot and admitted["attempt"] == 1
    assert admitted["manifest_sha256"] == sha(OUT/"manifest.json")
    assert json.loads((OUT/(key+"-result.json")).read_text()) == row
    before, after = row["before"],row["after"]
    new = after["hybrid_cached"][0]
    old = before["hybrid_cached"]
    assert after["current_user"] == after["session_user"] == "rag_app"
    assert after["read_only"] == after["row_security"] == "on"
    assert after["plan_cache_mode"] == "auto" and after["tenant"] == slot["tenant_id"]
    assert after["superuser"] is after["bypass_rls"] is False
    assert new["statement"] == expected_sql and new["from_sql"] is False
    assert row["output_rows"] == slot["expected_rows"]
    if old:
        assert new["name"] == old[0]["name"]
        assert new["generic_plans"] + new["custom_plans"] == old[0]["generic_plans"] + old[0]["custom_plans"] + 1
    else:
        assert new["generic_plans"] + new["custom_plans"] == 1
    if previous and after["pid"] == previous["pid"]:
        assert old == previous["hybrid_cached"]
    mode = "generic" if new["generic_plans"] > (old[0]["generic_plans"] if old else 0) else "custom"
    assert mode == row["chosen_mode"]
    assert all(type(row[k]) is int and row[k] >= 0 for k in (
        "adapter_wall_ns","adapter_cpu_ns","checkout_wall_ns","checkout_cpu_ns","rollback_wall_ns","rollback_cpu_ns"))
    names.add(new["name"]);pids.add(after["pid"]);previous = after
    records.append(dict(index=index, phase=slot["phase"],case_id=slot["case_id"],
        category=slot["category"],mode=mode,pid=after["pid"],name=new["name"],
        parameter_types=new["parameter_types"],custom_plans=new["custom_plans"],
        generic_plans=new["generic_plans"],wall_ms=row["adapter_wall_ns"]/1e6,
        python_cpu_ms=row["adapter_cpu_ns"]/1e6,checkout_ms=row["checkout_wall_ns"]/1e6,
        output_rows=row["output_rows"],result_sha256=row["result_sha256"]))
summary = {}
for category in ("document","combined"):
    group=[r for r in records if r["phase"]=="diagnostic" and r["category"]==category]
    assert len(group)==5
    summary[category]=dict(n=5,wall_ms_mean=statistics.mean(r["wall_ms"] for r in group),
        wall_ms_min=min(r["wall_ms"] for r in group),wall_ms_max=max(r["wall_ms"] for r in group),
        python_cpu_ms_mean=statistics.mean(r["python_cpu_ms"] for r in group),
        python_cpu_ms_min=min(r["python_cpu_ms"] for r in group),
        python_cpu_ms_max=max(r["python_cpu_ms"] for r in group))
scope=json.loads((OUT/"scope-before.json").read_text())
assert len(scope)==500 and all(sha(Path(f))==v for f,v in scope.items())
pre=json.loads((OUT/"preflight.json").read_text())
post=json.loads((OUT/"postflight.json").read_text())
assert pre["database"]==post["unchanged_database"]
assert json.loads((OUT/"cleanup.json").read_text())["status"]=="STOPPED_DATA_RETAINED"
result=dict(status="REQUEST_FREE_DRIVER_RECORDS_VERIFIED",records=records,
    versions=worker["probe"]["versions"],mode_counts=dict(Counter(r["mode"] for r in records)),
    unique_backend_pids=len(pids),unique_hybrid_statement_names=len(names),
    inferred_types=sorted({r["parameter_types"] for r in records}),
    actual_bind_order=bind_order,actual_compiled_sql_sha256=hashlib.sha256(expected_sql.encode()).hexdigest(),
    diagnostics=summary,warmups=20,diagnostic_calls=10,select_executions=30,
    warmup_categories=dict(Counter(s["category"] for s in manifest["slots"][:20])),
    distinct_visible_result_hashes=len({r["result_sha256"] for r in records if r["output_rows"]==20}),
    no_causal_claim_about_historical_AA=True,original_AA_status="AA_CALIBRATION_FAIL",
    source_files_unchanged=500,new_sql_calls_in_analysis=0,provider_calls=0,spend_usd="0")
with (OUT/"analysis.json").open("x") as f:f.write(json.dumps(result,indent=2)+"\n")
print(json.dumps({k:result[k] for k in ("status","mode_counts","unique_backend_pids",
    "inferred_types","actual_bind_order","diagnostics","distinct_visible_result_hashes")},indent=2))
