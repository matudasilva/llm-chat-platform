"""One fresh full-C1 worker:20 representative warmups then25 measurements."""
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx

from .aa_calibration_resources import resource_delta, worker_resources
from .blocked_latency import (SCHEMA, CONTRACT_SHA256, require, seed_probe, write_json)
from .capture import Capture
from .controlled_latency import candidate_evidence, request_deadline
from .local_api import install
from .performance_cleanup import release_validated_case
from .transports import Reply, native_provider, _purpose


async def run_block(asgi, lifecycle, scoped, capture, replies, plan, entry):
    """The actual production-worker request loop, also exercised by local stubs."""
    samples = [sample for sample in plan["samples"] if sample["block"] == entry["block"]
               and sample["language"] + "-" + sample["protocol"] == entry["cell"]]
    require(len(samples) == 45 and [sample["warmup"] for sample in samples] == [True] * 20 + [False] * 25,
            "Worker block/warmup population changed")
    current = {}
    original = capture.sent

    def sent(body, **kwargs):
        at = time.monotonic_ns()
        raw = body.encode() if isinstance(body, str) else bytes(body)
        purpose = _purpose.get()
        if purpose == 'primary':
            current['primary_ns'].append(at)
        current['dispatches'].append({'purpose': purpose, 'sha256': hashlib.sha256(raw).hexdigest()})
        return original(body, **kwargs)

    capture.sent = sent

    async def ingress(scope, receive, send):
        if scope.get('path') == '/chat':
            current['start_ns'] = time.monotonic_ns()
        await asgi(scope, receive, send)

    rows, seen_instances = [], set()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ingress), base_url="http://local") as client:
            for sample in samples:
                current.clear()
                current.update(primary_ns=[], dispatches=[])
                replies["rewrite"] = Reply(sample["message"])
                status, error, instance = "FAIL", None, None
                try:
                    async with request_deadline(plan["request_deadline_s"]):
                        response = await client.post("/chat", json=dict(
                            message=sample["message"], conversation_id=sample["conversation_id"],
                            stream=sample["protocol"] == "sse"), headers={
                                "X-Request-ID": sample["request_id"], "X-Tenant-ID": sample["tenant_id"]}, timeout=30)
                        require(response.status_code == 200, "Controlled HTTP failure")
                        if sample["protocol"] == "json":
                            terminal = response.json()
                        else:
                            from .validate_g123 import parse_sse
                            parsed = parse_sse(response.content)
                            require(parsed[-1][0] == "done", "Controlled SSE failure")
                            terminal = parsed[-1][1]
                        require(terminal.get("status") == "success"
                                and terminal.get("request_id") == sample["request_id"]
                                and terminal.get("conversation_id") == sample["conversation_id"],
                                "Controlled response completion/identity mismatch")
                        await lifecycle.quiesce(asyncio.get_running_loop().time() + plan["cleanup_bound_s"])
                        require(len(current["primary_ns"]) == 1
                                and [row["purpose"] for row in current["dispatches"]] == ["rewrite", "primary"],
                                "Ambiguous controlled dispatches")
                        instance = candidate_evidence(lifecycle.snapshots, capture.sends, sample["request_id"])
                        require(instance not in seen_instances, "Reused full-C1 accounting instance")
                    seen_instances.add(instance)
                    status = "PASS"
                except Exception as exc:
                    error = type(exc).__name__ + ": " + str(exc)[:100]
                rows.append(dict(sample, status=status, error=error, accounting_instance_id=instance,
                    start_ns=current.get("start_ns"),
                    primary_dispatch_ns=current["primary_ns"][0] if len(current["primary_ns"]) == 1 else None,
                    preparation_ns=current["primary_ns"][0] - current["start_ns"]
                        if len(current["primary_ns"]) == 1 and "start_ns" in current else None,
                    dispatches=list(current["dispatches"])))
                if status != "PASS":
                    break
                try:
                    release_validated_case(lifecycle, capture, scoped, rows[-1], candidate=True)
                except Exception as exc:
                    rows[-1].update(status="FAIL", error="cleanup: " + type(exc).__name__ + ": " + str(exc)[:100])
                    break
        return rows
    finally:
        capture.sent = original


async def main():
    from .validate_g123 import check_p2, check_config, config_identity
    check_p2()
    require(not sys.flags.optimize, "Optimized interpreter is not allowed")
    out = Path(os.environ["G6_RUN_DIR"])
    plan = json.loads((out / "plan.json").read_text())
    entry = dict(arm=os.environ["G6_ARM"], cell=os.environ["G6_CELL"], block=int(os.environ["G6_BLOCK"]))
    require(plan["schema"] == SCHEMA and plan["amendment_sha256"] == CONTRACT_SHA256
            and plan["mode"] == "aa_full_c1_both_arms" and plan["full_c1_both_arms"] is True
            and plan["images"]["c0"] == plan["images"]["c1"]
            and entry in plan["arm_cell_order"], "Only the frozen full-C1 A/A block is supported")
    from .g9_controller import sha_file
    require(json.loads((out / "execution-started.json").read_text())["plan_sha256"] == sha_file(out / "plan.json"),
            "Worker lacks frozen execution admission")
    probe = seed_probe()
    require(probe == plan["seed_probe"], "Worker process seed/interpreter drift")
    key = f'{entry["arm"]}-{entry["cell"]}-b{entry["block"]}'
    require(not (out / (key + ".json")).exists(), "Never repeat a published block")
    write_json(out / (key + "-started.json"), dict(plan_sha256=sha_file(out / "plan.json"), entry=entry))
    from app.core.settings import settings
    check_config(settings)
    require(config_identity(settings) == plan["config_sha256"][entry["arm"]], "Worker settings drift")
    require(not settings.ebm25_enabled and settings.chat_rag_augmentation_enabled
            and settings.conversation_history_enabled, "Controlled vector changed")
    from app.main import app
    capture = Capture()
    replies = dict(rewrite=Reply(""), evaluator=Reply("[]"), primary=Reply("Controlled local response."))
    provider, close = native_provider("bedrock", capture, replies)
    provider._cfg = replace(provider._cfg, model=settings.bedrock_model,
                            timeout_s=settings.provider_timeout_s, max_attempts=settings.bedrock_max_attempts)
    asgi, lifecycle, scoped = install(app, provider=provider, candidate=True,
        cache_namespace=f'orq41:g123:{plan["run_id"]}:{key}:')
    try:
        async with app.router.lifespan_context(app):
            before = worker_resources()
            require(before["topology"] == plan["cpu_topology"], "Topology/governor drift")
            rows = await run_block(asgi, lifecycle, scoped, capture, replies, plan, entry)
            after = worker_resources()
        result = dict(**entry, full_c1=True, samples=rows, resources_before=before, resources_after=after,
                      cpu_stat_delta=resource_delta(before, after), config_identity=config_identity(settings),
                      seed_probe=probe, provider_calls=0, external_calls=0)
        write_json(out / (key + ".json"), result)
    finally:
        try:
            await scoped.quiesce()
        finally:
            await close()


if __name__ == "__main__":
    asyncio.run(main())
