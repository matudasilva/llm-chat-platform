"""Verify retained forced-mode records and compare matched server plans offline."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics

OUT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
m=json.loads((OUT/"manifest.json").read_text())
result=json.loads((OUT/"result.json").read_text())
assert result["status"]=="REQUEST_FREE_PLAN_COMPARISON_COMPLETE"
assert result["cases_admitted"]==result["cases_resolved"]==20 and result["cases_failed"]==0
assert result["manifest_sha256"]==sha(OUT/"manifest.json")
assert m["controller_sha256"]==sha(OUT.parent/"run_plan_comparison.py")
assert m["compiled_sql_sha256"]==sha(OUT/"compiled-query.sql")
pre=json.loads((OUT/"preflight.json").read_text())["database"]


def walk(node,path="root"):
    yield path,node
    for i,c in enumerate(node.get("Plans",[])):
        yield from walk(c,path+"/"+str(i))


groups=defaultdict(dict);rows=[];pids=set()
for index,(slot,row) in enumerate(zip(m["slots"],result["rows"])):
    key=f'{index:02}-{slot["case_id"]}-{slot["mode"]}'
    assert row["index"]==index and row["slot"]==slot and row["status"]=="PASS" and row["attempt"]==1
    admitted=json.loads((OUT/(key+"-admitted.json")).read_text())
    assert admitted["slot"]==slot and admitted["attempt"]==1 and admitted["sql_sha256"]==sha(OUT/(key+".sql"))
    assert admitted["manifest_sha256"]==sha(OUT/"manifest.json")
    assert json.loads((OUT/(key+"-result.json")).read_text())==row
    assert sha(OUT/(key+"-stdout.log"))==row["stdout_sha256"]
    assert sha(OUT/(key+"-stderr.log"))==row["stderr_sha256"]
    assert (OUT/(key+"-stderr.log")).read_bytes()==b""
    raw=(OUT/(key+"-stdout.log")).read_text().strip();docs=[];decoder=json.JSONDecoder()
    while raw:
        obj,end=decoder.raw_decode(raw);docs.append(obj);raw=raw[end:].strip()
    assert len(docs)==3 and docs[0]==row["metadata"] and docs[1]==[row["explain"]]
    assert docs[2]["prepared_after"]==row["prepared_after"]
    meta=row["metadata"];counts=row["prepared_after"]
    assert meta["current_user"]==meta["session_user"]=="rag_app"
    assert meta["read_only"]==meta["row_security"]=="on" and meta["tenant"]==slot["tenant_id"]
    assert meta["superuser"] is meta["bypass_rls"] is False
    assert meta["settings"]["plan_cache_mode"]==slot["mode"]
    assert dict(meta["settings"],plan_cache_mode="auto")==pre["settings"]
    assert meta["prepared_before"]["custom_plans"]==meta["prepared_before"]["generic_plans"]==0
    assert counts["parameter_types"]=="{vector,bigint,text,bigint}" and counts["from_sql"] is True
    target="generic_plans" if slot["mode"]=="force_generic_plan" else "custom_plans"
    assert counts[target]==1 and counts["custom_plans"]+counts["generic_plans"]==1
    pids.add(meta["pid"])
    e=row["explain"];root=e["Plan"];assert root["Actual Rows"]==20
    scans=[dict(path=path,node_type=n["Node Type"],actual_rows=n["Actual Rows"],
        loops=n["Actual Loops"],elapsed_ms=n["Actual Total Time"],
        rows_removed=n.get("Rows Removed by Filter",0),filter=n.get("Filter",""),
        shared_hits=n.get("Shared Hit Blocks",0),shared_reads=n.get("Shared Read Blocks",0))
        for path,n in walk(root) if n.get("Relation Name")=="chunks"]
    keyword=[s for s in scans if "search_vector" in s["filter"]]
    semantic=[s for s in scans if "search_vector" not in s["filter"]]
    assert len(scans)==2 and len(keyword)==len(semantic)==1
    assert keyword[0]["actual_rows"]==0 and keyword[0]["rows_removed"]==2146 and keyword[0]["loops"]==1
    assert semantic[0]["actual_rows"]==2146
    r=dict(index=index,pair=slot["pair"],case_id=slot["case_id"],category=slot["category"],
        mode=slot["mode"],planning_ms=e["Planning Time"],execution_ms=e["Execution Time"],
        scans=scans,keyword=keyword[0],semantic=semantic[0],root_shared_reads=root.get("Shared Read Blocks",0),
        temp_reads=root.get("Temp Read Blocks",0),temp_writes=root.get("Temp Written Blocks",0))
    rows.append(r);assert slot["mode"] not in groups[slot["case_id"]]
    groups[slot["case_id"]][slot["mode"]]=r
assert len(pids)==20 and len(groups)==10
pairs=[]
for case,modes in groups.items():
    c,g=modes["force_custom_plan"],modes["force_generic_plan"]
    assert c["category"]==g["category"]
    pairs.append(dict(case_id=case,category=c["category"],custom_execution_ms=c["execution_ms"],
        generic_execution_ms=g["execution_ms"],ratio=g["execution_ms"]/c["execution_ms"],
        execution_difference_ms=g["execution_ms"]-c["execution_ms"],
        custom_keyword_ms=c["keyword"]["elapsed_ms"],generic_keyword_ms=g["keyword"]["elapsed_ms"],
        custom_semantic_ms=c["semantic"]["elapsed_ms"],generic_semantic_ms=g["semantic"]["elapsed_ms"],
        custom_keyword_filter=c["keyword"]["filter"],generic_keyword_filter=g["keyword"]["filter"],
        generic_has_parameterized_tsquery="plainto_tsquery" in g["keyword"]["filter"] and "$3" in g["keyword"]["filter"],
        custom_has_literal_tsquery="::tsquery" in c["keyword"]["filter"] and "plainto_tsquery" not in c["keyword"]["filter"]))
categories={}
for category in ("document","combined"):
    data=[p for p in pairs if p["category"]==category]
    categories[category]={field:dict(min=min(p[field] for p in data),max=max(p[field] for p in data),
        mean=statistics.mean(p[field] for p in data)) for field in (
        "custom_execution_ms","generic_execution_ms","custom_keyword_ms","generic_keyword_ms")}
scope=json.loads((OUT/"scope-before.json").read_text())
assert len(scope)==500 and all(sha(Path(f))==v for f,v in scope.items())
assert json.loads((OUT/"postflight.json").read_text())["unchanged_database"]==pre
assert pre["settings"]["plan_cache_mode"]=="auto"
assert json.loads((OUT/"cleanup.json").read_text())["status"]=="STOPPED_DATA_RETAINED"
analysis=dict(status="PLAN_COMPARISON_RETAINED_RECORDS_VERIFIED",pairs=pairs,rows=rows,categories=categories,
    unique_backend_pids=len(pids),twenty_readonly_executions=True,
    all_generic_slower=all(p["ratio"]>1 for p in pairs),
    all_generic_parameterized_filter=all(p["generic_has_parameterized_tsquery"] for p in pairs),
    all_custom_literal_filter=all(p["custom_has_literal_tsquery"] for p in pairs),
    no_shared_reads=all(r["root_shared_reads"]==0 for r in rows),
    no_temp_io=all(r["temp_reads"]==r["temp_writes"]==0 for r in rows),
    source_files_unchanged=500,scope_limit="Mode order coupled to category; R=1, direct server instrumentation; original AA cause not certified",
    exact_function_call_count_measured=False,no_new_sql_in_analysis=True,
    api_requests=0,provider_calls=0,spend_usd="0",original_AA_status="AA_CALIBRATION_FAIL")
with (OUT/"analysis.json").open("x") as f:f.write(json.dumps(analysis,indent=2)+"\n")
print(json.dumps({k:analysis[k] for k in ("status","categories","all_generic_slower",
    "all_generic_parameterized_filter","all_custom_literal_filter","no_shared_reads","no_temp_io")},indent=2))
