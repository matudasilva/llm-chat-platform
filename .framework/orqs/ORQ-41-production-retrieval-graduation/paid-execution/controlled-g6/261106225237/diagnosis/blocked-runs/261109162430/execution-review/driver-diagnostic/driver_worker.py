"""Request-free adapter diagnostic using the shipped session factory and driver."""
import argparse
import asyncio
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import time

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.providers.pgvector_store import PgVectorStore
from app.core.settings import settings
from app.http.middleware.tenant import tenant_scope
from app.infra.db.session import build_rag_sessionmaker, TenantScopedSession
from experiments.production_graduation.gate_validation.validate_g123 import check_p2, check_config, config_identity
from experiments.production_graduation.gate_validation.g9_controller import private_write

META_SQL = """SELECT json_build_object(
 'pid',pg_backend_pid(),'current_user',current_user,'session_user',session_user,
 'read_only',current_setting('transaction_read_only'),'row_security',current_setting('row_security'),
 'tenant',current_setting('app.tenant_id'),'plan_cache_mode',current_setting('plan_cache_mode'),
 'superuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
 'bypass_rls',(SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user),
 'hybrid_cached',(SELECT coalesce(json_agg(row_to_json(s)),'[]'::json) FROM (
   SELECT name,statement,CAST(parameter_types AS text) AS parameter_types,
          custom_plans,generic_plans,from_sql
   FROM pg_prepared_statements
   WHERE statement ~ '^[[:space:]]*WITH semantic AS [(]'
   ORDER BY name) s)
);"""


def write(path, value):
    private_write(path, (json.dumps(value, indent=2) + "\n").encode())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe():
    check_p2()
    check_config(settings)
    return dict(status="DRIVER_IMAGE_SOURCE_SETTINGS_PROBE_PASS",
        config_identity=config_identity(settings),
        versions={k: version(k) for k in ("SQLAlchemy", "asyncpg", "greenlet")},
        sources={f:sha(Path("/app")/f) for f in (
            "app/core/providers/pgvector_store.py", "app/infra/db/session.py",
            "app/http/middleware/tenant.py")},
        app_requests=0, provider_calls=0, database_connections=0)


async def metadata(session, expected_tenant):
    value = (await session.execute(text(META_SQL))).scalar_one()
    if isinstance(value, str):
        value = json.loads(value)
    assert value["current_user"] == value["session_user"] == "rag_app"
    assert value["read_only"] == value["row_security"] == "on"
    assert value["tenant"] == expected_tenant and value["plan_cache_mode"] == "auto"
    assert value["superuser"] is False and value["bypass_rls"] is False
    assert len(value["hybrid_cached"]) <= 1
    return value


async def run():
    initial = probe()
    out = Path(os.environ["DRIVER_RUN_DIR"])
    manifest = json.loads((out / "manifest.json").read_text())
    assert sha(out / "manifest.json") == os.environ["DRIVER_MANIFEST_SHA"]
    assert initial["sources"] == manifest["image_source_sha256"]
    assert sha(Path(__file__)) == manifest["worker_sha256"]
    assert (out / "execution-started.json").is_file()
    write(out / "worker-started.json", dict(manifest_sha256=sha(out / "manifest.json")))
    factory = build_rag_sessionmaker(settings.database_url_app)
    engine = factory.kw["bind"]
    rows, error, dispose_error = [], None, None
    try:
        for index, slot in enumerate(manifest["slots"]):
            key = f'{index:02}-{slot["phase"]}-{slot["case_id"]}'
            write(out / (key+"-admitted.json"), dict(slot=slot, index=index,
                manifest_sha256=sha(out / "manifest.json"), attempt=1))
            row = dict(index=index, **slot, status="FAILED", error=None, adapter_call_begun=False)
            try:
                async with asyncio.timeout(35):
                    with tenant_scope(slot["tenant_id"]):
                        async with factory() as session:
                            assert isinstance(session.sync_session, TenantScopedSession)
                            wall, cpu = time.monotonic_ns(), time.process_time_ns()
                            await session.connection(execution_options={"postgresql_readonly": True})
                            row["checkout_wall_ns"] = time.monotonic_ns()-wall
                            row["checkout_cpu_ns"] = time.process_time_ns()-cpu
                            await session.execute(text("SET LOCAL statement_timeout='30s'"))
                            await session.execute(text("SET LOCAL lock_timeout='5s'"))
                            before = await metadata(session, slot["tenant_id"])
                            row["before"] = before
                            adapter = PgVectorStore(session)
                            row["adapter_call_begun"] = True
                            wall, cpu = time.monotonic_ns(), time.process_time_ns()
                            chunks = await adapter.hybrid_search(
                                slot["query_text"], manifest["vector"], top_k=20)
                            row["adapter_wall_ns"] = time.monotonic_ns()-wall
                            row["adapter_cpu_ns"] = time.process_time_ns()-cpu
                            after = await metadata(session, slot["tenant_id"])
                            row["after"] = after
                            assert before["pid"] == after["pid"]
                            old = before["hybrid_cached"]
                            new = after["hybrid_cached"]
                            assert len(new) == 1 and new[0]["from_sql"] is False
                            assert sum(new[0][k] for k in ("custom_plans","generic_plans")) == (
                                sum(old[0][k] for k in ("custom_plans","generic_plans")) if old else 0) + 1
                            if old:
                                assert all(old[0][k] == new[0][k] for k in ("name","statement","parameter_types"))
                            assert len(chunks) == slot["expected_rows"]
                            projection = [dict(chunk_id=str(c.chunk_id),document_id=str(c.document_id),
                                text_sha256=hashlib.sha256(c.text.encode()).hexdigest(),score=str(c.score))
                                for c in chunks]
                            row.update(before=before, after=after, output_rows=len(chunks),
                                result_sha256=hashlib.sha256(json.dumps(projection,sort_keys=True).encode()).hexdigest(),
                                output_projection=projection,
                                chosen_mode="generic" if new[0]["generic_plans"] > (old[0]["generic_plans"] if old else 0) else "custom")
                            wall, cpu = time.monotonic_ns(), time.process_time_ns()
                            await session.rollback()
                            row["rollback_wall_ns"] = time.monotonic_ns()-wall
                            row["rollback_cpu_ns"] = time.process_time_ns()-cpu
                row["status"] = "PASS"
            except Exception as exc:
                message = str(exc)
                password = make_url(settings.database_url_app).password
                if password:
                    message = message.replace(password, "<redacted>")
                row["error"] = type(exc).__name__+": "+message[:180]
                error = row["error"]
            write(out / (key+"-result.json"), row)
            rows.append(row)
            if row["status"] != "PASS":
                break
    finally:
        try:
            async with asyncio.timeout(10):
                await engine.dispose()
        except Exception as exc:
            dispose_error = type(exc).__name__
    status = "DRIVER_DIAGNOSTIC_COMPLETE" if len(rows)==30 and not error and not dispose_error else "DRIVER_DIAGNOSTIC_FAILED"
    write(out / "worker.json", dict(status=status, rows=rows, error=error,
        dispose_error=dispose_error, probe=initial, application_requests=0,
        provider_calls=0, repetitions=1,
        adapter_invocations_begun=sum(r["adapter_call_begun"] for r in rows),
        successful_adapter_calls=sum(r["status"]=="PASS" for r in rows), spend_usd="0"))
    print(status)
    if status != "DRIVER_DIAGNOSTIC_COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe()))
    else:
        asyncio.run(run())
