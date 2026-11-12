"""Verify retained SQL records and summarize them without new database calls."""
import hashlib
import json
from pathlib import Path
import statistics

OUT = Path(__file__).resolve().parent
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
manifest = json.loads((OUT / "manifest.json").read_text())
result = json.loads((OUT / "result.json").read_text())
assert result["status"] == "REQUEST_FREE_SQL_DIAGNOSTIC_COMPLETE"
assert result["cases_attempted"] == result["cases_passed"] == result["cases_resolved"] == 10
assert not result["unresolved_case_ids"] and result["cases_failed"] == 0
assert result["manifest_sha256"] == sha(OUT / "manifest.json")
assert manifest["script_sha256"] == sha(OUT.parent / "run_sql_diagnostic.py")
assert manifest["sql_template_sha256"] == sha(OUT / "query-template.sql")
assert manifest["prepared_sql_sha256"] == sha(OUT / "query-prepared.sql")


def walk(node, path="root"):
    yield path, node
    for i, child in enumerate(node.get("Plans", [])):
        yield from walk(child, path + "/" + str(i))


def shape(node):
    return dict(node=node["Node Type"], relation=node.get("Relation Name"),
                index=node.get("Index Name"), join=node.get("Join Type"),
                children=[shape(c) for c in node.get("Plans", [])])


rows = []
for expected, retained in zip(manifest["cases"], result["results"]):
    cid = expected["case_id"]
    assert retained["case_id"] == cid and retained["attempt"] == 1
    admitted = json.loads((OUT / (cid + "-admitted.json")).read_text())
    assert admitted["manifest_sha256"] == sha(OUT / "manifest.json")
    assert admitted["sql_sha256"] == sha(OUT / (cid + ".sql"))
    program = (OUT / (cid + ".sql")).read_text()
    assert program.count("EXPLAIN (ANALYZE TRUE") == 1
    assert program.startswith("BEGIN READ ONLY;") and program.endswith("ROLLBACK;\n")
    assert sha(OUT / (cid + "-stdout.log")) == retained["stdout_sha256"]
    assert sha(OUT / (cid + "-stderr.log")) == retained["stderr_sha256"]
    assert (OUT / (cid + "-stderr.log")).read_bytes() == b""
    raw, decoder, docs = (OUT / (cid + "-stdout.log")).read_text().strip(), json.JSONDecoder(), []
    while raw:
        value, end = decoder.raw_decode(raw)
        docs.append(value)
        raw = raw[end:].strip()
    assert len(docs) == 3 and docs[0] == retained["metadata"]
    assert docs[1] == [retained["explain"]] and docs[2]["prepared_after"] == retained["prepared_after"]
    meta, explain = retained["metadata"], retained["explain"]
    assert meta["current_user"] == meta["session_user"] == "rag_app"
    assert meta["row_security"] == meta["read_only"] == "on"
    assert meta["tenant"] == expected["tenant_id"] and not meta["bypass_rls"] and not meta["superuser"]
    assert retained["prepared_after"]["custom_plans"] == 1
    assert retained["prepared_after"]["generic_plans"] == 0
    root = explain["Plan"]
    assert root["Actual Rows"] == expected["top_k"] == 20
    scans = [dict(path=path, relation=node.get("Relation Name"), node=node["Node Type"],
                  actual_rows=node["Actual Rows"], actual_loops=node["Actual Loops"],
                  actual_total_ms=node["Actual Total Time"], removed=node.get("Rows Removed by Filter", 0))
             for path, node in walk(root) if node["Node Type"].endswith("Scan") and node.get("Relation Name") == "chunks"]
    assert len(scans) == 2 and all(n["node"] == "Seq Scan" for n in scans)
    assert sorted(n["actual_rows"] for n in scans) == [0, 2146]
    assert all(root.get(k, 0) == 0 for k in ("Shared Read Blocks", "Temp Read Blocks", "Temp Written Blocks", "Shared Written Blocks"))
    rows.append(dict(case_id=cid, category=expected["category"], planning_ms=explain["Planning Time"],
        execution_ms=explain["Execution Time"], output_rows=20, prepared_mode="custom",
        plan_shape_sha256=hashlib.sha256(json.dumps(shape(root), sort_keys=True).encode()).hexdigest(),
        scans=scans, root_buffer_hits=root["Shared Hit Blocks"],
        root_buffer_reads=root["Shared Read Blocks"], temporary_writes=root["Temp Written Blocks"]))
assert len({r["plan_shape_sha256"] for r in rows}) == 1
before = json.loads((OUT / "preflight.json").read_text())["database"]
after = json.loads((OUT / "postflight.json").read_text())["unchanged_database"]
assert before == after
scope = json.loads((OUT / "scope-before.json").read_text())
assert len(scope) == 500 and all(sha(Path(f)) == v for f, v in scope.items())
cleanup = json.loads((OUT / "cleanup.json").read_text())
assert cleanup["status"] == "STOPPED_DATA_RETAINED" and cleanup["no_resume"] is True
summary = dict(status="SQL_DIAGNOSTIC_RETAINED_EVIDENCE_VERIFIED", rows=rows,
    categories={category:dict(n=5, mean_execution_ms=statistics.mean(r["execution_ms"] for r in rows if r["category"] == category),
        min_execution_ms=min(r["execution_ms"] for r in rows if r["category"] == category),
        max_execution_ms=max(r["execution_ms"] for r in rows if r["category"] == category))
        for category in ("document", "combined")},
    one_shape_all10=True, custom_plans=10, generic_plans=0, query_attempts=10,
    source_files_unchanged=500, unchanged_database=after, cleanup=cleanup,
    no_original_runtime_causality_claim=True, new_database_calls_in_verification=0,
    api_requests=0, provider_calls=0, spend_usd="0", original_calibration="AA_CALIBRATION_FAIL")
with (OUT / "analysis.json").open("x") as f:
    f.write(json.dumps(summary, indent=2) + "\n")
print(json.dumps({k:summary[k] for k in ("status", "categories", "one_shape_all10",
    "custom_plans", "generic_plans", "query_attempts", "source_files_unchanged")}, indent=2))
