"""Balanced A/A protocol controls; only local doubles and memory-native transports."""
import ast
import asyncio
from collections import Counter
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid5

import pytest

from experiments.production_graduation.gate_validation import blocked_latency as driver
from experiments.production_graduation.gate_validation import blocked_latency_worker as worker


PASSWORDS = dict.fromkeys(("POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD", "POSTGRES_OPS_PASSWORD"), "local-test-only")


@pytest.fixture
def packet():
    plan, fixtures = driver.make_plan(UUID(int=1441), "261109010101")
    plan.update(config_sha256={"c0": "a" * 64, "c1": "b" * 64},
                normalized_config_sha256="c" * 64,
                seed_probe=dict(seed="41", string_hash=41, python="pinned", hash_algorithm="siphash13", hash_width=64))
    return plan, fixtures


def resources(plan, cpus=(0, 2), value=1):
    return dict(affinity=list(cpus), effective_cpuset=list(cpus), cpu_max="200000 100000",
                topology=plan["cpu_topology"], cpu_stat=dict(usage_usec=value, nr_periods=value,
                                                           nr_throttled=0, throttled_usec=0))


def receipt(plan, entry, duration=1000):
    number = plan["arm_cell_order"].index(entry)
    samples = [sample for sample in plan["samples"] if sample["block"] == entry["block"]
               and sample["language"] + "-" + sample["protocol"] == entry["cell"]]
    rows = []
    for index, sample in enumerate(samples):
        at = (number * 100 + index + 1) * 10**9
        rows.append(dict(sample, status="PASS", error=None,
            accounting_instance_id=str(uuid5(UUID(int=1442), entry["arm"] + sample["sample_id"])),
            start_ns=at, primary_dispatch_ns=at + duration, preparation_ns=duration,
            dispatches=[dict(purpose=purpose, sha256="a" * 64) for purpose in ("rewrite", "primary")]))
    before, after = resources(plan), resources(plan, value=2)
    return dict(**entry, full_c1=True, samples=rows, config_identity=plan["config_sha256"][entry["arm"]],
                seed_probe=plan["seed_probe"], resources_before=before, resources_after=after,
                cpu_stat_delta=driver.resource_delta(before, after), provider_calls=0, external_calls=0)


def arms(plan, a=1000, b=1000):
    result = {arm: [] for arm in driver.ARMS}
    for entry in plan["arm_cell_order"]:
        result[entry["arm"]].extend(receipt(plan, entry, a if entry["arm"] == "c0" else b)["samples"])
    return result


def write_packet(path, packet):
    plan, fixtures = packet
    driver.write_json(path / "plan.json", plan)
    driver.write_json(path / "fixtures.json", fixtures)
    driver.write_json(path / "credentials/local-credentials.json", PASSWORDS)
    analyses = [dict(database=database, settings={}, completion=dict.fromkeys(driver.TABLES, "completed"),
                    statements=[f'ANALYZE "public"."{table}";' for table in driver.TABLES])
                for database in plan["databases"].values()]
    prep = dict(status="BLOCKED_AA_PREPARED_NOT_EXECUTED", plan_sha256=driver.sha_file(path / "plan.json"),
                fixtures_sha256=driver.sha_file(path / "fixtures.json"), private_state=str(path / "credentials"),
                databases=[], analyses=analyses, api_requests=0, config_probes=[
                    dict(config=plan["config_sha256"][arm], normalized=plan["normalized_config_sha256"],
                         seed=plan["seed_probe"]) for arm in driver.ARMS])
    driver.write_json(path / "preparation.json", prep)
    driver.write_json(path / "independent-review.json", dict(status="BLOCKED_AA_HARNESS_REVIEW_PASS",
        plan_sha256=driver.sha_file(path / "plan.json"), fixtures_sha256=driver.sha_file(path / "fixtures.json"),
        preparation_sha256=driver.sha_file(path / "preparation.json")))
    driver.write_json(path / "execution-authorization.json", dict(status="OPERATOR_AUTHORIZED_BLOCKED_AA_EXECUTION",
                                                                 plan_sha256=driver.sha_file(path / "plan.json")))
    return prep


def test_exact_business_population_balanced_order_and_fresh_identity(packet):
    plan, fixtures = packet
    assert len(plan["samples"]) == len(fixtures) == 720
    assert sum(not sample["warmup"] for sample in plan["samples"]) == 400
    assert sum(len(fixture["messages"]) for fixture in fixtures) == 17280
    assert len({s["request_id"] for s in plan["samples"]}) == 720
    assert len({s["conversation_id"] for s in plan["samples"]}) == 720
    assert len(plan["arm_cell_order"]) == 32
    for cell in driver.CELLS:
        samples = [s for s in plan["samples"] if s["language"] + "-" + s["protocol"] == cell]
        measured = [s for s in samples if not s["warmup"]]
        assert Counter(s["category"] for s in measured) == dict.fromkeys(driver.CATEGORIES, 25)
        assert set(Counter(s["case_id"] for s in measured).values()) == {5}
        assert Counter(next(e["arm"] for e in plan["arm_cell_order"] if e["cell"] == cell and e["block"] == b)
                       for b in range(4)) == {"c0": 2, "c1": 2}
        for b in range(4):
            block = [s for s in samples if s["block"] == b]
            assert [s["warmup"] for s in block] == [True] * 20 + [False] * 25
            assert Counter(s["category"] for s in block[:20]) == dict.fromkeys(driver.CATEGORIES, 5)
            assert len({s["case_id"] for s in block[:20]}) == 20
    cases = json.loads((driver.ORQ / "paid-execution/cases.json").read_text())["cases"]
    again, _, _ = driver.build_samples(cases, UUID(int=1443))
    assert not {s["request_id"] for s in again} & {s["request_id"] for s in plan["samples"]}
    assert not {s["conversation_id"] for s in again} & {s["conversation_id"] for s in plan["samples"]}


@pytest.mark.parametrize("field,value", [("mode", "formal_g6"), ("concurrency", 2), ("n_per_cell_arm", 99),
    ("sample_attempts", True), ("warmups_per_block_arm", 5), ("boundary", "later"), ("symmetric_limit_percent", 6)])
def test_frozen_contract_drift_is_rejected_before_operations(packet, field, value):
    plan, fixtures = packet
    plan[field] = value
    with pytest.raises(ValueError):
        driver.validate_plan(plan, fixtures, prepared=True)


@pytest.mark.parametrize("fault", ["phase", "fixture", "order", "uuid", "images", "seed"])
def test_population_identity_and_full_c1_drift_never_pass(packet, fault):
    plan, fixtures = packet
    if fault == "phase": plan["samples"][20]["warmup"] = True
    elif fault == "fixture": fixtures[0]["messages"].append(dict(role="user", content="changed"))
    elif fault == "order": plan["arm_cell_order"].reverse()
    elif fault == "uuid": plan["samples"][1]["request_id"] = plan["samples"][0]["request_id"]
    elif fault == "images": plan["images"]["c0"] = "different"
    else: plan["seed_probe"] = None
    with pytest.raises(ValueError): driver.validate_plan(plan, fixtures, prepared=True)


@pytest.mark.parametrize("a,b,expected", [(1000,1000,"PASS"), (1000,1050,"PASS"), (1050,1000,"PASS"),
    (1000,1051,"FAIL"), (1051,1000,"FAIL"), (0,0,"PASS"), (0,1,"FAIL"), (1,0,"FAIL")])
def test_symmetric_forward_reverse_and_zero_boundaries(packet, a, b, expected):
    plan, _ = packet
    result = driver.summarize(arms(plan, a, b), plan)
    assert result["status"] == "AA_CALIBRATION_" + expected
    assert result["request_count"] == result["accounting_instances"] == 1440
    assert result["official_g6_status"] == "CONTROLLED_G6_FAIL"


def test_primary_p95_pools100durations_and_never_averages_block_quantiles(packet):
    plan, _ = packet
    data = arms(plan, 100, 100)
    for row in data["c1"]:
        value = 10**8 if row["warmup"] else [90, 100, 110, 120][row["block"]]
        row.update(preparation_ns=value, primary_dispatch_ns=row["start_ns"] + value)
    result = driver.summarize(data, plan)
    assert all(cell["c1_p95_ns"] == 120 and cell["status"] == "FAIL" for cell in result["cells"])
    assert len(result["descriptive_blocks"]) == 32


@pytest.mark.parametrize("fault", ["missing", "duplicate", "failure", "context", "payload", "warmup", "clock"])
def test_missing_contradictory_or_failed_evidence_never_qualifies(packet, fault):
    plan, _ = packet
    data = arms(plan)
    if fault == "missing": data["c1"].pop()
    elif fault == "duplicate": data["c1"][1] = copy.deepcopy(data["c1"][0])
    elif fault == "failure": data["c1"][0]["status"] = "FAIL"
    elif fault == "context": data["c1"][0]["accounting_instance_id"] = data["c0"][0]["accounting_instance_id"]
    elif fault == "payload": data["c1"][0]["dispatches"][0]["sha256"] = "b" * 64
    elif fault == "warmup": data["c1"][20]["warmup"] = True
    else: data["c1"][0]["primary_dispatch_ns"] += 1
    with pytest.raises((ValueError, KeyError)): driver.summarize(data, plan)


def test_seed_propagates_before_startup_and_matches_fresh_interpreter(packet, monkeypatch):
    plan, _ = packet
    values = driver.worker_environment(plan, PASSWORDS, dict(arm="c1", cell="EN-sse", block=2))
    assert values["PYTHONHASHSEED"] == "41" and values["G6_BLOCK"] == "2"
    code = "import json;from experiments.production_graduation.gate_validation.blocked_latency import seed_probe;print(json.dumps(seed_probe()))"
    results = [subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True,
                             env={**os.environ, "PYTHONHASHSEED": "41"}).stdout for _ in range(2)]
    assert json.loads(results[0]) == json.loads(results[1])
    monkeypatch.setenv("PYTHONHASHSEED", "42")
    with pytest.raises(ValueError): driver.seed_probe()


def test_settings_probes_preserve_container_guard_path_and_paired_role_databases(packet):
    plan, _ = packet
    for arm in driver.ARMS:
        values = driver.worker_environment(plan, PASSWORDS, arm=arm)
        assert values["PYTHONPATH"] == "/p2_netguard:/app" and values["PYTHONHASHSEED"] == "41"
        assert all(values[name].endswith("/" + plan["databases"][arm])
                   for name in ("DATABASE_URL", "DATABASE_URL_APP", "DATABASE_URL_OPS"))
        assert values["APP_SETTINGS_ENV_FILE"] == "" and values["AWS_EC2_METADATA_DISABLED"] == "true"


def test_real_settings_only_probes_match_across_fresh_processes_without_connecting(packet):
    plan, _ = packet;results = []
    code = ("import json;from experiments.production_graduation.gate_validation import blocked_latency as d;"
            "d.worker_resources=lambda: {'unit_double':True};print(json.dumps(d.configuration_probe()))")
    for arm in driver.ARMS:
        env = {**os.environ, **driver.worker_environment(plan, PASSWORDS, arm=arm)}
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
        result = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True, env=env)
        assert "local-test-only" not in result.stdout
        results.append(json.loads(result.stdout))
    assert results[0]["normalized"] == results[1]["normalized"]
    assert results[0]["seed"] == results[1]["seed"] and results[0]["config"] != results[1]["config"]


@pytest.mark.parametrize("fault", ["review_missing", "execution_missing", "wrong_review", "source", "prep", "restart"])
def test_review_authorization_integrity_and_restart_guards_precede_docker(packet, tmp_path, monkeypatch, fault):
    write_packet(tmp_path, packet)
    if fault == "review_missing": (tmp_path / "independent-review.json").unlink()
    elif fault == "execution_missing": (tmp_path / "execution-authorization.json").unlink()
    elif fault == "wrong_review": (tmp_path / "independent-review.json").write_text('{"status":"wrong"}')
    elif fault == "source":
        plan = json.loads((tmp_path / "plan.json").read_text());plan["harness_sha256"].clear()
        (tmp_path / "plan.json").write_text(json.dumps(plan))
    elif fault == "prep": (tmp_path / "preparation.json").write_text('{}')
    else: driver.write_json(tmp_path / "execution-started.json", {})
    monkeypatch.setattr(driver, "docker", lambda *a, **k: pytest.fail("Docker before review/authorization"))
    monkeypatch.setattr(driver.aa, "docker", lambda *a, **k: pytest.fail("Database I/O before review/authorization"))
    with pytest.raises((ValueError, FileNotFoundError, KeyError)): driver.execute(tmp_path)


def test_preparation_needs_separate_environment_authorization(tmp_path, monkeypatch):
    approval = tmp_path / "approval.json";approval.write_text('{"status":"IMPLEMENTATION_ONLY"}')
    monkeypatch.setattr(driver, "docker", lambda *a, **k: pytest.fail("Unapproved preparation"))
    with pytest.raises(ValueError): driver.prepare(approval)


@pytest.mark.parametrize("fault", ["seed", "resource", "incomplete", "cleanup", "context", "phase", "identity"])
def test_worker_receipt_rejects_incomplete_or_contradictory_evidence(packet, fault):
    plan, _ = packet;entry = plan["arm_cell_order"][0];data = receipt(plan, entry)
    if fault == "seed": data["seed_probe"] = dict(data["seed_probe"], seed="42")
    elif fault == "resource": data["resources_after"]["affinity"] = [16, 17]
    elif fault == "incomplete": data["samples"].pop()
    elif fault == "cleanup": data["samples"][-1].update(status="FAIL", error="cleanup failure")
    elif fault == "context": data["samples"][1]["accounting_instance_id"] = data["samples"][0]["accounting_instance_id"]
    elif fault == "phase": data["samples"][20]["warmup"] = True
    else: data["samples"][0]["request_id"] = str(UUID(int=999))
    with pytest.raises(ValueError): driver.validate_worker(data, plan, entry)


def test_readiness_probe_is_loopback_only_and_has_no_application_or_provider_start(packet, monkeypatch):
    plan, _ = packet;calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        assert args[args.index("--network") + 1] == "container:" + plan["containers"]["postgres"]
        assert "--pull=never" in args and "127.0.0.1" in args[-1]
        tree = ast.parse(args[-1]);imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert imports == ["experiments.production_graduation.gate_validation.validate_g123"]
        return b"BLOCKED_AA_LOCAL_SERVICES_READY\n"
    monkeypatch.setattr(driver, "docker", docker)
    driver.check_local_services(plan, Path("private-local.env"))
    assert len(calls) == 1


class AnalyzeDB:
    def __init__(self, plan, fault=None):
        self.container = plan["containers"]["postgres"]
        self.calls, self.fault = [], fault
    def schema_hash(self, database): return "a" * 64
    def sql(self, database, query):
        self.calls.append((database, query))
        if query.startswith("ANALYZE "):
            if self.fault == "operation" and len([q for _, q in self.calls if q.startswith("ANALYZE ")]) == 2:
                raise RuntimeError("injected ANALYZE failure")
            return ""
        if "pg_tables" in query: return json.dumps(list(driver.TABLES)[:-1] if self.fault == "inventory" else list(driver.TABLES))
        if "pg_settings" in query: return json.dumps({"autovacuum": "on"})
        if "last_analyze" in query: return json.dumps(dict.fromkeys(driver.TABLES, None if self.fault == "completion" else "complete"))
        pytest.fail("Unexpected SQL in double")


def test_analyze_is_exactly_once_on_seven_allowed_disposable_tables(packet):
    plan, _ = packet;db = AnalyzeDB(plan)
    result = driver.analyze_database(db, plan, plan["databases"]["c0"])
    assert result["statements"] == [q for _, q in db.calls if q.startswith("ANALYZE ")]
    assert len(result["statements"]) == 7 and len(set(result["statements"])) == 7
    assert all(q.startswith("ANALYZE ") or q.startswith("BEGIN READ ONLY;\n") for _, q in db.calls)
    before = list(db.calls)
    with pytest.raises(ValueError): driver.analyze_database(db, plan, "orq41")
    assert db.calls == before


@pytest.mark.parametrize("fault", ["inventory", "operation", "completion"])
def test_analyze_failure_never_continues_to_admission(packet, fault):
    plan, _ = packet;db = AnalyzeDB(plan, fault)
    with pytest.raises((ValueError, RuntimeError)): driver.analyze_database(db, plan, plan["databases"]["c0"])
    assert len([q for _, q in db.calls if q.startswith("ANALYZE ")]) == ({"inventory":0, "operation":2, "completion":7}[fault])


def test_host_metric_snapshots_reject_missing_reset_but_never_filter_frequency(tmp_path):
    proc = tmp_path / "stat"
    proc.write_text("\n".join(f'cpu{i} ' + ' '.join(['1'] * 10) for i in range(8)))
    for cpu in (0, 2, 4, 6):
        folder = tmp_path / f"cpu{cpu}/cpufreq";folder.mkdir(parents=True)
        (folder / "scaling_cur_freq").write_text("1000000")
    a = driver.host_snapshot(proc, tmp_path)
    (tmp_path / "cpu0/cpufreq/scaling_cur_freq").write_text("2000000")
    b = driver.host_snapshot(proc, tmp_path)
    assert all(set(delta) == {0} for delta in driver.host_delta(a, b).values())
    b["cpu_ticks"]["cpu0"][0] = 0
    with pytest.raises(ValueError): driver.host_delta(a, b)
    proc.write_text(proc.read_text().replace("cpu7", "cpu6"))
    with pytest.raises(ValueError): driver.host_snapshot(proc, tmp_path)


def test_database_reset_and_decreasing_counters_fail_closed():
    before = {arm: dict(counters=dict(datid="1", datname=arm, stats_reset=None,
                                     **dict.fromkeys(driver.DB_COUNTERS, 2))) for arm in driver.ARMS}
    after = copy.deepcopy(before)
    assert all(set(row.values()) == {0} for row in driver.database_delta(before, after).values())
    after["c0"]["counters"]["stats_reset"] = "reset"
    with pytest.raises(ValueError): driver.database_delta(before, after)
    after = copy.deepcopy(before);after["c1"]["counters"]["blks_hit"] = 1
    with pytest.raises(ValueError): driver.database_delta(before, after)


def projection(fixture, namespace, arm):
    sample = fixture["sample"];cid = sample["conversation_id"];rows = []
    content = [*fixture["messages"], dict(role="user", content=sample["message"]),
               dict(role="assistant", content="Controlled local response.")]
    for index, message in enumerate(content):
        key = sample["sample_id"] + "/history/" + str(index) if index < len(fixture["messages"]) else arm + str(index)
        rows.append(dict(id=str(uuid5(UUID(namespace), key)), conversation_id=cid,
                         tenant_id=sample["tenant_id"], sequence=index + 1, **message))
    return dict(conversations=[dict(id=cid, tenant_id=sample["tenant_id"])], messages=rows)


def test_exact_history_and_committed_exchange_proof_normalizes_only_new_uuids(packet):
    plan, fixtures = packet;fixture = next(f for f in fixtures if f["sample"]["category"] == "history")
    a, b = [driver.verify_projection(projection(fixture, plan["namespace"], arm), [fixture], plan["namespace"], final=True)
            for arm in driver.ARMS]
    assert a == b and a["generated_message_ids"] == 2


@pytest.mark.parametrize("fault", ["missing", "duplicate", "history", "content", "uuid", "tenant", "sequence"])
def test_partial_duplicate_foreign_or_changed_persistence_never_passes(packet, fault):
    plan, fixtures = packet;fixture = next(f for f in fixtures if f["sample"]["category"] == "history")
    data = projection(fixture, plan["namespace"], "c0")
    if fault == "missing": data["messages"].pop()
    elif fault == "duplicate": data["messages"].append(copy.deepcopy(data["messages"][-1]))
    elif fault == "history": data["messages"][0]["content"] += "changed"
    elif fault == "content": data["messages"][-1]["content"] = "wrong"
    elif fault == "uuid": data["messages"][-1]["id"] = "invalid"
    elif fault == "tenant": data["messages"][-1]["tenant_id"] = "foreign"
    else: data["messages"][-1]["sequence"] = data["messages"][0]["sequence"]
    with pytest.raises(ValueError): driver.verify_projection(data, [fixture], plan["namespace"], final=True)


@pytest.mark.parametrize("fault", [None, "exit", "cleanup", "observation"])
def test_controller_simulation_completes_only_valid_blocks_and_never_resends(packet, tmp_path, monkeypatch, fault):
    plan, _ = packet;prep = write_packet(tmp_path, packet);calls = []
    class DB:
        container = plan["containers"]["postgres"]
        def sql(self, database, query): return "{}"
    monkeypatch.setattr(driver.aa, "Database", lambda _: DB())
    monkeypatch.setattr(driver.aa, "inspect_environment", lambda _: resources(plan, (4, 6)))
    monkeypatch.setattr(driver, "verify_databases", lambda *a, **k: prep["databases"])
    snapshot = {arm: dict(counters=dict(datid="1", datname=arm, stats_reset=None,
                    **dict.fromkeys(driver.DB_COUNTERS, 1))) for arm in driver.ARMS}
    monkeypatch.setattr(driver, "database_snapshot", lambda *a: copy.deepcopy(snapshot))
    clock = iter(range(1000))
    def host():
        at = next(clock)
        return dict(start_ns=at, end_ns=at, cpu_ticks={f"cpu{i}": [at] * 10 for i in range(8)},
                    reported_frequency_khz=dict.fromkeys(("0", "2", "4", "6"), 1000))
    monkeypatch.setattr(driver, "host_snapshot", host)
    if fault == "observation": monkeypatch.setattr(driver, "host_delta", lambda *a: (_ for _ in ()).throw(ValueError("lost observation")))
    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "inspect":
            if args[1] == DB.container: return json.dumps([dict(Id="pg-id")]).encode()
            return json.dumps([dict(Image=plan["images"]["c0"], HostConfig=dict(NetworkMode="container:pg-id",
                PortBindings={}, CpusetCpus="0,2", NanoCpus=2000000000, Memory=2147483648, MemorySwap=2147483648))]).encode()
        if args[0] == "wait":
            if fault == "exit": return b"1"
            entry = plan["arm_cell_order"][sum(call[0] == "wait" for call in calls) - 1]
            result = receipt(plan, entry)
            if fault == "cleanup": result["samples"][0].update(status="FAIL", error="cleanup: injected")
            driver.write_json(tmp_path / f'{entry["arm"]}-{entry["cell"]}-b{entry["block"]}.json', result)
            return b"0"
        return b""
    monkeypatch.setattr(driver, "docker", docker)
    if fault:
        with pytest.raises(ValueError): driver.execute(tmp_path)
        assert sum(call[0] == "start" for call in calls) == 1 and not (tmp_path / "result.json").exists()
    else:
        assert driver.execute(tmp_path)["status"] == "AA_CALIBRATION_PASS"
        assert sum(call[0] == "start" for call in calls) == 32
    before = len(calls)
    with pytest.raises(ValueError): driver.execute(tmp_path)
    assert len(calls) == before


@pytest.mark.parametrize("protocol", ["json", "sse"])
@pytest.mark.parametrize("fault", [None, "cleanup", "response", "context", "timeout"])
@pytest.mark.asyncio
async def test_actual_block_loop_with_memory_native_json_sse_stops_on_failure(packet, monkeypatch, protocol, fault):
    from app.core.observability import context_evidence as c1
    from app.core.domain.provider import ProviderInput
    from app.core.domain.types import ChatMessage
    from app.http.request_context import set_telemetry_identity, reset_telemetry_identity
    from experiments.production_graduation.gate_validation.capture import Capture
    from experiments.production_graduation.gate_validation.local_api import Lifecycle, LocalASGI
    from experiments.production_graduation.gate_validation.transports import Barriers, Reply, ScopedProvider, native_provider, with_purpose
    plan, _ = packet;entry = dict(arm="c0", cell="EN-" + protocol, block=0)
    lifecycle = Lifecycle();barriers = Barriers();capture = Capture();seen = []
    replies = dict(rewrite=Reply(""), primary=Reply("Controlled local response."))
    provider, close = native_provider("bedrock", capture, replies)
    scoped = ScopedProvider(provider, candidate=True, barriers=barriers)
    async def app(scope, receive, send):
        body = b""
        while True:
            message = await receive();body += message.get("body", b"")
            if not message.get("more_body", False): break
        data = json.loads(body);rid = dict(scope["headers"])[b"x-request-id"].decode();seen.append(rid)
        instance = str(uuid5(UUID(int=1444), rid));tokens = set_telemetry_identity(instance, rid);state = None
        try:
            with c1.request_evidence(instance, rid) as state:
                if fault == "timeout": await asyncio.Event().wait()
                pin = ProviderInput(request_id=UUID(rid), messages=(ChatMessage(role="user", content=data["message"]),))
                await with_purpose(scoped.generate, "rewrite")(pin)
                if protocol == "sse":
                    stream = await scoped.stream(pin)
                    async for _ in stream.chunks: pass
                    await stream.get_final_result()
                else: await scoped.generate(pin)
                terminal = dict(status="success", request_id=rid, conversation_id=data["conversation_id"])
                body = json.dumps(terminal).encode()
                if protocol == "sse": body = b"event: done\ndata: " + body + b"\n\n"
                if fault == "response": body = b"invalid"
                await send(dict(type="http.response.start", status=200, headers=[(b"content-type", b"text/event-stream" if protocol == "sse" else b"application/json")]))
                await send(dict(type="http.response.body", body=body, more_body=False))
        finally:
            reset_telemetry_identity(*tokens)
            if state is not None:
                if fault == "context": state.valid = False
                lifecycle.evidence_states.append(state)
    if fault == "cleanup":
        def fail(*a, **k): raise ValueError("injected cleanup failure")
        monkeypatch.setattr(worker, "release_validated_case", fail)
    if fault == "timeout": plan["request_deadline_s"] = .01
    try:
        rows = await worker.run_block(LocalASGI(app, lifecycle, barriers), lifecycle, scoped, capture, replies, plan, entry)
        if fault:
            assert len(rows) == len(seen) == 1 and rows[0]["status"] == "FAIL"
            assert lifecycle.requests and lifecycle.evidence_states
        else:
            assert len(rows) == len(seen) == 45 and len(set(seen)) == 45
            assert all(row["status"] == "PASS" for row in rows)
            assert [row["warmup"] for row in rows] == [True] * 20 + [False] * 25
            assert not lifecycle.tasks and not lifecycle.requests and not lifecycle.evidence_states
    finally:
        await scoped.quiesce();await close()


def test_actual_clock_callback_and_full_c1_flag_match_reviewed_worker():
    old = ast.parse((Path(driver.__file__).parent / "aa_calibration_worker.py").read_text())
    new = ast.parse(Path(worker.__file__).read_text())
    def function(tree, name):
        return ast.dump(next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and node.name == name), include_attributes=False)
    assert function(old, "sent") == function(new, "sent")
    assert function(old, "ingress") == function(new, "ingress")
    install = next(node for node in ast.walk(new) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id == "install")
    assert next(key.value.value for key in install.keywords if key.arg == "candidate") is True
