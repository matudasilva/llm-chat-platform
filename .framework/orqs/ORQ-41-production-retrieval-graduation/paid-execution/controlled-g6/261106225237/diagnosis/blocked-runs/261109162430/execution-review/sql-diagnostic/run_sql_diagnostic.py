"""One authorized, request-free SQL diagnostic on a fresh isolated PG clone."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time

from experiments.production_graduation.gate_validation import blocked_latency as h
from experiments.production_graduation.gate_validation.aa_calibration_resources import canonical_schema
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

BASE = Path(__file__).resolve().parent
PRIOR = BASE.parents[1]
SOURCE = h.ROOT / "app/core/providers/pgvector_store.py"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]


def write(path, value):
    h.write_json(path, value)


def invoke(*args, data=None, timeout=60):
    p = subprocess.run(DOCKER + list(args), input=data, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError("Local diagnostic Docker command failed: " + args[0])
    return p.stdout


def sql(container, database, statement, *, role="orq41owner"):
    return invoke("exec", "-i", container, "psql", "-X", "-q", "-A", "-t",
                  "-v", "ON_ERROR_STOP=1", "-U", role, "-d", database, data=statement.encode()).decode()


def readonly(container, database, query, *, role="orq41owner", tenant=None):
    prefix = "BEGIN READ ONLY;\nSET LOCAL statement_timeout='30s';\n"
    if tenant is not None:
        prefix += "SET LOCAL app.tenant_id=" + h.quote(tenant) + ";\n"
    return sql(container, database, prefix + query + "\nROLLBACK;", role=role)


def extract_query():
    tree = ast.parse(SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PgVectorStore")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "hybrid_search")
    strings = [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)
               and isinstance(n.value, str) and "WITH semantic AS (" in n.value]
    assert len(strings) == 1
    rrf = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "_RRF_K" for t in n.targets))
    assert rrf == 60
    query = strings[0]
    assert set(re.findall(r":([a-z_]+)", query)) == {"query_embedding", "query_text", "top_k", "rrf_k"}
    return query, rrf


def freeze():
    check_p2()
    prior = json.loads((PRIOR / "plan.json").read_text())
    assert h.sha_file(PRIOR / "plan.json") == "b3d7cbe4aa4587ca20a3dadd79e2a10d7813981b8a33550d661c58af6f19026b"
    assert h.sha_file(PRIOR / "execution-review/receipt.json") == "0a1c5f52b10c02cbdd01e9bc407be5cb0a92533c3ded5c8b4114a29c9df2d72b"
    scope = json.loads((PRIOR / "execution-scope-before.json").read_text())
    assert len(scope) == 500 and all(h.sha_file(h.ROOT / f) == v for f, v in scope.items())
    casefile = h.ORQ / "paid-execution/cases.json"
    assert h.sha_file(casefile) == prior["support_files_sha256"][str(casefile.relative_to(h.ROOT))]
    cases = json.loads(casefile.read_text())["cases"]
    ordered = [next(c for c in cases if c["case_id"] == f"ES-{category}-{index:02}")
               for index in range(1, 6) for category in ("document", "combined")]
    assert len({c["case_id"] for c in ordered}) == 10
    assert all(c["language"] == "ES" and c["tenant_id"] == "orq37-t23" for c in ordered)
    query, rrf = extract_query()
    run_id = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    out = BASE / run_id
    out.mkdir(mode=0o700, exist_ok=False)
    h.private_write(out / "query-template.sql", query.encode())
    write(out / "scope-before.json", scope)
    bindings = {"query_embedding": "$1", "query_text": "$2", "top_k": "$3", "rrf_k": "$4"}
    prepared = re.sub(r":([a-z_]+)", lambda m: bindings[m[1]], query)
    h.private_write(out / "query-prepared.sql", prepared.encode())
    dump = h.ORQ / "corpus-snapshot/orq37-t23-corpus.pgdump"
    assert h.sha_file(dump) == "0334e3af47edf9c885093a6ad061390f6f85ba62517e56b94450339950599d4f"
    rows = [dict(case_id=c["case_id"], category=c["category"], tenant_id=c["tenant_id"],
                 query_text=c["message"], top_k=20, rrf_k=rrf) for c in ordered]
    manifest = dict(schema="orq41-request-free-sql-diagnostic-v1", run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(), not_a_gate=True,
        prior_plan_sha256=h.sha_file(PRIOR / "plan.json"), casefile_sha256=h.sha_file(casefile),
        postgres_image=prior["postgres_image"], container="orq41-sql-" + run_id + "-postgres",
        database="orq41_sql_" + run_id, schema_sha256=prior["source_schema_sha256"],
        source_postgres_id=json.loads((PRIOR / "execution-review/cleanup.json").read_text())["source_postgres_id"],
        locale=prior["database_locale"], source_sha256=h.sha_file(SOURCE),
        script_sha256=h.sha_file(Path(__file__)), sql_template_sha256=h.sha_file(out / "query-template.sql"),
        prepared_sql_sha256=h.sha_file(out / "query-prepared.sql"), corpus_dump_sha256=h.sha_file(dump),
        cases=rows, vector=[1.0]+[0.0]*1535,
        concurrency=1, case_attempts=1, warmups=0, query_statement_timeout_ms=30000,
        lock_timeout_ms=5000, prepared_parameter_types=["text", "text", "integer", "integer"],
        plan_cache_mode="unchanged auto; first prepared execution, no force_generic/custom",
        analyze_tables=list(h.TABLES), api_requests=0, external_calls=0, spend_usd="0",
        original_calibration_status="AA_CALIBRATION_FAIL", official_g6_status="CONTROLLED_G6_FAIL",
        limitations=["EXPLAIN timing overhead", "Fresh single prepared execution may differ from warmed asyncpg cache",
                     "No client/C1/per-request CPU reproduction; not comparable G6 timing"])
    write(out / "manifest.json", manifest)
    write(out / "authorization.json", dict(status="OPERATOR_AUTHORIZED_REQUEST_FREE_SQL_DIAGNOSTIC",
        operator_message="ok, avancemos con el planç",
        antecedent="Fresh disposable clone; ten ES document/combined exact-query cases; read-only bounded EXPLAIN; no application/provider requests.",
        manifest_sha256=h.sha_file(out / "manifest.json"), max_query_executions=10,
        services_authorized=["one fresh isolated PostgreSQL"], app_or_harness_changes=False,
        repetitions_authorized=0, external_calls_authorized=0, spend_usd="0"))
    print(out.relative_to(h.ROOT))


def schema_hash(container, database):
    raw = invoke("exec", container, "pg_dump", "-U", "orq41owner", "-d", database, "--schema-only")
    return hashlib.sha256(canonical_schema(raw)).hexdigest()


def identity(container, database, manifest):
    meta = json.loads((h.ORQ / "corpus-snapshot/corpus-snapshot.json").read_text())["identity"]
    projection = meta["snapshot_content_projection"].split("  (psql")[0]
    digest = hashlib.sha256(readonly(container, database, "COPY ("+projection+") TO STDOUT;").encode()).hexdigest()
    assert digest == meta["snapshot_content_sha256"]
    counts = readonly(container, database, "SELECT (SELECT count(*) FROM documents),"
        "(SELECT count(*) FROM chunks),(SELECT count(*) FROM conversations),(SELECT count(*) FROM messages),"
        "(SELECT count(*) FROM usage_events),(SELECT count(*) FROM rag_request_metrics);").strip()
    assert counts == "124|2146|0|0|0|0", counts
    assert schema_hash(container, database) == manifest["schema_sha256"]
    settings = json.loads(readonly(container, database, h.SETTINGS_SQL))
    expected = json.loads((PRIOR / "preparation.json").read_text())["analyses"][0]["settings"]
    assert settings == expected
    rls = {}
    for tenant in ("orq37-t23", "", "sql-diagnostic-unknown"):
        n = int(readonly(container, database, "SELECT count(*) FROM chunks;", role="rag_app", tenant=tenant))
        assert n == (2146 if tenant == "orq37-t23" else 0)
        rls[tenant] = n
    return dict(corpus_content_sha256=digest, counts=counts, settings=settings, rls=rls,
                schema_sha256=manifest["schema_sha256"])


def decode_documents(raw):
    documents, decoder, rest = [], json.JSONDecoder(), raw.strip()
    while rest:
        value, index = decoder.raw_decode(rest)
        documents.append(value)
        rest = rest[index:].strip()
    return documents


def execute(out):
    check_p2()
    out = out.resolve()
    assert not (out / "execution-started.json").exists() and not (out / "execution-started.json").is_symlink(), "Never resume an admitted diagnostic"
    manifest = json.loads((out / "manifest.json").read_text())
    authorization = json.loads((out / "authorization.json").read_text())
    assert authorization["manifest_sha256"] == h.sha_file(out / "manifest.json")
    assert authorization["status"] == "OPERATOR_AUTHORIZED_REQUEST_FREE_SQL_DIAGNOSTIC"
    assert manifest["script_sha256"] == h.sha_file(Path(__file__))
    assert manifest["source_sha256"] == h.sha_file(SOURCE)
    assert manifest["prepared_sql_sha256"] == h.sha_file(out / "query-prepared.sql")
    scope = json.loads((out / "scope-before.json").read_text())
    assert all(h.sha_file(h.ROOT / f) == v for f, v in scope.items())
    assert shutil.disk_usage(h.ROOT).free > 5*1024**3
    pg, db = manifest["container"], manifest["database"]
    assert not invoke("ps", "-a", "--filter", "name=^/"+pg+"$", "--format", "{{.ID}}").strip()
    assert json.loads(invoke("image", "inspect", manifest["postgres_image"]))[0]["Id"] == manifest["postgres_image"]
    source = json.loads(invoke("inspect", "orq41-env-pg"))[0]
    assert source["Id"] == manifest["source_postgres_id"] and source["State"]["Running"]
    ddl = invoke("exec", "orq41-env-pg", "pg_dump", "-U", "orq41owner", "-d", "orq41", "--schema-only")
    assert hashlib.sha256(canonical_schema(ddl)).hexdigest() == manifest["schema_sha256"]
    private = Path(tempfile.mkdtemp(prefix="orq41-sql-"+manifest["run_id"]+"-"))
    private.chmod(0o700)
    values = {k:secrets.token_hex(24) for k in ("POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD",
        "POSTGRES_EVALUATION_PASSWORD", "POSTGRES_OPS_PASSWORD", "POSTGRES_OPS_RETENTION_PASSWORD")}
    values.update(POSTGRES_USER="orq41owner", POSTGRES_DB="orq41sql_bootstrap")
    h.private_write(private / "postgres.env", "".join(k+"="+v+"\n" for k,v in sorted(values.items())).encode())
    write(out / "execution-started.json", dict(manifest_sha256=h.sha_file(out / "manifest.json"),
        started_at=datetime.now(timezone.utc).isoformat(), private_state=str(private)))
    results, created, error, cleanup = [], False, None, None
    try:
        invoke("create", "--pull=never", "--name", pg, "--network", "none", "--cpus=2",
            "--cpuset-cpus", "4,6", "--memory=2147483648", "--memory-swap=2147483648",
            "--env-file", str(private / "postgres.env"), "--mount",
            f"type=bind,src={h.ROOT/'scripts/postgres-init'},dst=/docker-entrypoint-initdb.d,readonly",
            manifest["postgres_image"])
        created = True
        invoke("start", pg)
        deadline = time.monotonic()+60
        while True:
            probe = subprocess.run(DOCKER+["exec", pg, "sh", "-c",
                'test "$(cat /proc/1/comm)" = postgres && pg_isready -h 127.0.0.1 -U orq41owner -d orq41sql_bootstrap'],
                capture_output=True, timeout=5)
            if probe.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Fresh diagnostic PostgreSQL readiness timeout")
            time.sleep(.25)
        info = json.loads(invoke("inspect", pg))[0]
        limits = info["HostConfig"]
        assert info["Image"] == manifest["postgres_image"] and limits["NetworkMode"] == "none"
        assert not limits.get("PortBindings") and limits["CpusetCpus"] == "4,6"
        assert limits["Memory"] == limits["MemorySwap"] == 2147483648 and limits["NanoCpus"] == 2000000000
        locale = manifest["locale"]
        sql(pg, "orq41sql_bootstrap", "CREATE DATABASE "+db+" OWNER orq41owner TEMPLATE template0 ENCODING "
            +h.quote(locale["encoding"])+" LC_COLLATE "+h.quote(locale["collate"])+" LC_CTYPE "
            +h.quote(locale["ctype"])+" LOCALE_PROVIDER libc;")
        invoke("exec", "-i", pg, "psql", "-X", "-v", "ON_ERROR_STOP=1", "--single-transaction",
               "-U", "orq41owner", "-d", db, data=ddl)
        sql(pg, db, "INSERT INTO alembic_version VALUES ('e4b7f21c9a06');")
        dump = h.ORQ / "corpus-snapshot/orq37-t23-corpus.pgdump"
        assert h.sha_file(dump) == manifest["corpus_dump_sha256"]
        invoke("exec", "-i", pg, "pg_restore", "-U", "orq41owner", "-d", db,
               "--data-only", "--single-transaction", data=dump.read_bytes())
        analyses = []
        for table in manifest["analyze_tables"]:
            statement = 'ANALYZE "public"."'+table+'";'
            sql(pg, db, statement)
            analyses.append(statement)
        before = identity(pg, db, manifest)
        write(out / "preflight.json", dict(status="REQUEST_FREE_SQL_PREFLIGHT_PASS",
            database=before, analyses=analyses, postgres_id=info["Id"], image=info["Image"],
            network_mode=limits["NetworkMode"], no_published_ports=True,
            effective_postgres_resources=h.aa.pg_resources(pg), api_requests=0, external_calls=0))
        prepared = (out / "query-prepared.sql").read_text()
        vector = "["+",".join(str(float(v)) for v in manifest["vector"])+"]"
        for case in manifest["cases"]:
            cid = case["case_id"]
            # Session-local PREPARE and exactly one execution; no app/observer call.
            header = ("BEGIN READ ONLY;\nSET LOCAL statement_timeout='30s';\n"
                "SET LOCAL lock_timeout='5s';\nSET LOCAL app.tenant_id="+h.quote(case["tenant_id"])+";\n"
                "PREPARE orq41_diagnostic(text,text,integer,integer) AS "+prepared+";\n")
            prepared_stats = ("(SELECT json_build_object('generic_plans',generic_plans,'custom_plans',custom_plans,"
                "'parameter_types',parameter_types::text) FROM pg_prepared_statements WHERE name='orq41_diagnostic')")
            metadata = ("SELECT json_build_object('current_user',current_user,'session_user',session_user,"
                "'read_only',current_setting('transaction_read_only'),'row_security',current_setting('row_security'),"
                "'tenant',current_setting('app.tenant_id'),'statement_timeout',current_setting('statement_timeout'),"
                "'superuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),"
                "'bypass_rls',(SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user),"
                "'settings',("+h.SETTINGS_SQL.rstrip(";")+"),'prepared_before',"+prepared_stats+");\n")
            explain = ("EXPLAIN (ANALYZE TRUE, BUFFERS TRUE, SETTINGS TRUE, FORMAT JSON) EXECUTE orq41_diagnostic("
                +h.quote(vector)+","+h.quote(case["query_text"])+","+str(case["top_k"])+","+str(case["rrf_k"])+");\n")
            program = header+metadata+explain+"SELECT json_build_object('prepared_after',"+prepared_stats+");\nROLLBACK;\n"
            h.private_write(out / (cid+".sql"), program.encode())
            write(out / (cid+"-admitted.json"), dict(case_id=cid, manifest_sha256=h.sha_file(out / "manifest.json"),
                sql_sha256=h.sha_file(out / (cid+".sql")), attempt=1, admitted_at=datetime.now(timezone.utc).isoformat()))
            response = subprocess.run(DOCKER+["exec", "-i", "-e", "PGAPPNAME=orq41-sql-"+cid,
                pg, "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-U", "rag_app", "-d", db],
                input=program.encode(), capture_output=True, timeout=45)
            h.private_write(out / (cid+"-stdout.log"), response.stdout)
            h.private_write(out / (cid+"-stderr.log"), response.stderr)
            if response.returncode:
                results.append(dict(case_id=cid, status="FAILED", exit_code=response.returncode, attempt=1))
                active = int(readonly(pg, db, "SELECT count(*) FROM pg_stat_activity WHERE application_name="
                    +h.quote("orq41-sql-"+cid)+" AND state<>'idle';").strip())
                if active:
                    raise RuntimeError("Failed SQL case still unresolved; stop admission")
                continue
            docs = decode_documents(response.stdout.decode())
            assert len(docs) == 3
            meta, plan, after = docs
            assert meta["current_user"] == meta["session_user"] == "rag_app"
            assert meta["read_only"] == meta["row_security"] == "on" and meta["tenant"] == case["tenant_id"]
            assert not meta["superuser"] and not meta["bypass_rls"]
            assert meta["settings"] == before["settings"]
            assert meta["prepared_before"]["generic_plans"] == meta["prepared_before"]["custom_plans"] == 0
            modes = after["prepared_after"]
            assert modes["generic_plans"]+modes["custom_plans"] == 1
            assert len(plan) == 1 and plan[0]["Plan"]["Actual Rows"] == case["top_k"]
            row = dict(case_id=cid, category=case["category"], status="PASS", attempt=1,
                metadata=meta, prepared_after=modes, explain=plan[0],
                stdout_sha256=h.sha_file(out / (cid+"-stdout.log")), stderr_sha256=h.sha_file(out / (cid+"-stderr.log")))
            write(out / (cid+"-result.json"), row)
            results.append(row)
        after = identity(pg, db, manifest)
        assert before == after
        assert all(h.sha_file(h.ROOT/f) == v for f,v in scope.items())
        write(out / "postflight.json", dict(status="REQUEST_FREE_SQL_POSTFLIGHT_PASS",
            unchanged_database=after, protected_files_unchanged=len(scope), api_requests=0,
            usage_writes=0, external_calls=0, spend_usd="0"))
    except Exception as exc:
        error = type(exc).__name__+": "+str(exc)[:180]
    finally:
        if created:
            try:
                invoke("stop", "--time", "10", pg, timeout=25)
                state = json.loads(invoke("inspect", pg))[0]
                assert not state["State"]["Running"]
                cleanup = dict(status="STOPPED_DATA_RETAINED", container=pg, id=state["Id"], no_resume=True)
            except Exception as exc:
                cleanup = dict(status="FAILED", error=type(exc).__name__)
        else:
            cleanup = dict(status="NO_CONTAINER_CREATED")
        write(out / "cleanup.json", cleanup)
    status = ("REQUEST_FREE_SQL_DIAGNOSTIC_COMPLETE" if not error and len(results) == 10
              and all(r["status"] == "PASS" for r in results) and cleanup["status"] == "STOPPED_DATA_RETAINED"
              else "REQUEST_FREE_SQL_DIAGNOSTIC_FAILED")
    admitted = sorted(f.name.removesuffix("-admitted.json") for f in out.glob("*-admitted.json"))
    unresolved = sorted(set(admitted)-{r["case_id"] for r in results})
    write(out / "result.json", dict(status=status, error=error, cases_attempted=len(admitted),
        cases_resolved=len(results), unresolved_case_ids=unresolved,
        cases_passed=sum(r["status"]=="PASS" for r in results), cases_failed=sum(r["status"]!="PASS" for r in results),
        manifest_sha256=h.sha_file(out / "manifest.json"), results=results,
        no_retries=True, application_requests=0, provider_calls=0, spend_usd="0",
        official_g6_status="CONTROLLED_G6_FAIL", paid_admission="BLOCKED_CONTROLLED_G6_FAIL"))
    print(status)
    if status != "REQUEST_FREE_SQL_DIAGNOSTIC_COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze", action="store_true")
    action.add_argument("--execute", type=Path)
    args = parser.parse_args()
    if args.freeze:
        freeze()
    else:
        execute(args.execute)
