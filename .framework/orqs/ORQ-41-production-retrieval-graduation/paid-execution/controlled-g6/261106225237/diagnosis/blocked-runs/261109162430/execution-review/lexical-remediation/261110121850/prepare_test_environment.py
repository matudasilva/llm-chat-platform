"""Create only fresh, isolated PG databases for the authorized lexical tests."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

from experiments.production_graduation.gate_validation import blocked_latency as h
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

OUT=Path(__file__).resolve().parent
PRIOR=OUT.parents[2]
COMMON=PRIOR/"execution-review/sql-diagnostic/run_sql_diagnostic.py"
assert h.sha_file(COMMON)=="197edfcb2e295c5aa6a04727596923da28accf6a2e22c36473a2d45a8af6fddf"
spec=importlib.util.spec_from_file_location("lexical_fixture_helpers",COMMON)
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
check_p2()
baseline=json.loads((OUT/"scope-before.json").read_text())
assert all(h.sha_file(h.ROOT/f)==v for f,v in baseline.items())
plan=json.loads((PRIOR/"plan.json").read_text())
run_id=OUT.name
pg="orq41-lex-"+run_id+"-postgres"
database="orq41_lex_"+run_id
empty=database+"_empty"
assert not c.invoke("ps","-a","--filter","name=^/"+pg+"$","--format","{{.ID}}").strip()
private=Path(tempfile.mkdtemp(prefix="orq41-lex-"+run_id+"-"));private.chmod(0o700)
values={k:secrets.token_hex(24) for k in ("POSTGRES_PASSWORD","POSTGRES_APP_PASSWORD",
    "POSTGRES_EVALUATION_PASSWORD","POSTGRES_OPS_PASSWORD","POSTGRES_OPS_RETENTION_PASSWORD")}
values.update(POSTGRES_USER="orq41owner",POSTGRES_DB="orq41sql_bootstrap")
h.private_write(private/"postgres.env","".join(k+"="+v+"\n" for k,v in sorted(values.items())).encode())
h.write_json(OUT/"environment-allocation.json",dict(container=pg,private_state=str(private),
    database=database,empty_database=empty,postgres_image=plan["postgres_image"],app_image=plan["images"]["c1"]))
c.invoke("create","--pull=never","--name",pg,"--network","none","--cpus=2","--cpuset-cpus","4,6",
    "--memory=2147483648","--memory-swap=2147483648","--env-file",str(private/"postgres.env"),
    "--mount",f"type=bind,src={h.ROOT/'scripts/postgres-init'},dst=/docker-entrypoint-initdb.d,readonly",plan["postgres_image"])
c.invoke("start",pg)
deadline=time.monotonic()+60
while True:
    r=subprocess.run(c.DOCKER+["exec",pg,"sh","-c",
        'test "$(cat /proc/1/comm)" = postgres && pg_isready -h 127.0.0.1 -U orq41owner -d orq41sql_bootstrap'],
        capture_output=True,timeout=5)
    if r.returncode==0:break
    if time.monotonic()>=deadline:raise RuntimeError("PG fixture readiness timeout; no tests admitted")
    time.sleep(.25)
source=json.loads(c.invoke("inspect","orq41-env-pg"))[0]
assert source["State"]["Running"]
ddl=c.invoke("exec","orq41-env-pg","pg_dump","-U","orq41owner","-d","orq41","--schema-only")
assert hashlib.sha256(c.canonical_schema(ddl)).hexdigest()==plan["source_schema_sha256"]
for name,restore in ((database,True),(empty,False)):
    loc=plan["database_locale"]
    c.sql(pg,"orq41sql_bootstrap","CREATE DATABASE "+name+" OWNER orq41owner TEMPLATE template0 ENCODING "
        +h.quote(loc["encoding"])+" LC_COLLATE "+h.quote(loc["collate"])+" LC_CTYPE "+h.quote(loc["ctype"])+" LOCALE_PROVIDER libc;")
    c.invoke("exec","-i",pg,"psql","-X","-v","ON_ERROR_STOP=1","--single-transaction",
        "-U","orq41owner","-d",name,data=ddl)
    c.sql(pg,name,"INSERT INTO alembic_version VALUES ('e4b7f21c9a06');")
    if restore:
        dump=h.ORQ/"corpus-snapshot/orq37-t23-corpus.pgdump"
        assert h.sha_file(dump)=="0334e3af47edf9c885093a6ad061390f6f85ba62517e56b94450339950599d4f"
        c.invoke("exec","-i",pg,"pg_restore","-U","orq41owner","-d",name,"--data-only","--single-transaction",data=dump.read_bytes())
    for table in h.TABLES:c.sql(pg,name,'ANALYZE "public"."'+table+'";')
    assert c.schema_hash(pg,name)==plan["source_schema_sha256"]
manifest=dict(schema_sha256=plan["source_schema_sha256"])
proof=c.identity(pg,database,manifest)
assert c.readonly(pg,empty,"SELECT (SELECT count(*) FROM documents),(SELECT count(*) FROM chunks);").strip()=="0|0"
env=h.env_for("c1","C1",database,values)
env.update(RAG_TEST_DATABASE_URL=env["DATABASE_URL"],RAG_TEST_DATABASE_URL_APP=env["DATABASE_URL_APP"],
    RAG_TEST_EMPTY_DATABASE_URL_APP=env["DATABASE_URL_APP"].rsplit("/",1)[0]+"/"+empty,
    PYTHONHASHSEED="41",PYTHONDONTWRITEBYTECODE="1",PYTHONPATH="/p2_netguard:/app",
    P2_NET_AUDIT_LOG="/validation/network-audit.log",PATH="/usr/local/bin:/usr/bin:/bin")
h.private_write(private/"tests.env","".join(k+"="+v+"\n" for k,v in sorted(env.items())).encode())
h.write_json(OUT/"environment-preflight.json",dict(status="LEXICAL_TEST_ENVIRONMENT_READY",prepared_at=datetime.now(timezone.utc).isoformat(),
    container=pg,id=json.loads(c.invoke("inspect",pg))[0]["Id"],database=database,empty_database=empty,
    p3=proof,source_postgres_id=source["Id"],app_image=plan["images"]["c1"],postgres_image=plan["postgres_image"],
    postgres_resources=h.aa.pg_resources(pg),private_state=str(private),external_provider_calls=0,app_requests=0,spend_usd="0"))
print("LEXICAL_TEST_ENVIRONMENT_READY")
