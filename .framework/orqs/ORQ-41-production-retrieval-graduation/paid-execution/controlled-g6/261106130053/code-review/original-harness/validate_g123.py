"""Fail-closed G1/G2/G3 harness controls; importing does not execute gates.

Callers must separately authorize environment provisioning/execution. A unit
control result is never a gate PASS. Frozen independent oracles are mandatory;
this module deliberately has no 'record expectations from candidate' mode.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import copy
import re
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from .fixtures import (CONTEXT_CASES, TRANSACTION_CASES, HarnessError, P3_FINGERPRINT, P3_CONTENT_SHA256,
                       Case, canonical, fingerprint, freeze, readback, run_database,
                       cell_key, minimum_cells, scenario, OBSERVATION_FAULTS, execution_identity, execution_identity_sha256)

_active_case = False


def serial_case(fn):
    """Refuse concurrent admissions in the single local controller process."""
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        global _active_case
        # No await between the check and assignment in this event loop.
        if _active_case:
            raise HarnessError("concurrent gate execution refused")
        _active_case = True
        try:
            return await fn(*args, **kwargs)
        finally:
            _active_case = False
    return wrapped


def local_endpoint(value):
    parsed = urlsplit(value)
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except (ValueError, TypeError):
        local = False
    if not local or parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HarnessError("only literal loopback HTTP endpoints are permitted")
    return value


def check_config(cfg):
    if (cfg.provider != "bedrock" or cfg.fallback_provider is not None or cfg.routing_policy != "static"
            or cfg.routing_shadow_mode_enabled or cfg.routing_shadow_policy is not None
            or cfg.bedrock_model != "nvidia.nemotron-nano-3-30b" or cfg.bedrock_region != "us-east-1"):
        raise HarnessError("campaign configuration drift")
    if cfg.otel_enabled:
        local_endpoint(cfg.otel_exporter_otlp_endpoint)
    for name in ("database_url", "database_url_app", "database_url_ops"):
        value = getattr(cfg, name, None)
        if not value:
            raise HarnessError("three separate PostgreSQL roles required")
        url = make_url(str(value))
        if url.drivername != "postgresql+asyncpg" or url.host not in {"127.0.0.1", "::1"}:
            raise HarnessError("nonlocal/non-PostgreSQL database URL")
    urls = [make_url(str(getattr(cfg, name))) for name in ("database_url", "database_url_app", "database_url_ops")]
    if len({url.database for url in urls}) != 1 or len({url.username for url in urls}) != 3:
        raise HarnessError("role/database separation missing")
    if urls[1].username != "rag_app" or urls[2].username != "chat_ops":
        raise HarnessError("approved read roles required")
    for flag in ("notion_mcp_enabled", "notion_read_enabled", "notion_write_enabled", "web_read_enabled"):
        if getattr(cfg, flag, False):
            raise HarnessError("external integration enabled")
    if any(getattr(cfg, key, None) for key in ("openai_api_key", "aws_access_key_id", "aws_secret_access_key", "aws_session_token")):
        raise HarnessError("external credentials in effective settings")
    if getattr(cfg, "redis_host", None) not in {"127.0.0.1", "::1"}:
        raise HarnessError("Redis must use literal loopback")
    if not 0 < getattr(cfg, "chat_response_cache_ttl_s", 0):
        raise HarnessError("invalid frozen cache TTL")


def config_identity(cfg):
    """Hash effective settings without retaining secrets in the manifest."""
    values = cfg.model_dump(mode="json") if hasattr(cfg, "model_dump") else vars(cfg).copy()
    for key, value in list(values.items()):
        if "url" in key and value:
            try:
                values[key] = make_url(str(value)).render_as_string(hide_password=True)
            except Exception as exc:
                raise HarnessError("invalid settings URL") from exc
        elif key.endswith(("password", "secret", "api_key", "access_token", "credential")) or key in {"aws_access_key_id", "aws_session_token"}:
            values[key] = bool(value)
    return fingerprint(values)


def check_vector(case, cfg, reference):
    if reference != case.reference:
        raise HarnessError("source reference differs from frozen case")
    flags = tuple(getattr(cfg, name, None) for name in ("chat_rag_augmentation_enabled", "conversation_history_enabled", "ebm25_enabled"))
    expected = (False, False, False) if case.vector == "OFF" else (True, True, case.vector == "E1")
    if flags != expected:
        raise HarnessError("effective feature vector mismatch")


def check_p2():
    forbidden = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "OPENAI_API_KEY",
                 "GOOGLE_APPLICATION_CREDENTIALS", "GCP_PROJECT_ID", "AWS_PROFILE")
    if any(os.environ.get(key) for key in forbidden) or os.environ.get("APP_SETTINGS_ENV_FILE") != "":
        raise HarnessError("unscrubbed settings/credentials")
    if os.environ.get("AWS_EC2_METADATA_DISABLED") != "true":
        raise HarnessError("SDK metadata discovery not disabled")
    # sysfs may retain the parent mount namespace's network view after
    # unshare -n. Query the active kernel network namespace instead.
    interfaces = {line.split(":", 1)[0].strip()
                  for line in Path("/proc/self/net/dev").read_text().splitlines()[2:]}
    if interfaces - {"lo"}:
        raise HarnessError("kernel namespace has non-loopback interfaces")
    import sitecustomize
    if "p2_netguard" not in str(getattr(sitecustomize, "__file__", "")):
        raise HarnessError("P2 network guard not loaded")


async def preflight(cfg, sessions, *, run_id, reference, dump_path):
    """Read-only checks. Must complete before fixture seed or /chat requests."""
    check_p2()
    check_config(cfg)
    database = run_database(run_id, reference)
    if len(sessions) != 3 or any(not isinstance(session, AsyncSession) for session in sessions):
        raise HarnessError("real independent business/rag/history sessions required")
    from .fixtures import P3_SHA256
    if hashlib.sha256(Path(dump_path).read_bytes()).hexdigest() != P3_SHA256:
        raise HarnessError("P3 dump mismatch")
    from app.http.middleware.tenant import tenant_scope
    from app.infra.db.session import TenantScopedSession
    if not isinstance(sessions[1].sync_session, TenantScopedSession):
        raise HarnessError("rag_app must retain TenantScopedSession")
    roles = []
    for index, session in enumerate(sessions):
        if session.in_transaction():
            raise HarnessError("preflight requires fresh sessions")
        with tenant_scope(f"g123-{run_id}-own"):
            async with session.begin():
                # Configure READ ONLY before the TenantScopedSession after_begin
                # SELECT; SET TRANSACTION after that SELECT would be too late.
                await session.connection(execution_options={"postgresql_readonly": True})
                row = (await session.execute(text("""SELECT current_database() AS db,current_user AS role,
                    rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"""))).mappings().one()
                if row["db"] != database or session.bind.dialect.name != "postgresql":
                    raise HarnessError("wrong gate database")
                roles.append(row["role"])
                if index in (1, 2) and (row["rolsuper"] or row["rolbypassrls"]):
                    raise HarnessError("read role bypasses isolation")
                if index == 1:
                    if row["role"] != "rag_app":
                        raise HarnessError("document reads must use rag_app")
                    rls = (await session.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid='chunks'::regclass"))).scalar_one()
                    if not rls:
                        raise HarnessError("document RLS disabled")
                    foreign_count = (await session.execute(text("SELECT count(*) FROM chunks WHERE tenant_id='orq37-t23'"))).scalar_one()
                    if foreign_count != 0:
                        raise HarnessError("rag_app leaks foreign corpus")
                if index == 2 and row["role"] != "chat_ops":
                    raise HarnessError("history reads must use chat_ops")
                if index == 0:
                    revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
                    version = (await session.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))).scalar_one()
                    pg_version = int((await session.execute(text("SHOW server_version_num"))).scalar_one())
                    if revision != "e4b7f21c9a06" or version != "0.8.6" or pg_version != 160014:
                        raise HarnessError("schema/PostgreSQL/pgvector drift")
                    docs = (await session.execute(text("SELECT source_path,content_hash FROM documents WHERE tenant_id='orq37-t23'"))).all()
                    projection = "\n".join(sorted(f"{path}:{digest}" for path, digest in docs))
                    counts = (await session.execute(text("""SELECT count(*),count(embedding),min(vector_dims(embedding)),max(vector_dims(embedding))
                        FROM chunks WHERE tenant_id='orq37-t23'"""))).one()
                    if len(docs) != 124 or tuple(counts) != (2146, 2146, 1536, 1536) or hashlib.sha256(projection.encode()).hexdigest() != P3_FINGERPRINT:
                        raise HarnessError("restored corpus mismatch")
                    content = (await session.execute(text("""SELECT d.source_path,d.content_hash,d.doc_type,d.indexing_mode,
                        c.ordinal,md5(c.text),md5(coalesce(c.context,'')),md5(c.embedding::text),
                        md5(c.search_vector::text),md5(c.metadata::text)
                        FROM chunks c JOIN documents d ON d.id=c.document_id
                        WHERE c.tenant_id='orq37-t23' ORDER BY d.source_path,c.ordinal"""))).all()
                    projection_bytes = "".join("\t".join(copy_text(value) for value in row) + "\n" for row in content).encode()
                    if hashlib.sha256(projection_bytes).hexdigest() != P3_CONTENT_SHA256:
                        raise HarnessError("restored chunk/vector content mismatch")
    if len(set(roles)) != 3:
        raise HarnessError("independent roles missing")
    return dict(database=database, roles=roles, preflight="PASS", gates_executed=False)


def copy_text(value):
    """PostgreSQL text COPY encoding used by the approved P3 content identity."""
    if value is None:
        return "\\N"
    return str(value).translate(str.maketrans({"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r", "\b": "\\b", "\f": "\\f", "\v": "\\v"}))


def load_manifest(raw):
    value = json.loads(raw)
    if set(value) != {"body", "sha256"} or value["sha256"] != fingerprint(value["body"]):
        raise HarnessError("manifest integrity failure")
    body = value["body"]
    if body.get("version") != 2 or body.get("minimum_cells") != [list(cell) for cell in sorted(minimum_cells())]:
        raise HarnessError("unsupported manifest version")
    cases = [Case(**item) for item in body["cases"]]
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise HarnessError("duplicate/empty manifest")
    # Reuse the freeze-side identity checks; a recomputed hash cannot make an
    # incomplete or wrong-corpus manifest valid.
    freeze(cases, body["identities"])
    return body, cases


def check_matrix(cases, required_cells):
    """Exact prospectively declared expansion, including approved N/A cells.

    required_cells contains all applicable (family,vector,protocol,adapter,language)
    tuples. An omitted or duplicated expanded case cannot be called complete.
    """
    cells = [cell_key(case) for case in cases]
    required_cells = [tuple(cell) for cell in required_cells]
    if len(set(cells)) != len(cells) or set(cells) != set(required_cells):
        raise HarnessError("incomplete/duplicate/unapproved matrix expansion")
    if not minimum_cells() <= set(cells):
        raise HarnessError("approved minimum matrix coverage missing")


def verify_source(root, files):
    """Verify the prospective source inventory inside the running test image."""
    root = Path(root).resolve()
    if not files:
        raise HarnessError("missing source inventory")
    for name, expected in files.items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise HarnessError("unsafe/missing source file")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise HarnessError("source inventory mismatch")


def observation_fault(snapshot, kind):
    """Deliberately corrupt only a retained copy, never the runtime observer.

    These negative controls must be declared evidence_expected=rejected. They
    are not claimed as end-to-end loss unless applied to that same PG request.
    """
    result = copy.deepcopy(snapshot)
    records = result["records"]
    if kind == "lost_observation":
        del records[len(records) // 2]
    elif kind == "duplicate_observation":
        records.insert(1, copy.deepcopy(records[0]))
    elif kind == "reordered_observation":
        records[0], records[1] = records[1], records[0]
    elif kind == "wrong_execution":
        result["instance_id"] = "wrong-execution"
    elif kind in {"corrupt_observation", "wrong_attempt", "wrong_purpose"}:
        record = next((row for row in records if row["stage"] == "transport.dispatched"), None)
        if record is None:
            raise HarnessError("negative control requires an actual dispatch")
        if kind == "wrong_attempt":
            record["data"]["application_attempt"] = 0
        elif kind == "wrong_purpose":
            record["purpose"] = "evaluator"
        else:
            record["data"]["payload_sha256"] = "0" * 64
    else:
        raise HarnessError("unknown observation fault")
    return result


def parse_sse(body):
    """Native /chat framing; preserve multiline token text and validate to EOF."""
    try:
        decoded = body.decode("utf-8", errors="strict").replace("\r\n", "\n")
    except UnicodeError as exc:
        raise HarnessError("invalid SSE encoding") from exc
    if not decoded.endswith("\n\n"):
        raise HarnessError("incomplete SSE frame")
    events = []
    terminal = False
    for frame in decoded[:-2].split("\n\n"):
        name, data = None, []
        for line in frame.split("\n"):
            if line.startswith("event: ") and name is None:
                name = line[7:]
            elif line.startswith("data: "):
                data.append(line[6:])
            else:
                raise HarnessError("unexpected SSE field")
        if terminal or name not in {"token", "done", "error"} or not data:
            raise HarnessError("invalid SSE order/event")
        payload = "\n".join(data)
        if name != "token":
            payload = json.loads(payload)
            if not isinstance(payload, dict):
                raise HarnessError("invalid SSE terminal")
            terminal = True
        events.append((name, payload))
    if not terminal:
        raise HarnessError("missing SSE terminal")
    return events


async def http_operation(client, endpoint, case, *, request_id, tenant, timeout_s):
    """One HTTP operation, no resend. EOF means body EOF, not TCP close."""
    local_endpoint(endpoint)
    deadline = asyncio.get_running_loop().time() + timeout_s
    async with asyncio.timeout_at(deadline):
        async with client.stream("POST", endpoint.rstrip("/") + "/chat", json=json.loads(case.request_json),
                                 headers={"X-Request-ID": request_id, "X-Tenant-ID": tenant}) as response:
            body = b"".join([chunk async for chunk in response.aiter_raw()])
            if asyncio.get_running_loop().time() >= deadline:
                raise HarnessError("response exceeded absolute deadline")
            length = response.headers.get("content-length")
            if length is not None and (not length.isdecimal() or len(body) != int(length)):
                raise HarnessError("incomplete HTTP body")
            if case.protocol == "sse" and response.headers.get("content-type", "").startswith("text/event-stream"):
                events = parse_sse(body)
                terminal = events[-1][0]
                content = "".join(item for kind, item in events if kind == "token")
                payload = events[-1][1]
            else:
                try:
                    payload = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise HarnessError("invalid JSON response") from exc
                if not isinstance(payload, dict):
                    raise HarnessError("invalid JSON response object")
                terminal = payload.get("status", "http_error")
                content = payload.get("assistant_content")
                events = []
            return dict(http_status=response.status_code, terminal=terminal, content=content, payload=payload, events=events)


def reconcile(before, after, oracle, outcome):
    """Compare independent rows, not sequence allocator gaps or HTTP inference."""
    if (outcome["http_status"] != oracle["http_status"] or outcome["terminal"] != oracle["terminal"]):
        raise HarnessError("unexpected native wire outcome")
    for table in ("conversations", "messages"):
        old = {row["id"]: row for row in before[table]}
        new = {row["id"]: row for row in after[table]}
        if any(new.get(key) != value for key, value in old.items()):
            raise HarnessError("prior business row changed/disappeared")
        added = [row for key, row in new.items() if key not in old]
        expected = oracle["db_delta"][table]
        # Expected additions are exact projections with generated IDs/sequence
        # explicitly omitted. Persisted response IDs are checked separately.
        projected = [{key: row[key] for key in expected["fields"]} for row in added]
        if sorted(projected, key=canonical) != sorted(expected["rows"], key=canonical):
            raise HarnessError("partial/duplicate/unexpected business exchange")
    messages = {row["id"]: row for row in after["messages"] if row["id"] not in {old["id"] for old in before["messages"]}}
    payload = outcome["payload"]
    if messages:
        rows = list(messages.values())
        if (len(rows) != 2 or {row.get("role") for row in rows} != {"user", "assistant"}
                or len({row.get("conversation_id") for row in rows}) != 1
                or len({row.get("tenant_id") for row in rows}) != 1):
            raise HarnessError("exchange is not exactly one scoped complete pair")
        by_role = {row["role"]: row for row in rows}
        if not by_role["user"].get("sequence", 0) < by_role["assistant"].get("sequence", 0):
            raise HarnessError("exchange ordering invalid")
    if messages and oracle.get("client_outcome", "resolved") == "resolved":
        for role in ("user", "assistant"):
            row = messages.get(payload.get(f"{role}_message_id"))
            if row is None or row["role"] != role or row["conversation_id"] != payload.get("conversation_id"):
                raise HarnessError("wire/persisted identities disagree")
        if messages[payload["assistant_message_id"]]["content"] != outcome["content"]:
            raise HarnessError("wire/persisted content mismatch")
    if payload.get("sources", []) != oracle["sources"]:
        raise HarnessError("unexpected provenance")
    # Foreign-poison fixtures intentionally exist in the independent reader's
    # projection. Their presence there is not a leak into the HTTP response.
    serialized = canonical(outcome)
    if any(str(identifier).encode() in serialized for identifier in oracle["forbidden_ids"]):
        raise HarnessError("unauthorized identifier escaped")


async def terminate_run_backend(controller, *, database, pid, observed_pids):
    """Existing privilege only. Target exactly an observed run business backend."""
    if pid not in observed_pids or type(pid) is not int or pid <= 0:
        raise HarnessError("unobserved backend termination refused")
    from .fixtures import assert_database
    await assert_database(controller, database)
    row = (await controller.execute(text("SELECT datname,backend_type FROM pg_stat_activity WHERE pid=:pid"), dict(pid=pid))).one_or_none()
    if row is None or row.datname != database or row.backend_type != "client backend":
        raise HarnessError("backend identity mismatch")
    if not (await controller.execute(text("SELECT pg_terminate_backend(:pid)"), dict(pid=pid))).scalar_one():
        raise HarnessError("backend termination not permitted/completed")


async def drive_fault(kind, barrier, *, barriers, lifecycle, client_task, controller=None, database=None, visibility_reader=None, before=None, protocol=None):
    """One named local action; never confuse cancelling a client with a server."""
    await barriers.wait(barrier, timeout=10)
    started = asyncio.get_running_loop().time()
    proof = dict(action=kind, barrier=barrier, at=started)
    proof["barrier_at"] = next(at for name, at in reversed(barriers.timeline) if name == barrier)
    proof["purpose"] = "primary" if barrier == "primary_provider_wait" else None
    if barrier not in barriers.held:
        raise HarnessError("required action barrier was not held")
    if kind == "inspect_uncommitted":
        if visibility_reader is None or before is None:
            raise HarnessError("missing independent visibility reader")
        if protocol == "json" and "after_user_flush" not in [name for name, _ in barriers.timeline]:
            raise HarnessError("JSON visibility barrier precedes user flush")
        observed = await visibility_reader()
        for table in ("conversations", "messages"):
            if observed[table] != before[table]:
                raise HarnessError("uncommitted exchange visible to independent reader")
        proof.update(before_sha256=fingerprint({table: before[table] for table in ("conversations", "messages")}),
                     observed_sha256=fingerprint({table: observed[table] for table in ("conversations", "messages")}),
                     read_at=asyncio.get_running_loop().time())
    elif kind in {"disconnect", "postcommit_response_loss"}:
        checkpoint = None
        if barrier == "primary_before_dispatch":
            waiters = barriers.waiters.get(barrier, {})
            active = [r for r in lifecycle.requests if r['completed'] is None]
            if len(waiters) != 1 or len(active) != 1:
                raise HarnessError('ambiguous primary disconnect checkpoint')
            owner, checkpoint = next(iter(waiters.items()))
            if checkpoint['request'] is not active[0] or owner not in lifecycle.tasks:
                raise HarnessError('foreign primary disconnect checkpoint')
        client_task.cancel()  # actual HTTP client cancellation closes its stream
        if checkpoint is not None:
            await barriers.wait('http_disconnect', timeout=10)
            await asyncio.wait_for(checkpoint['cancelled'].wait(), timeout=10)
            if any(name == 'primary_provider_wait' for name, _ in barriers.timeline):
                raise HarnessError('primary provider entered before disconnect checkpoint settled')
            proof.update(purpose='primary', disconnect_observed=True, checkpoint_cancelled=True)
    elif kind == "server_cancel":
        requests = [row for row in lifecycle.requests if row["completed"] is None]
        waiters = barriers.waiters.get(barrier, {})
        if len(requests) != 1 or len(waiters) != 1:
            raise HarnessError("missing/ambiguous actual server task")
        owner, checkpoint = next(iter(waiters.items()))
        request = requests[0]
        if (owner is client_task or owner.done() or owner.cancelling()
                or checkpoint['request'] is not request
                or (owner is not request['task'] and owner not in lifecycle.tasks)):
            raise HarnessError("checkpoint owner outside current server execution")
        owner.cancel()
        # Do not release the checkpoint and race middleware cancellation
        # propagation. Acknowledgement means CancelledError reached the waiter.
        await asyncio.wait_for(checkpoint['cancelled'].wait(), timeout=10)
        proof['checkpoint_cancelled'] = True
    elif kind == "commit_connection_loss":
        if barrier != "before_commit" or controller is None or not lifecycle.backend_pids:
            raise HarnessError("commit fault lacks real backend/barrier")
        await terminate_run_backend(controller, database=database, pid=lifecycle.backend_pids[-1],
                                    observed_pids=lifecycle.backend_pids)
    else:
        raise HarnessError("unknown driver action")
    lifecycle.scenario_receipts.append(proof)
    if kind != "server_cancel" and barrier != "primary_before_dispatch":
        barriers.release(barrier)
    return started


@serial_case
async def execute_case(case, *, cfg, sessions, fixture, reference, dump_path, endpoint,
                       lifecycle, providers, transport_capture, barriers, request_id,
                       controller=None, action=None, source_root, source_files, manifest_raw):
    """Real-gate driver, intentionally not called by the offline control tests.

    A local API must already be running in this process/namespace, from its own
    fresh vector image. Preflight is read-only. This function never provisions,
    retries or repairs state. Fixture setup and the exact oracle precede it.
    Each instance uses a fresh capture; joining different requests is rejected.
    """
    body, frozen_cases = load_manifest(manifest_raw)
    identities = execution_identity(body, case)
    if case not in frozen_cases or identities["run_id"] != fixture.run_id:
        raise HarnessError("case outside frozen manifest")
    if (identities["fixture"] != fingerprint(fixture.rows()) or identities["config"] != config_identity(cfg)
            or identities["source"] != source_files):
        raise HarnessError("effective fixture/config/source drift")
    check_vector(case, cfg, reference)
    contract = scenario(case.family, case.protocol)
    if action is not None and action != contract["action"]:
        raise HarnessError("driver action differs from frozen scenario")
    action = contract["action"]
    if action and contract["barrier"] not in barriers.held:
        raise HarnessError("scenario requires held barrier before admission")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identities["images"].get(reference, "")):
        raise HarnessError("unpinned API image identity")
    if not re.fullmatch(r"[0-9a-f]{40}", identities.get("commit", "")):
        raise HarnessError("missing commit identity")
    app_files = {str(path.relative_to(source_root)) for path in (Path(source_root) / "app").rglob("*.py")}
    if not app_files or not app_files <= set(source_files):
        raise HarnessError("incomplete application source inventory")
    harness_files = identities["harness"]
    required_harness = {f"experiments/production_graduation/gate_validation/{name}.py"
                        for name in ("capture", "fixtures", "transports", "local_api", "validate_g123")}
    if not isinstance(harness_files, dict) or not required_harness <= set(harness_files):
        raise HarnessError("incomplete harness source inventory")
    verify_source(source_root, source_files)
    verify_source(source_root, harness_files)
    receipt = await preflight(cfg, sessions, run_id=fixture.run_id, reference=reference, dump_path=dump_path)
    if lifecycle.requests or transport_capture.bodies or lifecycle.snapshots:
        raise HarnessError("case requires fresh request/capture lifecycle")
    database = receipt["database"]
    async with sessions[0].begin():
        before = await readback(sessions[0], fixture, database)
    async def visibility_reader():
        async with sessions[0].begin():
            return await readback(sessions[0], fixture, database)
    oracle = json.loads(case.oracle_json)
    started = asyncio.get_running_loop().time()
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=None) as client:
        task = asyncio.create_task(http_operation(client, endpoint, case, request_id=request_id,
                                                  tenant=fixture.tenant(), timeout_s=cfg.provider_timeout_s + 10))
        try:
            if action is not None:
                started = await drive_fault(action, oracle["barrier"], barriers=barriers, lifecycle=lifecycle,
                                           client_task=task, controller=controller, database=database,
                                           visibility_reader=visibility_reader, before=before, protocol=case.protocol)
            try:
                outcome = await task
            except (asyncio.CancelledError, httpx.HTTPError, TimeoutError, HarnessError) as exc:
                if isinstance(exc, HarnessError) and action not in {"server_cancel", "disconnect", "postcommit_response_loss"}:
                    raise
                if oracle.get("client_outcome") != "unresolved":
                    raise HarnessError("unexpected unresolved HTTP operation") from None
                outcome = dict(http_status=None, terminal="unresolved", content=None, payload={}, events=[])
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    # HTTP completion is not proof of actual ASGI task/resource quiescence.
    deadline = (started if action else asyncio.get_running_loop().time()) + oracle["cleanup_s"]
    actual = [row["task"] for row in lifecycle.requests if row["completed"] is None]
    if actual:
        async with asyncio.timeout_at(deadline):
            await asyncio.gather(*actual, return_exceptions=True)
    await lifecycle.quiesce(deadline)
    async with sessions[0].begin():
        after = await readback(sessions[0], fixture, database)
    if len(lifecycle.requests) != 1:
        raise HarnessError("missing/duplicate actual ASGI execution")
    snapshot = original_snapshot = None
    instance_id = correlation_id = None
    if case.reference == "c1":
        if len(lifecycle.snapshots) != 1:
            raise HarnessError("missing/duplicate candidate snapshot")
        snapshot = lifecycle.snapshots[0]
        original_snapshot = copy.deepcopy(snapshot)
        instance_id, correlation_id = snapshot["instance_id"], snapshot["correlation_id"]
        if correlation_id != request_id:
            raise HarnessError("HTTP/observer correlation mismatch")
        if case.fault in {"lost_observation", "duplicate_observation", "reordered_observation", "wrong_execution",
                          "corrupt_observation", "wrong_attempt", "wrong_purpose"}:
            snapshot = observation_fault(snapshot, case.fault)
            lifecycle.faults_triggered.append(case.fault)
    result = await settle_case(case, before=before, after=after, outcome=outcome, lifecycle=lifecycle,
                              providers=providers, fault_started=deadline-oracle["cleanup_s"], snapshot=snapshot,
                              transport_capture=transport_capture, instance_id=instance_id, correlation_id=correlation_id)
    result["manifest_sha256"] = json.loads(manifest_raw)["sha256"]
    result["execution_identity_sha256"] = execution_identity_sha256(body, case)
    detail = dict(before=before, after=after, outcome=outcome, snapshot=snapshot, original_snapshot=original_snapshot,
                  timeline=list(barriers.timeline), preflight=receipt,
                  transport_bodies=[body.hex() for body in transport_capture.bodies],
                  transport_sends=copy.deepcopy(transport_capture.sends))
    if case.fault in {"history_error", "history_timeout", "retrieval_error", "retrieval_timeout",
                      "episodic_error", "telemetry_error", "telemetry_timeout", "observer_error"}:
        if case.fault not in lifecycle.faults_triggered:
            raise HarnessError("declared dependency fault was never exercised")
    if case.fault != "none" or case.family == "repeated_request_id":
        recovery = oracle.get("recovery")
        if not recovery:
            raise HarnessError("fault case lacks prospectively declared recovery control")
        recovery_case = Case(**recovery["case"])
        if recovery_case.fault != "none":
            raise HarnessError("recovery control must not inject another fault")
        # The driver must release the process-local one-shot fault through the
        # supplied function; no setting or production timeout is changed.
        reset = getattr(lifecycle, "release_fault", None)
        if reset is None and case.fault != "none":
            raise HarnessError("fault recovery lacks explicit release mechanism")
        if reset is not None:
            reset()
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=None) as client:
            recovery_outcome = await http_operation(client, endpoint, recovery_case,
                request_id=recovery["request_id"], tenant=fixture.tenant(), timeout_s=cfg.provider_timeout_s + 10)
        recovery_deadline = asyncio.get_running_loop().time() + 10
        pending = [row["task"] for row in lifecycle.requests if row["completed"] is None]
        async with asyncio.timeout_at(recovery_deadline):
            await asyncio.gather(*pending, return_exceptions=True)
        await lifecycle.quiesce(recovery_deadline)
        async with sessions[0].begin():
            recovered = await readback(sessions[0], fixture, database)
        reconcile(after, recovered, json.loads(recovery_case.oracle_json), recovery_outcome)
        if len(lifecycle.requests) != 2:
            raise HarnessError("missing/duplicate recovery ASGI execution")
        if case.family == "repeated_request_id":
            if recovery["request_id"] != request_id:
                raise HarnessError("repeated-header control used different headers")
            ids = {row["instance_id"] for row in transport_capture.sends}
            if len(ids) != 2 or None in ids:
                raise HarnessError("repeated header conflated actual execution identities")
        # This is a functional/session recovery control, not an additional C1
        # delivered claim. Its receipts remain available for independent review.
        detail["recovery"] = dict(outcome=recovery_outcome, after=recovered,
                                  snapshots=copy.deepcopy(lifecycle.snapshots[1:]))
    return result, detail


async def settle_case(case, *, before, after, outcome, lifecycle, providers, fault_started,
                      snapshot, transport_capture, instance_id, correlation_id):
    """Finalization after actual ASGI completion; invalid evidence never passes."""
    oracle = json.loads(case.oracle_json)
    deadline = fault_started + oracle["cleanup_s"]
    await lifecycle.quiesce(deadline)
    async with asyncio.timeout_at(deadline):
        for provider in providers:
            await provider.quiesce()
    if asyncio.get_running_loop().time() > deadline:
        raise HarnessError("cleanup bound missed")
    reconcile(before, after, oracle, outcome)
    verify_scenario(case, lifecycle, providers)
    evidence_valid = True
    if case.reference == "c1":
        # Lazy import is required: the original C0 image has no C1 observer.
        from .capture import EvidenceError, validate
        expectation = oracle["capture"]
        if not isinstance(expectation, dict):
            raise HarnessError("independent capture oracle required")
        expectation = dict(expectation)
        for field in ("expected_messages", "expected_data", "expected_purposes", "expected_invocation_outcomes"):
            expectation[field] = {int(key): value for key, value in expectation[field].items()}
        expectation["expected_messages"] = {key: [tuple(item) for item in rows] for key, rows in expectation["expected_messages"].items()}
        for field in ("expected_rendered_messages", "expected_pre_dispatch_failures"):
            if field in expectation:
                values = expectation[field]
                if (not isinstance(values, dict)
                        or any(not isinstance(key, str) or not key.isdecimal()
                               or str(int(key)) != key or int(key) <= 0 for key in values)):
                    raise HarnessError("invalid explicit render/failure oracle keys")
                expectation[field] = {int(key): value for key, value in values.items()}
        if "expected_rendered_messages" in expectation:
            expectation["expected_rendered_messages"] = {
                key: [tuple(item) for item in rows]
                for key, rows in expectation["expected_rendered_messages"].items()}
        try:
            validate(snapshot, expected_instance_id=instance_id, expected_correlation_id=correlation_id,
                     transport_capture=transport_capture, **expectation)
        except EvidenceError:
            evidence_valid = False
        if evidence_valid != (oracle["evidence_expected"] == "valid"):
            raise HarnessError("unexpected observer acceptance/rejection")
    if oracle["positive_delivery"] and not transport_capture.bodies:
        raise HarnessError("empty positive delivery")
    if oracle["positive_delivery"] and case.reference == "c1" and evidence_valid:
        positive_delivery(oracle, transport_capture)
    return dict(case_id=case.case_id, status="PASS", before_sha256=fingerprint(before),
                after_sha256=fingerprint(after), evidence_valid=evidence_valid, scenario_verified=True,
                case_sha256=fingerprint(case.__dict__), external_provider_calls=0)


def verify_scenario(case, lifecycle, providers):
    contract = scenario(case.family, case.protocol)
    if contract["action"]:
        proofs = [proof for proof in lifecycle.scenario_receipts if proof.get("action") == contract["action"]]
        if len(proofs) != 1 or proofs[0].get("barrier") != contract["barrier"]:
            raise HarnessError("missing/duplicate scenario action proof")
        proof = proofs[0]
        if not proof.get("barrier_at", float("inf")) <= proof["at"]:
            raise HarnessError("scenario action precedes barrier")
        if contract["barrier"] == "primary_provider_wait" and proof.get("purpose") != "primary":
            raise HarnessError("primary-purpose barrier proof missing")
        if contract['barrier'] == 'primary_before_dispatch' and not (
                proof.get('purpose') == 'primary' and proof.get('disconnect_observed')
                and proof.get('checkpoint_cancelled')):
            raise HarnessError('missing primary disconnect/cancellation proof')
        if case.family == "uncommitted_visibility" and (not proof.get("before_sha256") or proof.get("before_sha256") != proof.get("observed_sha256") or proof.get("read_at", 0) < proof["at"]):
            raise HarnessError("missing held-transaction visibility proof")
    if contract["marker"]:
        markers = list(lifecycle.faults_triggered)
        for provider in providers:
            markers.extend(getattr(getattr(provider, "provider", provider), "fault_events", []))
        if contract["marker"] not in markers:
            raise HarnessError("required fault was not exercised")
    if case.family in {"partial_stream_error", "cancel_after_token", "disconnect_after_token"}:
        if not any(event.get("type") == "wire_token" for request in lifecycle.requests for event in request["events"]):
            raise HarnessError("no actual ASGI token delivery proof")


def positive_delivery(oracle, capture):
    """Require declared nonempty source spans on primary serialized sends.

    Full stage equality is already enforced by capture.validate. This additional
    coverage check prevents counting a rewrite-only or empty-context send as a
    positive four-stage proof. Span expectations are private synthetic fixtures.
    """
    spans = oracle.get("delivered_spans")
    if not isinstance(spans, list) or not spans:
        raise HarnessError("positive case requires explicit source spans")
    expected = oracle["capture"]
    for span in spans:
        invocation = str(span["invocation"])
        if expected["expected_purposes"].get(invocation) != "primary":
            raise HarnessError("auxiliary dispatch cannot certify primary delivery")
        messages = expected["expected_messages"][invocation]
        text = messages[span["message_index"]][1]
        if (not span["text"] or type(span["start"]) is not int or type(span["end"]) is not int
                or not 0 <= span["start"] < span["end"] <= len(text)
                or text[span["start"]:span["end"]] != span["text"] or not span["source_id"]):
            raise HarnessError("independent source/span oracle mismatch")
        channels = {"documents": ("documents.retrieved", "documents.selected"),
                    "window": ("window.read", "window.bounded"),
                    "episodic": ("episodic.retrieved", "episodic.selected")}
        if span.get("channel") not in channels:
            raise HarnessError("positive source channel missing")
        data_by_stage = {stage: expected["expected_data"][str(index)]
                         for index, stage in enumerate(expected["expected_stages"])
                         if str(index) in expected["expected_data"]}
        key = str(span["source_id"])
        for stage in channels[span["channel"]]:
            if not any(row["key"] == key for row in data_by_stage.get(stage, {}).get("items", [])):
                raise HarnessError("positive source was not retrieved and selected")
        packed = data_by_stage.get("context.packed", {}).get(span["channel"], [])
        if not any(row["key"] == key and row["sha256"] == hashlib.sha256(span["text"].encode()).hexdigest() for row in packed):
            raise HarnessError("positive source span missing from packed context")
        if not any(row["purpose"] == "primary" and row["invocation"] == int(invocation) for row in capture.sends):
            raise HarnessError("no corresponding actual primary dispatch")


def private_write(directory, name, value):
    """Private immutable-attempt artifacts. Refuse collisions and symlinks."""
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077 or Path(name).name != name:
        raise HarnessError("unsafe private artifact path")
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def functional_projection(case, outcome):
    """Normalize only declared generated wire IDs, never text/event ordering."""
    result = copy.deepcopy(outcome)
    payload = outcome["payload"]
    names = ["user_message_id", "assistant_message_id"]
    if json.loads(case.oracle_json)["db_delta"]["conversations"]["rows"]:
        names.append("conversation_id")
    aliases = {key: f"<generated:{key}>" for key in names if payload.get(key)}
    for item in [result["payload"], *[data for kind, data in result["events"] if kind in {"done", "error"}]]:
        for key, alias in aliases.items():
            if key in item:
                item[key] = alias
    return result


def package_result(cases, results, details, required_cells, *, manifest_raw=None):
    """No partial/skip/double-backed package can produce a gate PASS."""
    check_matrix(cases, required_cells)
    if manifest_raw is None:
        raise HarnessError("frozen package manifest required")
    body, frozen_cases = load_manifest(manifest_raw)
    if list(cases) != frozen_cases:
        raise HarnessError("package differs from frozen manifest")
    manifest_sha = json.loads(manifest_raw)["sha256"]
    expected = {case.case_id for case in cases}
    if set(results) != expected or set(details) != expected or any(row.get("status") != "PASS" for row in results.values()):
        raise HarnessError("incomplete/failed package")
    if any(results[case.case_id].get("case_sha256") != fingerprint(case.__dict__) or results[case.case_id].get("manifest_sha256") != manifest_sha or results[case.case_id].get("execution_identity_sha256") != execution_identity_sha256(body, case) or results[case.case_id].get("scenario_verified") is not True for case in cases):
        raise HarnessError("case/manifest/scenario receipt mismatch")
    positives = {(case.protocol, case.adapter, case.language) for case in cases
                 if case.vector == "C1" and json.loads(case.oracle_json)["positive_delivery"]
                 and results[case.case_id].get("evidence_valid") is True
                 and details[case.case_id].get("transport_bodies")}
    needed = {(protocol, adapter, language) for protocol in ("json", "sse")
              for adapter in ("bedrock", "openai") for language in ("en", "es")}
    if not needed <= positives:
        raise HarnessError("missing nonempty delivered coverage")
    index = {cell_key(case): case for case in cases}
    for case in cases:
        if case.reference == "c1" and case.vector in {"C1", "OFF"}:
            baseline = index.get((case.family, "C0" if case.vector == "C1" else "OFF", "c0", case.protocol, case.adapter, case.language))
            if case.family in OBSERVATION_FAULTS or case.family == "observer_error":
                continue  # C0 has no observer; not an applicable observer-fault cell.
            if baseline is None:
                raise HarnessError("missing matched baseline")
            if functional_projection(case, details[case.case_id]["outcome"]) != functional_projection(baseline, details[baseline.case_id]["outcome"]):
                raise HarnessError("baseline/candidate functional mismatch")
    return dict(status="G123_HARNESS_PACKAGE_PASS", cases=len(cases), external_provider_calls=0,
                g9_executed=False, decision_freeze="BLOCKED", independent_review_required=True)
