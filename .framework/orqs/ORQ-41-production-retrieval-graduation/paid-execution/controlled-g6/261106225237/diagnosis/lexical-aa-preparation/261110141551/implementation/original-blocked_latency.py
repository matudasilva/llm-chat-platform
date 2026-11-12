"""Approved balanced-block full-C1 A/A harness; never an executable formal G6 mode."""
import argparse
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time
from uuid import UUID, uuid4, uuid5

from . import aa_calibration as aa
from .aa_calibration_resources import resource_delta, worker_resources
from .controlled_latency import percentile
from .controlled_latency_controller import MODULES, docker, quote
from .g9_controller import ROOT, ORQ, P2_GUARD, env_for, private_write, sha_file


DESIGN = ORQ / "paid-execution/controlled-g6/261106225237/diagnosis/measurement-amendment"
RUNS = DESIGN.parent / "blocked-runs"
CONTRACT_SHA256 = "12f9032a4361170238bb710b5903c43160797c86d9b7be0c6b382d685fef670d"
SCHEMA = "orq41-blocked-aa-v1"
CATEGORIES = ("document", "history", "combined", "empty")
CELLS = ("EN-json", "EN-sse", "ES-json", "ES-sse")
ARMS = ("c0", "c1")
TABLES = ("alembic_version", "chunks", "conversations", "documents", "messages",
          "rag_request_metrics", "usage_events")
OWN_MODULES = ("blocked_latency.py", "blocked_latency_worker.py")
DB_COUNTERS = ("xact_commit", "xact_rollback", "blks_read", "blks_hit", "tup_returned",
               "tup_fetched", "tup_inserted", "tup_updated", "tup_deleted", "deadlocks")
LOCALE_SQL = ("SELECT json_build_object('encoding',pg_encoding_to_char(encoding),"
              "'collate',datcollate,'ctype',datctype,'provider',datlocprovider,"
              "'icu_locale',daticulocale) FROM pg_database WHERE datname=current_database();")
SETTINGS_SQL = ("SELECT json_object_agg(name,setting ORDER BY name) FROM pg_settings "
                "WHERE name LIKE 'autovacuum%' OR name='default_statistics_target' "
                "OR category LIKE 'Query Tuning%';")
PROJECTION_SQL = """SELECT json_build_object(
 'conversations',(SELECT coalesce(json_agg(x),'[]') FROM
   (SELECT id::text,tenant_id FROM conversations ORDER BY id) x),
 'messages',(SELECT coalesce(json_agg(x),'[]') FROM
   (SELECT id::text,conversation_id::text,tenant_id,role::text,content,sequence
    FROM messages ORDER BY sequence) x));"""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    private_write(path, (json.dumps(value, indent=2) + "\n").encode())


def load_contract():
    require(sha_file(DESIGN / "contract.json") == CONTRACT_SHA256, "Amendment identity changed")
    contract = json.loads((DESIGN / "contract.json").read_text())
    approval = json.loads((DESIGN / "implementation/authorization.json").read_text())
    require(approval.get("status") == "AMENDMENT_APPROVED_HARNESS_IMPLEMENTATION_AUTHORIZED"
            and approval.get("harness_implementation_authorized") is True
            and approval.get("contract_sha256") == CONTRACT_SHA256
            and approval.get("proposal_sha256") == sha_file(DESIGN / "proposal.md"),
            "Implementation approval does not bind this amendment")
    return contract


def build_samples(cases, namespace):
    """Pure deterministic slots/fixtures; no request admission or service operation."""
    contract = load_contract()
    namespace = UUID(str(namespace))
    require(len(cases) == len({case["case_id"] for case in cases}) == 40, "Case population changed")
    samples, fixtures, schedule = [], [], []
    for cell in CELLS:
        language, protocol = cell.split("-")
        selected = {cat: sorted([case for case in cases if case["language"] == language
                                and case["category"] == cat], key=lambda case: case["case_id"])
                    for cat in CATEGORIES}
        require({cat: [case["case_id"] for case in rows] for cat, rows in selected.items()}
                == contract["case_order_by_language_category"][language], "Business cases changed")
        seen = Counter()
        for block in range(4):
            warm = [selected[cat][index] for index in range(5) for cat in CATEGORIES]
            measured = []
            for slot in range(25):
                cat = CATEGORIES[(block + slot) % 4]
                measured.append(selected[cat][seen[cat] % 5])
                seen[cat] += 1
            for is_warm, rows in ((True, warm), (False, measured)):
                for ordinal, case in enumerate(rows):
                    key = f'{cell}/b{block}/{"warm" if is_warm else "measured"}/{ordinal}'
                    sample = dict(sample_id=key, language=language, protocol=protocol, block=block,
                                  ordinal=ordinal, warmup=is_warm, category=case["category"],
                                  case_id=case["case_id"], tenant_id=case["tenant_id"], message=case["message"],
                                  request_id=str(uuid5(namespace, "request/" + key)),
                                  conversation_id=str(uuid5(namespace, key)))
                    samples.append(sample)
                    fixtures.append(dict(sample=copy.deepcopy(sample), messages=copy.deepcopy(case["history"])))
            for label in contract["block_arm_order"][cell][block]:
                schedule.append(dict(arm="c0" if label == "A" else "c1", cell=cell, block=block))
    return samples, fixtures, schedule


def pinned_files():
    names = set((*MODULES, *aa.OWN_MODULES, *OWN_MODULES))
    harness = {str(Path("experiments/production_graduation/gate_validation") / name):
               sha_file(ROOT / "experiments/production_graduation/gate_validation" / name)
               for name in sorted(names)}
    support = [DESIGN / "contract.json", DESIGN / "proposal.md", DESIGN / "implementation/authorization.json",
               aa.OPTIMIZED_C1_PIN, aa.COLLECTOR_CONFIG, P2_GUARD / "sitecustomize.py",
               ORQ / "paid-execution/cases.json", ORQ / "corpus-snapshot/corpus-snapshot.json",
               ORQ / "environment/g123/execution-freeze/settings/inspect.py",
               *sorted((ROOT / "scripts/postgres-init").glob("*.sh"))]
    return harness, {str(path.relative_to(ROOT)): sha_file(path) for path in support}


def make_plan(namespace, run_id):
    contract = load_contract()
    require(re.fullmatch(r"[0-9]{12}", run_id) is not None, "Invalid run identity")
    for name, digest in contract["source_evidence_sha256"].items():
        require(sha_file(ORQ / name) == digest, "Prior evidence changed")
    for name, digest in contract["reviewed_helpers_sha256"].items():
        require(sha_file(ROOT / name) == digest, "Reviewed helper changed")
    cases = json.loads((ORQ / "paid-execution/cases.json").read_text())["cases"]
    samples, fixtures, schedule = build_samples(cases, namespace)
    previous = json.loads((DESIGN.parent / "aa-runs/261108131511/plan.json").read_text())
    harness, support = pinned_files()
    plan = dict(schema=SCHEMA, protocol_id="orq41-balanced-blocks-v1", not_a_gate=True,
                mode="aa_full_c1_both_arms", full_c1_both_arms=True, run_id=run_id,
                namespace=str(UUID(str(namespace))), amendment_sha256=CONTRACT_SHA256,
                n_per_cell_arm=100, measured_per_block_arm=25, warmups_per_block_arm=20,
                blocks_per_cell=4, repetitions=1, concurrency=1, sample_attempts=1,
                request_deadline_s=300, cleanup_bound_s=10, symmetric_limit_percent=5,
                boundary=contract["timing"]["boundary"], samples=samples, arm_cell_order=schedule,
                images=copy.deepcopy(contract["identities"]["images"]),
                postgres_image=contract["identities"]["postgres_image"],
                auxiliary_images=copy.deepcopy(contract["identities"]["auxiliary_images"]),
                resources=copy.deepcopy(contract["identities"]["resources"]),
                cpu_topology=copy.deepcopy(contract["identities"]["cpu_topology_reference"]),
                containers={key: f"orq41-blocked-{run_id}-{key}" for key in ("postgres", "redis", "collector")},
                databases={arm: f"orq41_blocked_{run_id}_{arm}" for arm in ARMS},
                source_schema_sha256=previous["source_schema_sha256"], database_locale=previous["database_locale"],
                harness_sha256=harness, support_files_sha256=support, config_sha256={},
                normalized_config_sha256=None, seed_probe=None,
                external_calls=0, paid_requests=0, official_g6_status="CONTROLLED_G6_FAIL")
    return plan, fixtures


def validate_plan(plan, fixtures, *, prepared=False):
    expected, expected_fixtures = make_plan(plan["namespace"], plan["run_id"])
    for key, value in expected.items():
        if key not in ("config_sha256", "normalized_config_sha256", "seed_probe"):
            require(canonical_hash(plan.get(key)) == canonical_hash(value), "Frozen plan drift: " + key)
    require(set(plan) == set(expected), "Unknown/missing plan fields")
    require(canonical_hash(fixtures) == canonical_hash(expected_fixtures), "Frozen fixture drift")
    if prepared:
        require(set(plan["config_sha256"]) == set(ARMS)
                and all(re.fullmatch(r"[0-9a-f]{64}", value or "")
                        for value in plan["config_sha256"].values()), "Incomplete configuration identity")
        require(re.fullmatch(r"[0-9a-f]{64}", plan["normalized_config_sha256"] or ""),
                "Missing normalized effective configuration")
        require(isinstance(plan["seed_probe"], dict) and plan["seed_probe"].get("seed") == "41"
                and type(plan["seed_probe"].get("string_hash")) is int
                and isinstance(plan["seed_probe"].get("python"), str)
                and plan["seed_probe"].get("hash_algorithm") == "siphash13"
                and plan["seed_probe"].get("hash_width") == 64,
                "Missing process seed proof")
    return expected_fixtures


def seed_probe():
    require(os.environ.get("PYTHONHASHSEED") == "41", "Process seed must be set before interpreter startup")
    return dict(seed="41", string_hash=hash("ORQ41 blocked A/A process seed probe"),
                python=sys.version, hash_algorithm=sys.hash_info.algorithm, hash_width=sys.hash_info.width)


def configuration_probe():
    """Settings-only image probe; no lifespan, DB connection or provider call."""
    from sqlalchemy.engine import make_url
    from .validate_g123 import check_p2, check_config, config_identity
    check_p2()
    from app.core.settings import settings
    check_config(settings)
    values = settings.model_dump(mode="json")
    for key, value in list(values.items()):
        if "url" in key and value:
            url = make_url(str(value))
            if key in ("database_url_override", "database_url_app", "database_url_ops"):
                url = url.set(database="CONTROLLED_PAIRED_DB")
            values[key] = url.render_as_string(hide_password=True)
        elif key.endswith(("password", "secret", "api_key", "access_token", "credential")) or key in (
                "aws_access_key_id", "aws_session_token"):
            values[key] = bool(value)
    return dict(config=config_identity(settings), normalized=canonical_hash(values),
                seed=seed_probe(), resources=worker_resources())


def host_snapshot(proc=Path("/proc/stat"), cpu_root=Path("/sys/devices/system/cpu")):
    start = time.monotonic_ns()
    rows = defaultdict(list)
    for line in proc.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] in {f"cpu{cpu}" for cpu in range(8)}:
            rows[fields[0]].append([int(value) for value in fields[1:]])
    require(set(rows) == {f"cpu{cpu}" for cpu in range(8)}
            and all(len(values) == 1 and len(values[0]) >= 8 and min(values[0]) >= 0
                    for values in rows.values()), "Incomplete/corrupt host CPU counters")
    frequencies = {str(cpu): int((cpu_root / f"cpu{cpu}/cpufreq/scaling_cur_freq").read_text())
                   for cpu in (0, 2, 4, 6)}
    require(all(value > 0 for value in frequencies.values()), "Missing host frequency samples")
    return dict(start_ns=start, end_ns=time.monotonic_ns(),
                cpu_ticks={key: values[0] for key, values in sorted(rows.items())},
                reported_frequency_khz=frequencies)


def host_delta(before, after):
    require(before["start_ns"] <= before["end_ns"] <= after["start_ns"] <= after["end_ns"],
            "Host clock ordering changed")
    a, b = before["cpu_ticks"], after["cpu_ticks"]
    require(a.keys() == b.keys() == {f"cpu{cpu}" for cpu in range(8)}, "Host CPU inventory changed")
    require(all(len(a[key]) == len(b[key]) >= 8
                and all(type(x) is int and type(y) is int and y >= x >= 0
                        for x, y in zip(a[key], b[key])) for key in a), "Host counters reset")
    for row in (before, after):
        require(set(row["reported_frequency_khz"]) == {"0", "2", "4", "6"}
                and all(type(v) is int and v > 0 for v in row["reported_frequency_khz"].values()),
                "Host frequency evidence missing")
    return {key: [y - x for x, y in zip(a[key], b[key])] for key in a}


def readonly(db, database, query):
    return db.sql(database, "BEGIN READ ONLY;\n" + query + "\nROLLBACK;")


def analyze_database(db, plan, database):
    require(db.container == plan["containers"]["postgres"]
            and database in plan["databases"].values()
            and re.fullmatch(r"orq41_blocked_[0-9]{12}_c[01]", database),
            "ANALYZE is limited to the fresh disposable databases")
    inventory = json.loads(readonly(db, database, "SELECT json_agg(tablename ORDER BY tablename) "
                                   "FROM pg_tables WHERE schemaname='public';"))
    require(inventory == list(TABLES), "Unreviewed ANALYZE table inventory")
    before = json.loads(readonly(db, database, SETTINGS_SQL))
    schema = db.schema_hash(database)
    statements = [f'ANALYZE "public"."{table}";' for table in TABLES]
    for statement in statements:
        db.sql(database, statement)
    after = json.loads(readonly(db, database, SETTINGS_SQL))
    require(before == after and db.schema_hash(database) == schema, "ANALYZE changed settings/schema")
    complete = json.loads(readonly(db, database, "SELECT json_object_agg(relname,last_analyze::text) "
                                  "FROM pg_stat_user_tables WHERE schemaname='public';"))
    require(set(complete) == set(TABLES) and all(complete.values()), "Incomplete ANALYZE proof")
    return dict(database=database, statements=statements, settings=after, completion=complete)


def database_snapshot(db, plan):
    result = {}
    for arm, database in plan["databases"].items():
        query = ("SELECT row_to_json(x) FROM (SELECT datid::text,datname,stats_reset::text,"
                 + ",".join(DB_COUNTERS) + " FROM pg_stat_database WHERE datname=current_database()) x;")
        counters = json.loads(readonly(db, database, query))
        maintenance = json.loads(readonly(db, database, "SELECT json_agg(x ORDER BY relname) FROM "
            "(SELECT relname,last_analyze::text,last_autoanalyze::text,last_vacuum::text,"
            "last_autovacuum::text FROM pg_stat_user_tables WHERE schemaname='public') x;"))
        require(counters["datname"] == database and all(type(counters[key]) is int
                and counters[key] >= 0 for key in DB_COUNTERS), "Invalid database counters")
        require([row["relname"] for row in maintenance] == list(TABLES), "Missing maintenance evidence")
        result[arm] = dict(counters=counters, maintenance=maintenance)
    return result


def database_delta(before, after):
    require(before.keys() == after.keys() == set(ARMS), "Database counter arms changed")
    result = {}
    for arm in ARMS:
        a, b = before[arm]["counters"], after[arm]["counters"]
        require(all(a[key] == b[key] for key in ("datid", "datname", "stats_reset")), "Database stats reset")
        require(all(type(a[key]) is int and type(b[key]) is int and b[key] >= a[key] >= 0
                    for key in DB_COUNTERS), "Database counters reset/missing")
        result[arm] = {key: b[key] - a[key] for key in DB_COUNTERS}
    return result


def verify_projection(data, fixtures, namespace, *, final):
    expected = {fixture["sample"]["conversation_id"]: fixture for fixture in fixtures}
    require(len(expected) == len(fixtures), "Duplicated expected conversation")
    require(len(data["conversations"]) == len(expected)
            and {row["id"]: row["tenant_id"] for row in data["conversations"]}
            == {cid: f["sample"]["tenant_id"] for cid, f in expected.items()}, "Conversation projection differs")
    groups, ids, sequences = defaultdict(list), set(), set()
    for row in data["messages"]:
        require(str(UUID(row["id"])) == row["id"] and row["id"] not in ids, "Duplicate/invalid message UUID")
        require(type(row["sequence"]) is int and row["sequence"] > 0
                and row["sequence"] not in sequences, "Duplicate/invalid message sequence")
        cid = row["conversation_id"]
        require(cid in expected and row["tenant_id"] == expected[cid]["sample"]["tenant_id"], "Foreign message")
        ids.add(row["id"])
        sequences.add(row["sequence"])
        groups[cid].append(row)
    normalized = []
    generated = set()
    for cid, fixture in expected.items():
        rows = sorted(groups[cid], key=lambda row: row["sequence"])
        history = fixture["messages"]
        require(len(rows) == len(history) + (2 if final else 0), "Missing/duplicate persisted exchange")
        require([{key: row[key] for key in ("role", "content")} for row in rows[:len(history)]] == history,
                "Seeded history changed")
        for index, row in enumerate(rows[:len(history)]):
            require(row["id"] == str(uuid5(UUID(namespace), fixture["sample"]["sample_id"] + "/history/" + str(index))),
                    "Seeded message identity changed")
            normalized.append(row)
        if final:
            require([{key: row[key] for key in ("role", "content")} for row in rows[len(history):]] == [
                dict(role="user", content=fixture["sample"]["message"]),
                dict(role="assistant", content="Controlled local response.")], "Final exchange content differs")
            for row in rows[len(history):]:
                generated.add(row["id"])
                normalized.append(dict(row, id="<generated:" + row["role"] + ">"))
    return dict(conversations=len(expected), messages=len(ids), generated_message_ids=len(generated),
                normalized_business_sha256=canonical_hash(dict(
                    conversations=sorted(data["conversations"], key=lambda row: row["id"]),
                    messages=sorted(normalized, key=lambda row: row["sequence"]))))


def verify_databases(db, plan, fixtures, *, final=False):
    meta = json.loads((ORQ / "corpus-snapshot/corpus-snapshot.json").read_text())["identity"]
    receipts = []
    for arm, database in plan["databases"].items():
        data = json.loads(readonly(db, database, PROJECTION_SQL))
        proof = verify_projection(data, fixtures, plan["namespace"], final=final)
        require(proof["conversations"] == 720 and proof["messages"] == (18720 if final else 17280),
                "Frozen database counts differ")
        require(json.loads(readonly(db, database, LOCALE_SQL)) == plan["database_locale"]
                and db.schema_hash(database) == plan["source_schema_sha256"], "Database locale/schema drift")
        corpus = readonly(db, database, "COPY (" + meta["snapshot_content_projection"].split("  (psql")[0] + ") TO STDOUT;")
        require(hashlib.sha256(corpus.encode()).hexdigest() == meta["snapshot_content_sha256"], "P3 changed")
        require(readonly(db, database, "SELECT (SELECT count(*) FROM documents),(SELECT count(*) FROM chunks);").strip()
                == "124|2146", "Corpus population changed")
        roles = readonly(db, database, "SELECT rolname,rolsuper,rolbypassrls FROM pg_roles "
                         "WHERE rolname IN ('rag_app','chat_ops') ORDER BY rolname;").strip().splitlines()
        require(roles == ["chat_ops|f|f", "rag_app|f|f"], "RLS role capability drift")
        rls = {}
        for tenant in sorted({f["sample"]["tenant_id"] for f in fixtures} | {"orq37-t23", "", "blocked-unknown"}):
            count = int(readonly(db, database, "SET LOCAL ROLE rag_app; SET LOCAL app.tenant_id="
                                 + quote(tenant) + "; SELECT count(*) FROM chunks;").strip())
            require(count == (2146 if tenant == "orq37-t23" else 0), "Tenant corpus isolation failed")
            rls[tenant] = count
        receipts.append(dict(arm=arm, database=database, **proof, rls=rls,
                             corpus_content_sha256=meta["snapshot_content_sha256"]))
    require(receipts[0]["normalized_business_sha256"] == receipts[1]["normalized_business_sha256"],
            "Paired persisted contents differ")
    return receipts


def validate_worker(worker, plan, entry):
    expected = [s for s in plan["samples"] if s["language"] + "-" + s["protocol"] == entry["cell"]
                and s["block"] == entry["block"]]
    require(worker["arm"] == entry["arm"] and worker["cell"] == entry["cell"]
            and worker["block"] == entry["block"] and worker["full_c1"] is True
            and worker["config_identity"] == plan["config_sha256"][entry["arm"]]
            and worker["seed_probe"] == plan["seed_probe"], "Worker identity/config/seed drift")
    require(worker["resources_before"]["topology"] == plan["cpu_topology"]
            and worker["cpu_stat_delta"] == resource_delta(worker["resources_before"], worker["resources_after"]),
            "Worker resource proof drift")
    for proof in (worker["resources_before"], worker["resources_after"]):
        require(proof["affinity"] == proof["effective_cpuset"] == [0, 2]
                and proof["cpu_max"] == "200000 100000", "Worker effective resources changed")
    require(len(worker["samples"]) == len(expected) == 45, "Incomplete worker block")
    instances, previous = set(), -1
    for row, sample in zip(worker["samples"], expected):
        require(all(type(row.get(key)) is type(value) and row[key] == value for key, value in sample.items()),
                "Worker sample/phase/order drift")
        require(row["status"] == "PASS" and row["error"] is None, "Request/cleanup failed")
        instance = row["accounting_instance_id"]
        require(str(UUID(instance)) == instance and instance not in instances, "Missing/duplicate C1 instance")
        instances.add(instance)
        require(all(type(row[key]) is int for key in ("start_ns", "primary_dispatch_ns", "preparation_ns"))
                and row["start_ns"] > previous and row["primary_dispatch_ns"] >= row["start_ns"]
                and row["preparation_ns"] == row["primary_dispatch_ns"] - row["start_ns"], "Ambiguous timing")
        previous = row["primary_dispatch_ns"]
        require([d["purpose"] for d in row["dispatches"]] == ["rewrite", "primary"]
                and all(re.fullmatch(r"[0-9a-f]{64}", d["sha256"]) for d in row["dispatches"]), "Dispatch proof missing")
    require(worker["provider_calls"] == worker["external_calls"] == 0, "External operation recorded")


def summarize(arms, plan):
    require(set(arms) == set(ARMS), "Missing A/A arm")
    indexed, instances = {}, set()
    for arm in ARMS:
        require(len(arms[arm]) == 720, "Incomplete arm population")
        indexed[arm] = {row["sample_id"]: row for row in arms[arm]}
        require(len(indexed[arm]) == 720, "Duplicate admission")
        for sample in plan["samples"]:
            row = indexed[arm][sample["sample_id"]]
            require(all(type(row[key]) is type(value) and row[key] == value for key, value in sample.items())
                    and row["status"] == "PASS" and row["error"] is None, "Failed or drifted row")
            uid = row["accounting_instance_id"]
            require(str(UUID(uid)) == uid and uid not in instances, "Reused C1 context")
            instances.add(uid)
            require(type(row["preparation_ns"]) is int and row["preparation_ns"] >= 0, "Invalid duration")
            require(type(row["start_ns"]) is int and type(row["primary_dispatch_ns"]) is int
                    and row["preparation_ns"] == row["primary_dispatch_ns"] - row["start_ns"], "Timing contradicts clocks")
            require([d["purpose"] for d in row["dispatches"]] == ["rewrite", "primary"]
                    and all(re.fullmatch(r"[0-9a-f]{64}", d["sha256"]) for d in row["dispatches"]),
                    "Invalid dispatch projection")
    for key, a in indexed["c0"].items():
        require(a["dispatches"] == indexed["c1"][key]["dispatches"], "Native payload/call parity failed")
    cells, blocks = [], []
    for cell in CELLS:
        language, protocol = cell.split("-")
        values = {arm: [row["preparation_ns"] for row in arms[arm]
                       if not row["warmup"] and row["language"] == language and row["protocol"] == protocol]
                  for arm in ARMS}
        require(all(len(v) == 100 for v in values.values()), "Wrong measured denominator")
        a, b = (percentile(values[arm], .95) for arm in ARMS)
        metrics = {f"{arm}_{name}_ns": percentile(v, q) for arm, v in values.items()
                   for name, q in (("p50", .5), ("p95", .95), ("p99", .99), ("max", 1))}
        cells.append(dict(cell=cell, n_per_arm=100, **metrics,
                          status="PASS" if a * 100 <= b * 105 and b * 100 <= a * 105 else "FAIL"))
        for block in range(4):
            first = next(entry["arm"] for entry in plan["arm_cell_order"]
                         if entry["cell"] == cell and entry["block"] == block)
            for arm in ARMS:
                durations = [row["preparation_ns"] for row in arms[arm] if not row["warmup"]
                             and row["language"] == language and row["protocol"] == protocol
                             and row["block"] == block]
                require(len(durations) == 25, "Missing measured block")
                blocks.append(dict(cell=cell, block=block, arm=arm, first=first == arm,
                                   n=25, p50_ns=percentile(durations, .5),
                                   p95_ns=percentile(durations, .95), max_ns=max(durations)))
    return dict(status="AA_CALIBRATION_PASS" if all(c["status"] == "PASS" for c in cells) else "AA_CALIBRATION_FAIL",
                cells=cells, descriptive_blocks=blocks, not_a_gate=True, request_count=1440, measured=800, warmups=640,
                accounting_instances=len(instances), external_calls=0, paid_requests=0,
                spend_usd="0", official_g6_status="CONTROLLED_G6_FAIL", symmetric_limit_percent=5)


def preflight(out):
    """All local authorizations, hashes and replay guards precede Docker/SQL."""
    out = Path(out)
    require(not (out / "execution-started.json").exists()
            and not (out / "execution-started.json").is_symlink(), "Never resume/re-admit a started run")
    plan = json.loads((out / "plan.json").read_text())
    fixtures = json.loads((out / "fixtures.json").read_text())
    validate_plan(plan, fixtures, prepared=True)
    digest = sha_file(out / "plan.json")
    review = json.loads((out / "independent-review.json").read_text())
    require(review.get("status") == "BLOCKED_AA_HARNESS_REVIEW_PASS"
            and review.get("plan_sha256") == digest
            and review.get("fixtures_sha256") == sha_file(out / "fixtures.json")
            and review.get("preparation_sha256") == sha_file(out / "preparation.json"),
            "Exact packet lacks independent review")
    authorization = json.loads((out / "execution-authorization.json").read_text())
    require(authorization.get("status") == "OPERATOR_AUTHORIZED_BLOCKED_AA_EXECUTION"
            and authorization.get("plan_sha256") == digest, "Local A/A execution not authorized")
    prep = json.loads((out / "preparation.json").read_text())
    require(prep.get("status") == "BLOCKED_AA_PREPARED_NOT_EXECUTED"
            and prep.get("plan_sha256") == digest and prep.get("fixtures_sha256") == sha_file(out / "fixtures.json"),
            "Preparation identity incomplete")
    require(len(prep["analyses"]) == 2
            and {row["database"] for row in prep["analyses"]} == set(plan["databases"].values())
            and all(row["statements"] == [f'ANALYZE "public"."{table}";' for table in TABLES]
                    and set(row["completion"]) == set(TABLES) and all(row["completion"].values())
                    for row in prep["analyses"]), "Incomplete ANALYZE preparation")
    require(len(prep["config_probes"]) == 2 and prep["api_requests"] == 0
            and all(row["normalized"] == plan["normalized_config_sha256"]
                    and row["seed"] == plan["seed_probe"] for row in prep["config_probes"])
            and [row["config"] for row in prep["config_probes"]]
                == [plan["config_sha256"][arm] for arm in ARMS], "Configuration preparation mismatch")
    for path, expected in {**plan["harness_sha256"], **plan["support_files_sha256"]}.items():
        require(sha_file(ROOT / path) == expected, "Source/support identity changed")
    return plan, fixtures, prep


def worker_environment(plan, private_passwords, entry=None, *, arm="c0"):
    arm = entry["arm"] if entry else arm
    require(arm in ARMS, "Unknown worker arm")
    values = env_for(arm, "C1", plan["databases"][arm], private_passwords)
    values.update(PYTHONHASHSEED="41", PYTHONPATH="/p2_netguard:/app", PATH="/usr/local/bin:/usr/bin:/bin")
    if entry:
        values.update(G6_RUN_DIR="/g6run", G6_ARM=arm, G6_CELL=entry["cell"],
                      G6_BLOCK=str(entry["block"]), P2_NET_AUDIT_LOG="/g6run/network-audit.log")
    return values


def check_local_services(plan, env):
    """Preparation-only loopback readiness; never instantiate the application."""
    code = """import socket,time
from experiments.production_graduation.gate_validation.validate_g123 import check_p2
check_p2()
for port in (5432,6379,4318):
 deadline=time.monotonic()+10
 while True:
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.5):pass
   break
  except OSError:
   if time.monotonic()>=deadline:raise RuntimeError('Local readiness timeout')
   time.sleep(.1)
print('BLOCKED_AA_LOCAL_SERVICES_READY')
"""
    raw = docker("run", "--rm", "--pull=never", "--network", "container:" + plan["containers"]["postgres"],
                 "--env-file", str(env), "--cpus=2", "--cpuset-cpus", "0,2", "--memory=2147483648",
                 "--memory-swap=2147483648", "--mount",
                 f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
                 "--mount", f"type=bind,src={P2_GUARD},dst=/p2_netguard,readonly",
                 "--entrypoint", "/usr/local/bin/python", plan["images"]["c0"], "-c", code)
    require(raw.strip() == b"BLOCKED_AA_LOCAL_SERVICES_READY", "Local service readiness missing")


def prepare(authorization_path):
    load_contract()
    approval = json.loads(Path(authorization_path).read_text())
    require(approval.get("status") == "OPERATOR_AUTHORIZED_BLOCKED_AA_PREPARATION"
            and approval.get("amendment_sha256") == CONTRACT_SHA256, "Environment preparation not authorized")
    from .validate_g123 import check_p2
    check_p2()
    require(not sys.flags.optimize, "Optimized interpreter disables reviewed helper checks")
    run_id = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    plan, fixtures = make_plan(uuid4(), run_id)
    require(set((0, 2, 4, 6)) <= os.sched_getaffinity(0), "Required CPUs unavailable")
    require(aa.topology() == plan["cpu_topology"], "Host topology/governor changed")
    host_snapshot()
    source = aa.Database(aa.SOURCE_PG)
    require(source.schema_hash("orq41") == plan["source_schema_sha256"]
            and json.loads(readonly(source, "orq41", LOCALE_SQL)) == plan["database_locale"], "Source schema/locale drift")
    source_settings = json.loads(readonly(source, "orq41", SETTINGS_SQL))
    dump = ORQ / "corpus-snapshot/orq37-t23-corpus.pgdump"
    meta = json.loads((dump.parent / "corpus-snapshot.json").read_text())
    require(sha_file(dump) == meta["artifact"]["sha256"], "P3 artifact changed")
    for image in {plan["postgres_image"], *plan["images"].values(), *plan["auxiliary_images"].values()}:
        require(json.loads(docker("image", "inspect", image))[0]["Id"] == image, "Image unavailable")
    out = RUNS / run_id
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    private = Path(tempfile.mkdtemp(prefix="orq41-blocked-" + run_id + "-"))
    private.chmod(0o700)
    passwords = {key: secrets.token_hex(24) for key in ("POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD",
        "POSTGRES_EVALUATION_PASSWORD", "POSTGRES_OPS_PASSWORD", "POSTGRES_OPS_RETENTION_PASSWORD")}
    write_json(private / "local-credentials.json", passwords)
    write_json(out / "allocation.json", dict(containers=plan["containers"], private_state=str(private),
                                             api_requests=0, preparation_authorization_sha256=sha_file(Path(authorization_path))))
    aa.provision(plan, private, passwords)
    aa.inspect_environment(plan)
    db = aa.Database(plan["containers"]["postgres"])
    ddl = source.schema("orq41")
    analyses = []
    for arm, database in plan["databases"].items():
        require(not db.sql("postgres", "SELECT datname FROM pg_database WHERE datname=" + quote(database)).strip(),
                "Database already exists")
        locale = plan["database_locale"]
        db.sql("postgres", "CREATE DATABASE " + database + " OWNER orq41owner TEMPLATE template0 ENCODING "
               + quote(locale["encoding"]) + " LC_COLLATE " + quote(locale["collate"])
               + " LC_CTYPE " + quote(locale["ctype"]) + " LOCALE_PROVIDER libc")
        docker("exec", "-i", db.container, "psql", "-X", "-v", "ON_ERROR_STOP=1", "--single-transaction",
               "-U", "orq41owner", "-d", database, data=ddl)
        db.sql(database, "INSERT INTO alembic_version VALUES ('e4b7f21c9a06')")
        docker("exec", "-i", db.container, "pg_restore", "-U", "orq41owner", "-d", database,
               "--data-only", "--single-transaction", data=dump.read_bytes())
        statements = ["BEGIN;"]
        for fixture in fixtures:
            sample = fixture["sample"]
            cid, tenant = sample["conversation_id"], sample["tenant_id"]
            statements.append("INSERT INTO conversations(id,tenant_id) VALUES (" + quote(cid)
                              + "::uuid," + quote(tenant) + ");")
            for index, message in enumerate(fixture["messages"]):
                mid = str(uuid5(UUID(plan["namespace"]), sample["sample_id"] + "/history/" + str(index)))
                statements.append("INSERT INTO messages(id,conversation_id,tenant_id,role,content) VALUES ("
                                  + quote(mid) + "::uuid," + quote(cid) + "::uuid," + quote(tenant)
                                  + "," + quote(message["role"]) + "," + quote(message["content"]) + ");")
        db.sql(database, "\n".join([*statements, "COMMIT;"]))
        analysis = analyze_database(db, plan, database)
        require(analysis["settings"] == source_settings, "Clone planner/autovacuum settings differ")
        analyses.append(analysis)
    data_proof = verify_databases(db, plan, fixtures)
    probes = []
    for arm in ARMS:
        env = private / (arm + ".env")
        values = worker_environment(plan, passwords, arm=arm)
        private_write(env, "".join(f"{key}={value}\n" for key, value in sorted(values.items())).encode())
        code = ("import json;from experiments.production_graduation.gate_validation.blocked_latency "
                "import configuration_probe;print(json.dumps(configuration_probe()))")
        raw = docker("run", "--rm", "--pull=never", "--network", "none", "--env-file", str(env),
                     "--cpus=2", "--cpuset-cpus", "0,2", "--memory=2147483648", "--memory-swap=2147483648",
                     "--mount", f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
                     "--mount", f"type=bind,src={P2_GUARD},dst=/p2_netguard,readonly", "--entrypoint",
                     "/usr/local/bin/python", plan["images"][arm], "-c", code)
        probe = json.loads(raw)
        require(probe["resources"]["topology"] == plan["cpu_topology"], "Probe topology drift")
        plan["config_sha256"][arm] = probe["config"]
        probes.append(probe)
    require(probes[0]["seed"] == probes[1]["seed"] and probes[0]["normalized"] == probes[1]["normalized"],
            "Process seed/interpreter or effective settings differ")
    plan["seed_probe"] = probes[0]["seed"]
    plan["normalized_config_sha256"] = probes[0]["normalized"]
    validate_plan(plan, fixtures, prepared=True)
    check_local_services(plan, private / "c0.env")
    write_json(out / "plan.json", plan)
    write_json(out / "fixtures.json", fixtures)
    write_json(out / "preparation.json", dict(status="BLOCKED_AA_PREPARED_NOT_EXECUTED",
        plan_sha256=sha_file(out / "plan.json"), fixtures_sha256=sha_file(out / "fixtures.json"),
        private_state=str(private), analyses=analyses, databases=data_proof, config_probes=probes, api_requests=0))
    print(str(out.relative_to(ROOT)))
    return out


def execute(out):
    out = Path(out).resolve()
    plan, fixtures, prep = preflight(out)
    from .validate_g123 import check_p2
    check_p2()
    require(not sys.flags.optimize, "Optimized interpreter not allowed")
    aa.inspect_environment(plan)
    db = aa.Database(plan["containers"]["postgres"])
    require(verify_databases(db, plan, fixtures) == prep["databases"], "Prepared database drift")
    for analysis in prep["analyses"]:
        require(json.loads(readonly(db, analysis["database"], SETTINGS_SQL)) == analysis["settings"], "DB settings drift")
    private = Path(prep["private_state"])
    passwords = json.loads((private / "local-credentials.json").read_text())
    write_json(out / "execution-started.json", dict(plan_sha256=sha_file(out / "plan.json"),
                                                    started=datetime.now(timezone.utc).isoformat()))
    arms, observations, workers = {arm: [] for arm in ARMS}, [], {}
    last_primary = -1
    for entry in plan["arm_cell_order"]:
        for file, digest in {**plan["harness_sha256"], **plan["support_files_sha256"]}.items():
            require(sha_file(ROOT / file) == digest, "Source drift before next admission")
        arm = entry["arm"]
        key = f'{arm}-{entry["cell"]}-b{entry["block"]}'
        name = "orq41-blocked-" + plan["run_id"] + "-" + key.lower()
        output = out / (key + ".json")
        require(not output.exists() and not (out / (key + "-started.json")).exists(), "Never resend admitted block")
        env = private / (key + ".env")
        values = worker_environment(plan, passwords, entry)
        private_write(env, "".join(f"{key}={value}\n" for key, value in sorted(values.items())).encode())
        pg_before = aa.inspect_environment(plan)
        db_before = database_snapshot(db, plan)
        docker("create", "--pull=never", "--name", name, "--network", "container:" + db.container,
               "--user=1000:1000", "--cpus=2", "--cpuset-cpus", "0,2", "--memory=2147483648",
               "--memory-swap=2147483648", "--env-file", str(env),
               "--mount", f"type=bind,src={out},dst=/g6run",
               "--mount", f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
               "--mount", f"type=bind,src={P2_GUARD},dst=/p2_netguard,readonly",
               "--entrypoint", "/usr/local/bin/python", plan["images"][arm],
               "-m", "experiments.production_graduation.gate_validation.blocked_latency_worker")
        info = json.loads(docker("inspect", name))[0]
        limits = info["HostConfig"]
        require(info["Image"] == plan["images"][arm]
                and limits["NetworkMode"] == "container:" + json.loads(docker("inspect", db.container))[0]["Id"]
                and not limits.get("PortBindings") and limits["CpusetCpus"] == "0,2"
                and limits["NanoCpus"] == 2_000_000_000
                and limits["Memory"] == limits["MemorySwap"] == 2_147_483_648, "Worker isolation drift")
        host_before = host_snapshot()
        docker("start", name)
        code = docker("wait", name).strip()
        host_after = host_snapshot()
        private_write(out / (key + ".log"), docker("logs", name))
        require(code == b"0", "Worker failed; stop admission and never automatically resend")
        worker = json.loads(output.read_text())
        validate_worker(worker, plan, entry)
        require(worker["samples"][0]["start_ns"] > last_primary, "Overlapping/reordered workers")
        last_primary = worker["samples"][-1]["primary_dispatch_ns"]
        after = aa.inspect_environment(plan)
        db_after = database_snapshot(db, plan)
        observation = dict(entry=entry, host_before=host_before, host_after=host_after,
            host_delta=host_delta(host_before, host_after), pg_before=pg_before, pg_after=after,
            pg_delta=resource_delta(pg_before, after), db_before=db_before, db_after=db_after,
            db_delta=database_delta(db_before, db_after))
        write_json(out / (key + "-observations.json"), observation)
        observations.append(observation)
        arms[arm].extend(worker["samples"])
        workers[output.name] = sha_file(output)
    audit = out / "network-audit.log"
    require(not audit.exists() or not audit.read_bytes(), "P2 network attempt recorded")
    final = verify_databases(db, plan, fixtures, final=True)
    write_json(out / "database-final-verification.json", dict(databases=final, database_writes=0))
    result = summarize(arms, plan)
    result.update(plan_sha256=sha_file(out / "plan.json"), worker_receipts=workers,
                  observations=observations, final_database_receipt_sha256=sha_file(out / "database-final-verification.json"))
    write_json(out / "result.json", result)
    print(result["status"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare-authorization", type=Path)
    action.add_argument("--execute", type=Path)
    arguments = parser.parse_args()
    if arguments.execute:
        execute(arguments.execute)
    else:
        prepare(arguments.prepare_authorization)
