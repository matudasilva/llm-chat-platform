"""Freeze and execute one request-free 20-warmup/10-call driver diagnostic."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from uuid import uuid4, uuid5

from experiments.production_graduation.gate_validation import blocked_latency as h
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

BASE = Path(__file__).resolve().parent
PRIOR = BASE.parents[1]
COMMON_PATH = BASE.parent / "sql-diagnostic/run_sql_diagnostic.py"
assert h.sha_file(COMMON_PATH) == "197edfcb2e295c5aa6a04727596923da28accf6a2e22c36473a2d45a8af6fddf"
spec = importlib.util.spec_from_file_location("retained_sql_diagnostic_helpers", COMMON_PATH)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


def freeze():
    check_p2()
    plan = json.loads((PRIOR / "plan.json").read_text())
    assert h.sha_file(PRIOR / "plan.json") == "b3d7cbe4aa4587ca20a3dadd79e2a10d7813981b8a33550d661c58af6f19026b"
    scope = json.loads((PRIOR / "execution-scope-before.json").read_text())
    assert len(scope) == 500 and all(h.sha_file(h.ROOT/f) == v for f,v in scope.items())
    original = [s for s in plan["samples"] if s["language"] == "ES" and s["protocol"] == "sse"
                and s["block"] == 0 and s["warmup"]]
    assert len(original) == 20
    targets = json.loads((BASE.parent / "sql-diagnostic/261109212354/manifest.json").read_text())["cases"]
    assert len(targets) == 10
    namespace, slots = uuid4(), []
    for phase, source in (("warmup", original), ("diagnostic", targets)):
        for index, c in enumerate(source):
            slots.append(dict(slot_id=str(uuid5(namespace, phase+"/"+str(index))),
                phase=phase, case_id=c["case_id"], category=c["category"],
                tenant_id=c["tenant_id"], query_text=c.get("query_text", c.get("message")),
                expected_rows=20 if c["tenant_id"] == "orq37-t23" else 0))
    assert len(slots) == len({s["slot_id"] for s in slots}) == 30
    run_id = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    out = BASE / run_id
    out.mkdir(mode=0o700, exist_ok=False)
    manifest = dict(schema="orq41-request-free-driver-diagnostic-v1", run_id=run_id,
        namespace=str(namespace), slots=slots, warmups=20, diagnostic_calls=10, select_executions=30,
        repetitions=1, concurrency=1, attempts_per_slot=1, not_a_gate=True,
        postgres_image=plan["postgres_image"], worker_image=plan["images"]["c1"],
        container="orq41-driver-"+run_id+"-postgres", worker="orq41-driver-"+run_id+"-adapter",
        database="orq41_driver_"+run_id, locale=plan["database_locale"],
        schema_sha256=plan["source_schema_sha256"], vector=[1.0]+[0.0]*1535,
        source_postgres_id=json.loads((PRIOR / "execution-review/cleanup.json").read_text())["source_postgres_id"],
        image_source_sha256={f:h.sha_file(h.ROOT/f) for f in (
            "app/core/providers/pgvector_store.py","app/infra/db/session.py","app/http/middleware/tenant.py")},
        controller_sha256=h.sha_file(Path(__file__)), worker_sha256=h.sha_file(BASE/"driver_worker.py"),
        common_helper_sha256=h.sha_file(COMMON_PATH), prior_plan_sha256=h.sha_file(PRIOR/"plan.json"),
        prior_sql_result_sha256=h.sha_file(BASE.parent/"sql-diagnostic/261109212354/result.json"),
        corpus_dump_sha256="0334e3af47edf9c885093a6ad061390f6f85ba62517e56b94450339950599d4f",
        driver_policy="Shipped build_rag_sessionmaker, default pool/prepared cache and inferred types; plan_cache_mode auto",
        diagnostic_bounds=dict(server_statement_timeout_s=30,lock_timeout_s=5,slot_timeout_s=35,dispose_timeout_s=10),
        no_explain=True, no_explicit_prepare=True, no_app_or_provider_requests=True,
        api_requests=0, provider_calls=0, spend_usd="0", original_calibration="AA_CALIBRATION_FAIL")
    h.write_json(out/"manifest.json",manifest)
    h.write_json(out/"scope-before.json",scope)
    h.write_json(out/"authorization.json",dict(status="OPERATOR_AUTHORIZED_REQUEST_FREE_DRIVER_DIAGNOSTIC",
        operator_message="ok, continuemos con la proxima prueba", manifest_sha256=h.sha_file(out/"manifest.json"),
        max_select_executions=30, warmups=20, diagnostic_calls=10, repetitions=1,
        actual_driver_only=True, app_changes=False, forced_plan_modes=False, extra_explain=False,
        paid_requests_authorized=0, external_calls_authorized=0, spend_usd="0"))
    print(out.relative_to(h.ROOT))


def execute(out):
    check_p2()
    out = out.resolve()
    assert not (out/"execution-started.json").exists() and not (out/"execution-started.json").is_symlink()
    m = json.loads((out/"manifest.json").read_text())
    auth = json.loads((out/"authorization.json").read_text())
    assert auth["status"] == "OPERATOR_AUTHORIZED_REQUEST_FREE_DRIVER_DIAGNOSTIC"
    assert auth["manifest_sha256"] == h.sha_file(out/"manifest.json")
    assert m["controller_sha256"] == h.sha_file(Path(__file__))
    assert m["worker_sha256"] == h.sha_file(BASE/"driver_worker.py")
    scope = json.loads((out/"scope-before.json").read_text())
    assert all(h.sha_file(h.ROOT/f) == v for f,v in scope.items())
    for name in (m["container"],m["worker"]):
        assert not common.invoke("ps","-a","--filter","name=^/"+name+"$","--format","{{.ID}}").strip()
    for image in (m["postgres_image"],m["worker_image"]):
        assert json.loads(common.invoke("image","inspect",image))[0]["Id"] == image
    source = json.loads(common.invoke("inspect","orq41-env-pg"))[0]
    assert source["State"]["Running"] and source["Id"] == m["source_postgres_id"]
    ddl = common.invoke("exec","orq41-env-pg","pg_dump","-U","orq41owner","-d","orq41","--schema-only")
    assert hashlib.sha256(common.canonical_schema(ddl)).hexdigest() == m["schema_sha256"]
    private = Path(tempfile.mkdtemp(prefix="orq41-driver-"+m["run_id"]+"-"))
    private.chmod(0o700)
    credentials = {k:secrets.token_hex(24) for k in ("POSTGRES_PASSWORD","POSTGRES_APP_PASSWORD",
        "POSTGRES_EVALUATION_PASSWORD","POSTGRES_OPS_PASSWORD","POSTGRES_OPS_RETENTION_PASSWORD")}
    values = dict(credentials,POSTGRES_USER="orq41owner",POSTGRES_DB="orq41sql_bootstrap")
    h.private_write(private/"postgres.env","".join(k+"="+v+"\n" for k,v in sorted(values.items())).encode())
    h.write_json(out/"execution-started.json",dict(manifest_sha256=h.sha_file(out/"manifest.json"),
        started_at=datetime.now(timezone.utc).isoformat(),private_state=str(private)))
    pg, db, worker = m["container"],m["database"],m["worker"]
    pg_created, worker_created, error, cleanup = False,False,None,None
    try:
        common.invoke("create","--pull=never","--name",pg,"--network","none","--cpus=2",
            "--cpuset-cpus","4,6","--memory=2147483648","--memory-swap=2147483648",
            "--env-file",str(private/"postgres.env"),"--mount",
            f"type=bind,src={h.ROOT/'scripts/postgres-init'},dst=/docker-entrypoint-initdb.d,readonly",m["postgres_image"])
        pg_created=True
        common.invoke("start",pg)
        deadline=time.monotonic()+60
        while True:
            r=subprocess.run(common.DOCKER+["exec",pg,"sh","-c",
                'test "$(cat /proc/1/comm)" = postgres && pg_isready -h 127.0.0.1 -U orq41owner -d orq41sql_bootstrap'],
                capture_output=True,timeout=5)
            if r.returncode==0:break
            if time.monotonic()>=deadline:raise RuntimeError("Fresh PG readiness timeout")
            time.sleep(.25)
        info=json.loads(common.invoke("inspect",pg))[0]
        assert info["Image"]==m["postgres_image"] and info["HostConfig"]["NetworkMode"]=="none"
        assert not info["HostConfig"].get("PortBindings")
        assert info["HostConfig"]["Memory"]==info["HostConfig"]["MemorySwap"]==2147483648
        loc=m["locale"]
        common.sql(pg,"orq41sql_bootstrap","CREATE DATABASE "+db+" OWNER orq41owner TEMPLATE template0 ENCODING "
            +h.quote(loc["encoding"])+" LC_COLLATE "+h.quote(loc["collate"])+" LC_CTYPE "+h.quote(loc["ctype"])+" LOCALE_PROVIDER libc;")
        common.invoke("exec","-i",pg,"psql","-X","-v","ON_ERROR_STOP=1","--single-transaction","-U","orq41owner","-d",db,data=ddl)
        common.sql(pg,db,"INSERT INTO alembic_version VALUES ('e4b7f21c9a06');")
        dump=h.ORQ/"corpus-snapshot/orq37-t23-corpus.pgdump"
        assert h.sha_file(dump)==m["corpus_dump_sha256"]
        common.invoke("exec","-i",pg,"pg_restore","-U","orq41owner","-d",db,"--data-only","--single-transaction",data=dump.read_bytes())
        for table in h.TABLES:common.sql(pg,db,'ANALYZE "public"."'+table+'";')
        before=common.identity(pg,db,m)
        env=h.env_for("c1","C1",db,credentials)
        env.update(PYTHONHASHSEED="41",PYTHONPATH="/p2_netguard:/app",PATH="/usr/local/bin:/usr/bin:/bin",
            DRIVER_RUN_DIR="/driver-run",DRIVER_MANIFEST_SHA=h.sha_file(out/"manifest.json"),
            P2_NET_AUDIT_LOG="/driver-run/network-audit.log")
        h.private_write(private/"driver.env","".join(k+"="+v+"\n" for k,v in sorted(env.items())).encode())
        mounts=["--mount",f"type=bind,src={BASE/'driver_worker.py'},dst=/driver_worker.py,readonly",
            "--mount",f"type=bind,src={h.ROOT/'experiments'},dst=/app/experiments,readonly",
            "--mount",f"type=bind,src={h.P2_GUARD},dst=/p2_netguard,readonly"]
        limits=["--user=1000:1000","--cpus=2","--cpuset-cpus","0,2","--memory=2147483648","--memory-swap=2147483648"]
        raw=common.invoke("run","--rm","--pull=never","--network","none",*limits,
            "--env-file",str(private/"driver.env"),*mounts,"--entrypoint","/usr/local/bin/python",
            m["worker_image"],"/driver_worker.py","--probe")
        probe=json.loads(raw)
        assert probe["sources"]==m["image_source_sha256"]
        h.write_json(out/"preflight.json",dict(status="REQUEST_FREE_DRIVER_PREFLIGHT_PASS",
            database=before,image_probe=probe,postgres_resources=h.aa.pg_resources(pg),api_requests=0,provider_calls=0))
        common.invoke("create","--pull=never","--name",worker,"--network","container:"+pg,*limits,
            "--env-file",str(private/"driver.env"),*mounts,
            "--mount",f"type=bind,src={out},dst=/driver-run",
            "--entrypoint","/usr/local/bin/python",m["worker_image"],"/driver_worker.py")
        worker_created=True
        wi=json.loads(common.invoke("inspect",worker))[0]
        assert wi["Image"]==m["worker_image"] and wi["HostConfig"]["NetworkMode"]=="container:"+info["Id"]
        assert not wi["HostConfig"].get("PortBindings")
        assert wi["HostConfig"]["CpusetCpus"]=="0,2" and wi["HostConfig"]["NanoCpus"]==2000000000
        assert wi["HostConfig"]["Memory"]==wi["HostConfig"]["MemorySwap"]==2147483648
        common.invoke("start",worker)
        code=common.invoke("wait",worker,timeout=1200).strip()
        logs=subprocess.run(common.DOCKER+["logs",worker],capture_output=True,check=True,timeout=60)
        h.private_write(out/"worker-stdout.log",logs.stdout);h.private_write(out/"worker-stderr.log",logs.stderr)
        state=json.loads(common.invoke("inspect",worker))[0]
        h.write_json(out/"worker-state.json",dict(id=state["Id"],exit_code=state["State"]["ExitCode"],
            running=state["State"]["Running"],image=state["Image"],network_mode=state["HostConfig"]["NetworkMode"],
            cpuset=wi["HostConfig"]["CpusetCpus"],nano_cpus=wi["HostConfig"]["NanoCpus"],memory_bytes=wi["HostConfig"]["Memory"]))
        w=json.loads((out/"worker.json").read_text())
        assert code==b"0" and w["status"]=="DRIVER_DIAGNOSTIC_COMPLETE" and len(w["rows"])==30
        assert [r["slot_id"] for r in w["rows"]]==[r["slot_id"] for r in m["slots"]]
        after=common.identity(pg,db,m)
        assert before==after
        assert all(h.sha_file(h.ROOT/f)==v for f,v in scope.items())
        for audit in (out/"network-audit.log",Path("/tmp/orq41-driver-diagnostic-network.log")):
            assert not audit.exists() or audit.stat().st_size==0
        h.write_json(out/"postflight.json",dict(status="REQUEST_FREE_DRIVER_POSTFLIGHT_PASS",
            unchanged_database=after,protected_files_unchanged=len(scope),api_requests=0,provider_calls=0,spend_usd="0"))
    except Exception as exc:
        error=type(exc).__name__+": "+str(exc)[:180]
    finally:
        try:
            if worker_created:
                state=json.loads(common.invoke("inspect",worker))[0]
                if state["State"]["Running"]:common.invoke("stop","--time","10",worker,timeout=25)
            if pg_created:
                common.invoke("stop","--time","10",pg,timeout=25)
                state=json.loads(common.invoke("inspect",pg))[0]
                assert not state["State"]["Running"]
            cleanup=dict(status="STOPPED_DATA_RETAINED",postgres_created=pg_created,worker_created=worker_created,
                postgres=pg,worker=worker,markers_retained=True,no_resume=True)
        except Exception as exc:
            cleanup=dict(status="FAILED",error=type(exc).__name__)
        h.write_json(out/"cleanup.json",cleanup)
    status="REQUEST_FREE_DRIVER_DIAGNOSTIC_COMPLETE" if not error and cleanup["status"]=="STOPPED_DATA_RETAINED" else "REQUEST_FREE_DRIVER_DIAGNOSTIC_FAILED"
    h.write_json(out/"result.json",dict(status=status,error=error,manifest_sha256=h.sha_file(out/"manifest.json"),
        case_admissions=len(list(out.glob("*-admitted.json"))),api_requests=0,provider_calls=0,
        spend_usd="0",official_g6_status="CONTROLLED_G6_FAIL",paid_admission="BLOCKED_CONTROLLED_G6_FAIL"))
    print(status)
    if status!="REQUEST_FREE_DRIVER_DIAGNOSTIC_COMPLETE":raise SystemExit(1)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze",action="store_true")
    action.add_argument("--execute",type=Path)
    args=parser.parse_args()
    if args.freeze:freeze()
    else:execute(args.execute)
