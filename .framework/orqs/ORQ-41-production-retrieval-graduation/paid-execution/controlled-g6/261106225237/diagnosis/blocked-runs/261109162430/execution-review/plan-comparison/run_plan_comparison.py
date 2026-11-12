"""Twenty approved request-free custom/generic EXPLAIN executions on fresh PG."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

from experiments.production_graduation.gate_validation import blocked_latency as h
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

BASE = Path(__file__).resolve().parent
PRIOR = BASE.parents[1]
DRIVER = BASE.parent / "driver-diagnostic/261109222205"
COMMON = BASE.parent / "sql-diagnostic/run_sql_diagnostic.py"
assert h.sha_file(COMMON) == "197edfcb2e295c5aa6a04727596923da28accf6a2e22c36473a2d45a8af6fddf"
spec = importlib.util.spec_from_file_location("retained_plan_sql_helpers", COMMON)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
MODES = ("force_custom_plan", "force_generic_plan")


def freeze():
    check_p2()
    old = json.loads((DRIVER / "completion.json").read_text())
    assert all(h.sha_file(DRIVER/f) == v for f,v in old["artifacts_sha256"].items())
    assert h.sha_file(DRIVER/"next-proposal.md") == "e780546765695bfb14f5827e9c5f5ac3f9f0fdb6af0769a2c9f9e2aa601d3d7a"
    assert h.sha_file(DRIVER/"compiled-query.sql") == "baf73363e8bc6736ee0713ec99f0872ce3b6e89f16c6acaee3d76237caf1df4c"
    prior = json.loads((PRIOR/"plan.json").read_text())
    assert h.sha_file(PRIOR/"plan.json") == "b3d7cbe4aa4587ca20a3dadd79e2a10d7813981b8a33550d661c58af6f19026b"
    scope = json.loads((PRIOR/"execution-scope-before.json").read_text())
    assert len(scope) == 500 and all(h.sha_file(h.ROOT/f) == v for f,v in scope.items())
    driver = json.loads((DRIVER/"manifest.json").read_text())
    analysis = json.loads((DRIVER/"analysis.json").read_text())
    assert analysis["inferred_types"] == ["{vector,bigint,text,bigint}"]
    assert analysis["actual_bind_order"] == ["query_embedding","top_k","query_text","rrf_k"]
    targets = [s for s in driver["slots"] if s["phase"] == "diagnostic"]
    assert len(targets) == 10 and len({s["case_id"] for s in targets}) == 10
    slots = []
    for index, case in enumerate(targets):
        order = MODES if index % 2 == 0 else MODES[::-1]
        for mode in order:
            slots.append(dict(pair=index+1,case_id=case["case_id"],category=case["category"],
                tenant_id=case["tenant_id"],query_text=case["query_text"],mode=mode,top_k=20,rrf_k=60))
    run_id = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    out = BASE/run_id
    out.mkdir(mode=0o700,exist_ok=False)
    h.private_write(out/"compiled-query.sql",(DRIVER/"compiled-query.sql").read_bytes())
    h.write_json(out/"scope-before.json",scope)
    manifest = dict(schema="orq41-request-free-plan-comparison-v1",run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),not_a_gate=True,
        slots=slots,hybrid_executions=20,case_pairs=10,concurrency=1,repetitions=1,
        attempts_per_case_mode=1,warmups=0,prepared_types=["vector","bigint","text","bigint"],
        actual_bind_order=analysis["actual_bind_order"],vector=driver["vector"],
        compiled_sql_sha256=h.sha_file(out/"compiled-query.sql"),
        driver_manifest_sha256=h.sha_file(DRIVER/"manifest.json"),
        proposal_sha256=h.sha_file(DRIVER/"next-proposal.md"),
        controller_sha256=h.sha_file(Path(__file__)),common_sha256=h.sha_file(COMMON),
        postgres_image=prior["postgres_image"],container="orq41-plans-"+run_id+"-postgres",
        database="orq41_plans_"+run_id,schema_sha256=prior["source_schema_sha256"],
        locale=prior["database_locale"],source_postgres_id=driver["source_postgres_id"],
        corpus_dump_sha256=driver["corpus_dump_sha256"],statement_timeout_s=30,lock_timeout_s=5,
        transaction_read_only=True,plan_modes_only_transaction_local=True,
        limitation="Document cases custom-first, combined generic-first under the approved order; category/order confounded.",
        api_requests=0,provider_calls=0,spend_usd="0",original_calibration="AA_CALIBRATION_FAIL")
    h.write_json(out/"manifest.json",manifest)
    h.write_json(out/"authorization.json",dict(status="OPERATOR_AUTHORIZED_REQUEST_FREE_PLAN_COMPARISON",
        operator_message="continuar",manifest_sha256=h.sha_file(out/"manifest.json"),
        proposal_sha256=manifest["proposal_sha256"],max_hybrid_executions=20,
        permitted_local_modes=list(MODES),runtime_mode_must_remain="auto",
        app_or_existing_harness_changes=False,extra_repeats=False,
        external_calls_authorized=0,paid_requests_authorized=0,spend_usd="0"))
    print(out.relative_to(h.ROOT))


def case_program(query,vector,slot):
    assert slot["mode"] in MODES
    prepared_stats = ("(SELECT json_build_object('generic_plans',generic_plans,'custom_plans',custom_plans,"
        "'parameter_types',CAST(parameter_types AS text),'from_sql',from_sql)"
        " FROM pg_prepared_statements WHERE name='orq41_compare')")
    header = ("BEGIN READ ONLY;\nSET LOCAL statement_timeout='30s';\nSET LOCAL lock_timeout='5s';\n"
        "SET LOCAL app.tenant_id="+h.quote(slot["tenant_id"])+";\n"
        "SET LOCAL plan_cache_mode="+h.quote(slot["mode"])+";\n"
        "PREPARE orq41_compare(vector,bigint,text,bigint) AS "+query+";\n")
    metadata = ("SELECT json_build_object('pid',pg_backend_pid(),'current_user',current_user,"
        "'session_user',session_user,'read_only',current_setting('transaction_read_only'),"
        "'row_security',current_setting('row_security'),'tenant',current_setting('app.tenant_id'),"
        "'superuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),"
        "'bypass_rls',(SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user),"
        "'settings',("+h.SETTINGS_SQL.rstrip(";")+"),'prepared_before',"+prepared_stats+");\n")
    explain = ("EXPLAIN (ANALYZE TRUE, BUFFERS TRUE, SETTINGS TRUE, FORMAT JSON) EXECUTE orq41_compare("
        +h.quote(vector)+","+str(slot["top_k"])+","+h.quote(slot["query_text"])+","+str(slot["rrf_k"])+");\n")
    return header+metadata+explain+"SELECT json_build_object('prepared_after',"+prepared_stats+");\nROLLBACK;\n"


def execute(out):
    check_p2()
    out=out.resolve()
    assert not (out/"execution-started.json").exists() and not (out/"execution-started.json").is_symlink()
    m=json.loads((out/"manifest.json").read_text())
    auth=json.loads((out/"authorization.json").read_text())
    assert auth["status"]=="OPERATOR_AUTHORIZED_REQUEST_FREE_PLAN_COMPARISON"
    assert auth["manifest_sha256"]==h.sha_file(out/"manifest.json")
    assert m["controller_sha256"]==h.sha_file(Path(__file__)) and m["compiled_sql_sha256"]==h.sha_file(out/"compiled-query.sql")
    scope=json.loads((out/"scope-before.json").read_text())
    assert all(h.sha_file(h.ROOT/f)==v for f,v in scope.items())
    assert len(m["slots"])==20 and shutil.disk_usage(h.ROOT).free>5*1024**3
    pg,db=m["container"],m["database"]
    assert not common.invoke("ps","-a","--filter","name=^/"+pg+"$","--format","{{.ID}}").strip()
    assert json.loads(common.invoke("image","inspect",m["postgres_image"]))[0]["Id"]==m["postgres_image"]
    source=json.loads(common.invoke("inspect","orq41-env-pg"))[0]
    assert source["State"]["Running"] and source["Id"]==m["source_postgres_id"]
    ddl=common.invoke("exec","orq41-env-pg","pg_dump","-U","orq41owner","-d","orq41","--schema-only")
    assert hashlib.sha256(common.canonical_schema(ddl)).hexdigest()==m["schema_sha256"]
    private=Path(tempfile.mkdtemp(prefix="orq41-plans-"+m["run_id"]+"-"))
    private.chmod(0o700)
    env={k:secrets.token_hex(24) for k in ("POSTGRES_PASSWORD","POSTGRES_APP_PASSWORD",
        "POSTGRES_EVALUATION_PASSWORD","POSTGRES_OPS_PASSWORD","POSTGRES_OPS_RETENTION_PASSWORD")}
    env.update(POSTGRES_USER="orq41owner",POSTGRES_DB="orq41sql_bootstrap")
    h.private_write(private/"postgres.env","".join(k+"="+v+"\n" for k,v in sorted(env.items())).encode())
    h.write_json(out/"execution-started.json",dict(manifest_sha256=h.sha_file(out/"manifest.json"),
        started_at=datetime.now(timezone.utc).isoformat(),private_state=str(private)))
    created,error,cleanup,rows=False,None,None,[]
    try:
        common.invoke("create","--pull=never","--name",pg,"--network","none","--cpus=2",
            "--cpuset-cpus","4,6","--memory=2147483648","--memory-swap=2147483648",
            "--env-file",str(private/"postgres.env"),"--mount",
            f"type=bind,src={h.ROOT/'scripts/postgres-init'},dst=/docker-entrypoint-initdb.d,readonly",m["postgres_image"])
        created=True
        common.invoke("start",pg)
        deadline=time.monotonic()+60
        while True:
            p=subprocess.run(common.DOCKER+["exec",pg,"sh","-c",
                'test "$(cat /proc/1/comm)" = postgres && pg_isready -h 127.0.0.1 -U orq41owner -d orq41sql_bootstrap'],
                capture_output=True,timeout=5)
            if p.returncode==0:break
            if time.monotonic()>=deadline:raise RuntimeError("Fresh PG readiness timeout")
            time.sleep(.25)
        info=json.loads(common.invoke("inspect",pg))[0];limits=info["HostConfig"]
        assert info["Image"]==m["postgres_image"] and limits["NetworkMode"]=="none" and not limits.get("PortBindings")
        assert limits["CpusetCpus"]=="4,6" and limits["NanoCpus"]==2000000000
        assert limits["Memory"]==limits["MemorySwap"]==2147483648
        loc=m["locale"]
        common.sql(pg,"orq41sql_bootstrap","CREATE DATABASE "+db+" OWNER orq41owner TEMPLATE template0 ENCODING "
            +h.quote(loc["encoding"])+" LC_COLLATE "+h.quote(loc["collate"])+" LC_CTYPE "+h.quote(loc["ctype"])+" LOCALE_PROVIDER libc;")
        common.invoke("exec","-i",pg,"psql","-X","-v","ON_ERROR_STOP=1","--single-transaction",
            "-U","orq41owner","-d",db,data=ddl)
        common.sql(pg,db,"INSERT INTO alembic_version VALUES ('e4b7f21c9a06');")
        dump=h.ORQ/"corpus-snapshot/orq37-t23-corpus.pgdump"
        assert h.sha_file(dump)==m["corpus_dump_sha256"]
        common.invoke("exec","-i",pg,"pg_restore","-U","orq41owner","-d",db,"--data-only","--single-transaction",data=dump.read_bytes())
        for table in h.TABLES:common.sql(pg,db,'ANALYZE "public"."'+table+'";')
        before=common.identity(pg,db,m)
        h.write_json(out/"preflight.json",dict(status="PLAN_COMPARISON_PREFLIGHT_PASS",database=before,
            postgres_id=info["Id"],image=info["Image"],network_mode=limits["NetworkMode"],
            postgres_resources=h.aa.pg_resources(pg),api_requests=0,provider_calls=0))
        query=(out/"compiled-query.sql").read_text()
        vector="["+",".join(str(float(v)) for v in m["vector"])+"]"
        for index,slot in enumerate(m["slots"]):
            key=f'{index:02}-{slot["case_id"]}-{slot["mode"]}'
            program=case_program(query,vector,slot)
            h.private_write(out/(key+".sql"),program.encode())
            h.write_json(out/(key+"-admitted.json"),dict(index=index,slot=slot,attempt=1,
                manifest_sha256=h.sha_file(out/"manifest.json"),sql_sha256=h.sha_file(out/(key+".sql"))))
            p=subprocess.run(common.DOCKER+["exec","-i","-e","PGAPPNAME=orq41-plan-"+str(index),
                pg,"psql","-X","-q","-A","-t","-v","ON_ERROR_STOP=1","-U","rag_app","-d",db],
                input=program.encode(),capture_output=True,timeout=45)
            h.private_write(out/(key+"-stdout.log"),p.stdout);h.private_write(out/(key+"-stderr.log"),p.stderr)
            if p.returncode:
                row=dict(index=index,slot=slot,status="FAILED",exit_code=p.returncode,attempt=1)
                h.write_json(out/(key+"-result.json"),row);rows.append(row)
                active=int(common.readonly(pg,db,"SELECT count(*) FROM pg_stat_activity WHERE application_name="
                    +h.quote("orq41-plan-"+str(index))+" AND state<>'idle';").strip())
                if active:raise RuntimeError("Unresolved failed case; stop admission")
                continue
            docs=common.decode_documents(p.stdout.decode());assert len(docs)==3
            meta,plans,after=docs
            assert meta["current_user"]==meta["session_user"]=="rag_app"
            assert meta["read_only"]==meta["row_security"]=="on" and meta["tenant"]==slot["tenant_id"]
            assert meta["superuser"] is meta["bypass_rls"] is False
            assert meta["settings"]["plan_cache_mode"]==slot["mode"]
            settings=dict(meta["settings"],plan_cache_mode="auto")
            assert settings==before["settings"]
            assert meta["prepared_before"]["generic_plans"]==meta["prepared_before"]["custom_plans"]==0
            counts=after["prepared_after"]
            assert counts["parameter_types"]=="{vector,bigint,text,bigint}" and counts["from_sql"] is True
            expected="generic_plans" if slot["mode"]=="force_generic_plan" else "custom_plans"
            assert counts[expected]==1 and counts["generic_plans"]+counts["custom_plans"]==1
            assert len(plans)==1 and plans[0]["Plan"]["Actual Rows"]==20
            row=dict(index=index,slot=slot,status="PASS",attempt=1,metadata=meta,prepared_after=counts,
                explain=plans[0],stdout_sha256=h.sha_file(out/(key+"-stdout.log")),
                stderr_sha256=h.sha_file(out/(key+"-stderr.log")))
            h.write_json(out/(key+"-result.json"),row);rows.append(row)
        after=common.identity(pg,db,m);assert before==after
        assert all(h.sha_file(h.ROOT/f)==v for f,v in scope.items())
        for audit in (out/"network-audit.log",Path("/tmp/orq41-plan-comparison-network.log")):
            assert not audit.exists() or audit.stat().st_size==0
        h.write_json(out/"postflight.json",dict(status="PLAN_COMPARISON_POSTFLIGHT_PASS",
            unchanged_database=after,protected_files_unchanged=len(scope),api_requests=0,provider_calls=0,spend_usd="0"))
    except Exception as exc:
        error=type(exc).__name__+": "+str(exc)[:180]
    finally:
        try:
            if created:
                common.invoke("stop","--time","10",pg,timeout=25)
                info=json.loads(common.invoke("inspect",pg))[0];assert not info["State"]["Running"]
            cleanup=dict(status="STOPPED_DATA_RETAINED",container=pg,created=created,no_resume=True,markers_retained=True)
        except Exception as exc:
            cleanup=dict(status="FAILED",error=type(exc).__name__)
        h.write_json(out/"cleanup.json",cleanup)
    admitted=sorted(f.name.removesuffix("-admitted.json") for f in out.glob("*-admitted.json"))
    complete=not error and len(rows)==20 and all(r["status"]=="PASS" for r in rows) and cleanup["status"]=="STOPPED_DATA_RETAINED"
    status="REQUEST_FREE_PLAN_COMPARISON_COMPLETE" if complete else "REQUEST_FREE_PLAN_COMPARISON_FAILED"
    h.write_json(out/"result.json",dict(status=status,error=error,rows=rows,
        cases_admitted=len(admitted),cases_resolved=len(rows),cases_failed=sum(r["status"]!="PASS" for r in rows),
        manifest_sha256=h.sha_file(out/"manifest.json"),api_requests=0,provider_calls=0,spend_usd="0",
        original_AA="AA_CALIBRATION_FAIL",official_g6_status="CONTROLLED_G6_FAIL",paid_admission="BLOCKED_CONTROLLED_G6_FAIL"))
    print(status)
    if not complete:raise SystemExit(1)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze",action="store_true")
    action.add_argument("--execute",type=Path)
    args=parser.parse_args()
    if args.freeze:freeze()
    else:execute(args.execute)
