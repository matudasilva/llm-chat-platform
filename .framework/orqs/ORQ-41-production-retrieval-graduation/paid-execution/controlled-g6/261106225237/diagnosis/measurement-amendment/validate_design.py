"""Validate this design's arithmetic and identities; no application/SQL/Docker I/O."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import socket


ROOT = Path.cwd()
ORQ = ROOT / ".framework/orqs/ORQ-41-production-retrieval-graduation"
DESIGN = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    contract = json.loads((DESIGN / "contract.json").read_text())
    checks = []
    assert contract["executable"] is False
    assert contract["authorization"]["design_preparation"] is True
    assert not any(value for key, value in contract["authorization"].items()
                   if key != "design_preparation")
    checks.append("design_only_authorization")

    assert os.environ["APP_SETTINGS_ENV_FILE"] == ""
    assert not any(os.environ.get(key) for key in (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "OPENAI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"))
    routes = [line for line in Path("/proc/net/route").read_text().splitlines()
              if line.strip()]
    assert not routes or (len(routes) == 1 and routes[0].split()[0] == "Iface")
    assert [name for _, name in socket.if_nameindex()] == ["lo"]
    checks.append("credential_scrubbed_loopback_only_network_namespace")

    for file, digest in contract["source_evidence_sha256"].items():
        assert sha(ORQ / file) == digest, file
    for file, digest in contract["reviewed_helpers_sha256"].items():
        assert sha(ROOT / file) == digest, file
    checks.append("source_evidence_and_reviewed_helpers_unchanged")

    cases = json.loads((ORQ / "paid-execution/cases.json").read_text())["cases"]
    assert len(cases) == len({case["case_id"] for case in cases}) == 40
    prior = DESIGN.parent / "aa-runs/261108131511"
    prior_plan = json.loads((prior / "plan.json").read_text())
    prior_fixtures = json.loads((prior / "fixtures.json").read_text())
    categories = contract["categories"]
    details = []
    total_warmups = total_measured = total_history = 0
    for cell in contract["cell_order"]:
        language, protocol = cell.split("-")
        ordered = {
            category: sorted([case for case in cases
                              if case["language"] == language
                              and case["category"] == category],
                             key=lambda case: case["case_id"])
            for category in categories}
        assert all(len(rows) == 5 for rows in ordered.values())
        assert {category: [case["case_id"] for case in rows]
                for category, rows in ordered.items()} == (
                    contract["case_order_by_language_category"][language])
        occurrences = Counter()
        first = Counter()
        first_categories = Counter()
        measured, warmups, blocks = [], [], []
        for block in range(4):
            order = contract["block_arm_order"][cell][block]
            assert sorted(order) == ["A", "B"]
            first[order[0]] += 1
            block_warmups = [ordered[category][index] for index in range(5)
                             for category in categories]
            assert len({case["case_id"] for case in block_warmups}) == 20
            warmups.extend(block_warmups)
            block_measured = []
            for slot in range(25):
                category = categories[(block + slot) % 4]
                block_measured.append(ordered[category][occurrences[category] % 5])
                occurrences[category] += 1
                first_categories[order[0], category] += 1
            measured.extend(block_measured)
            blocks.append(dict(block=block, arm_order=order, measured=25,
                               warmups_per_arm=20, category_measured=Counter(
                                   case["category"] for case in block_measured)))
        assert first == {"A": 2, "B": 2}
        assert all(abs(first_categories["A", cat] - first_categories["B", cat]) <= 1
                   for cat in categories)
        assert Counter(case["category"] for case in measured) == dict.fromkeys(categories, 25)
        assert Counter(case["case_id"] for case in measured) == dict.fromkeys(
            [case["case_id"] for rows in ordered.values() for case in rows], 5)
        original_cases = []
        for fixture in prior_fixtures:
            sample = fixture["sample"]
            if sample["warmup"] or sample["language"] != language or sample["protocol"] != protocol:
                continue
            matches = [case for case in cases
                       if all(case[key] == sample[key] for key in (
                           "language", "category", "tenant_id", "message"))
                       and case["history"] == fixture["messages"]]
            assert len(matches) == 1
            original_cases.append(matches[0]["case_id"])
        assert Counter(original_cases) == Counter(case["case_id"] for case in measured)
        history = sum(len(case["history"]) for case in measured + warmups)
        total_history += history
        total_measured += len(measured)
        total_warmups += len(warmups)
        details.append(dict(cell=cell, measured_per_arm=len(measured),
                            warmups_per_arm=len(warmups),
                            seeded_history_per_arm=history, blocks=blocks))
    checks.extend(["same_measured_business_multiset_in_all_four_cells",
                   "all20business_cases_warmed_in_every_worker",
                   "four_balanced_blocks_per_cell_category_first_order_difference_at_most_one"])

    counts = contract["counts"]
    assert total_measured * 2 == counts["measured"] == 800
    assert total_warmups * 2 == counts["warmups"] == 640
    assert (total_warmups + total_measured) * 2 == counts["requests"] == 1440
    assert counts["workers"] == 32 and counts["extra_requests_vs_previous"] == 1440 - 840
    assert total_history == 17280
    assert contract["fixture_projection_per_arm"] == dict(
        prepared_conversations=720, prepared_history_messages=17280,
        final_conversations=720, final_messages=18720, new_messages=1440)
    checks.extend(["exact1440requests_800measured_640warmups_32workers",
                   "exact_prepared_final_database_projections_from_frozen_histories"])

    assert contract["timing"]["boundary"] == prior_plan["boundary"]
    assert contract["timing"]["p95_index_zero_based"] == 94
    assert contract["acceptance"]["aa_rule"] == "a*100<=b*105 AND b*100<=a*105"
    assert contract["acceptance"]["formal_g6_rule_unchanged"] == (
        "candidate_p95*100<=baseline_p95*105")
    assert contract["repetitions"] == contract["concurrency"] == contract["attempts_per_identity"] == 1
    assert contract["request_deadline_s"] == 300 and contract["cleanup_bound_s"] == 10
    for key in ("images", "postgres_image", "auxiliary_images"):
        assert contract["identities"][key] == prior_plan[key]
    for key, value in prior_plan["resources"].items():
        assert contract["identities"]["resources"][key] == value
    assert contract["process"]["PYTHONHASHSEED"] == "41"
    checks.extend(["unchanged_boundary_N100_5percent_R1_C1_deadlines",
                   "unchanged_images_cpu_memory_and_one_prospective_process_seed"])

    schema = DESIGN.parent / "aa-runs/261107141146/setup-failure/source-schema.sql"
    tables = re.findall(r"^CREATE TABLE public\.([a-z_]+) \(", schema.read_text(), re.M)
    postgres = contract["postgres_preparation"]
    assert tables == postgres["ordinary_public_tables"]
    assert postgres["analyze_once_per_database"] == [
        f'ANALYZE "public"."{table}";' for table in tables]
    checks.append("exact7table_ANALYZE_design_allowlist_noSQL_execution")
    proc = Path("/proc/stat").read_text()
    assert all(re.search(rf"^cpu{cpu}\s", proc, re.M) for cpu in range(8))
    assert all(int(Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq").read_text()) > 0
               for cpu in (0, 2, 4, 6))
    checks.append("readonly_host_metric_availability_no_benchmark_or_sampler")

    files = [file for base in ("app", "experiments", "tests")
             for file in (ROOT / base).rglob("*") if file.is_file()
             and "__pycache__" not in file.parts and file.suffix != ".pyc"]
    if (ROOT / ".env").is_file():
        files.append(ROOT / ".env")
    inventory = {str(file.relative_to(ROOT)): sha(file) for file in sorted(files)}
    inventory_hash = hashlib.sha256(json.dumps(
        inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert inventory_hash == contract["protected_sources_during_design"]["inventory_sha256"]
    assert len(inventory) == contract["protected_sources_during_design"]["count"] == 497
    assert all(not (ROOT / file).exists() for file in contract["future_new_files"])
    checks.extend(["all497protected_source_test_globalenv_files_unchanged",
                   "future_harness_files_not_implemented"])
    audit = Path(os.environ["P2_NET_AUDIT_LOG"])
    assert not audit.exists() or not audit.read_bytes()
    checks.append("empty_network_attempt_audit")

    receipt = dict(
        status="MEASUREMENT_AMENDMENT_DESIGN_INTERNAL_CONSISTENCY_PASS",
        independent_review=False, implementation_validated=False,
        execution_authorized=False, checks=checks, checks_passed=len(checks),
        contract_sha256=sha(DESIGN / "contract.json"),
        proposal_sha256=sha(DESIGN / "proposal.md"),
        validator_sha256=sha(Path(__file__)), cell_projections=details,
        protected_files_unchanged=497, source_inventory_sha256=inventory_hash,
        docker_operations=0, postgres_operations=0, application_requests=0,
        external_provider_calls=0, network_attempts=0, spend_usd="0",
        official_g6_status="CONTROLLED_G6_FAIL", paid_admission="BLOCKED_CONTROLLED_G6_FAIL")
    output = DESIGN / "validation.json"
    if output.exists():
        assert json.loads(output.read_text()) == receipt, "Do not overwrite different evidence"
    else:
        output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: receipt[key] for key in (
        "status", "checks_passed", "protected_files_unchanged",
        "application_requests", "postgres_operations", "external_provider_calls", "spend_usd")}, indent=2))


if __name__ == "__main__":
    main()
