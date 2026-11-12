"""Offline authoring for a single explicitly synthetic lifecycle case.

This module returns review material only. It does not provision or install.
"""
import hashlib
import re

from experiments.production_graduation.gate_validation import dedicated_lifecycle as life

LANE = (".framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/"
        "controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/workload-lifecycle")
ADAPTERS = {name: LANE + "/no-benchmark-packet/synthetic_" + name + ".py"
            for name in ("controller", "worker", "packet", "bootstrap")}
CORE_SHA = "9d8547bd60265c883ae46a1987776f6138f7c1a62dacb2f07dba26d8fc488545"
LEGACY_SHA = "8064e669e1921475167fb70fb73d3746cb4c034fa02fe207c7ffa749346b2be2"
REVIEWED = {
    "core.py": "experiments/production_graduation/gate_validation/dedicated_lifecycle.py",
    "host.py": "experiments/production_graduation/gate_validation/dedicated_lifecycle_host.py",
    "environment.py": "experiments/production_graduation/gate_validation/dedicated_environment.py",
    "host_helper.py": LANE + "/host_helper.py",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def author_manifest(plan, controller, owned, boot_id, *, worker_id, sample):
    """Bind one supplied synthetic slot to already known identities.

    Callers must supply real, frozen identities at a later separately approved
    staging step. This function never invents IDs, hashes or authorization.
    """
    required = {"packet_kind", "run_id", "environment_binding", "lifecycle_binding",
                "synthetic_adapter_sha256", "harness_sha256", "support_files_sha256",
                "synthetic_worker_id", "synthetic_worker_key", "synthetic_slot",
                "synthetic_mounts", "synthetic_command", "synthetic_python", "synthetic_core_sha256"}
    life.require(set(plan) >= required and plan["packet_kind"] == "synthetic_no_benchmark_v1",
                 "Not an explicitly synthetic no-benchmark plan")
    life.require(re.fullmatch(r"[0-9]{12}", plan["run_id"]), "Missing frozen run identity")
    life.require(isinstance(plan["synthetic_adapter_sha256"], dict)
                 and set(plan["synthetic_adapter_sha256"]) == set(ADAPTERS)
                 and all(re.fullmatch(r"[0-9a-f]{64}", value)
                         for value in plan["synthetic_adapter_sha256"].values()),
                 "Synthetic adapter sources are not pinned")
    life.require(plan["synthetic_core_sha256"] == CORE_SHA, "Unreviewed core snapshot")
    life.require(isinstance(plan["harness_sha256"], dict)
                 and isinstance(plan["support_files_sha256"], dict)
                 and all(plan["harness_sha256"].get(path) == plan["synthetic_adapter_sha256"][name]
                         for name, path in ADAPTERS.items())
                 and not (set(plan["harness_sha256"]) & set(plan["support_files_sha256"])),
                 "Adapter source pins missing or shadowed")
    life.require(re.fullmatch(r"[0-9a-f]{64}", worker_id) and worker_id in owned
                 and owned[worker_id]["role"] == "api", "Missing frozen synthetic worker")
    life.require(isinstance(sample, str) and sample and len(sample) <= 128,
                 "Invalid fixed synthetic slot")
    name = owned[worker_id]["inspect"].get("Name", "").lstrip("/")
    prefix = "orq41-blocked-" + plan["run_id"] + "-"
    life.require(plan["synthetic_worker_id"] == worker_id and name.startswith(prefix)
                 and plan["synthetic_worker_key"] == name.removeprefix(prefix)
                 and plan["synthetic_worker_key"] == "synthetic-worker-b0",
                 "Synthetic worker ID/name/key are not bound")
    life.require(plan["synthetic_slot"] == sample, "Synthetic slot differs from plan")
    config = owned[worker_id]["inspect"].get("Config", {})
    life.require(plan["synthetic_python"] in ("/usr/bin/python3", "/usr/local/bin/python3"),
                 "Unapproved interpreter path; actual image validation remains required")
    command = [plan["synthetic_python"], "-I", "-B", "/orq41-synthetic/synthetic_worker.py",
               "/orq41-synthetic/plan.json", "/g6run"]
    life.require(plan["synthetic_command"] == command
                 and config.get("Entrypoint") == command[:3]
                 and config.get("Cmd") == command[3:]
                 and config.get("User") == str(controller["uid"]) + ":" + str(controller["gid"]),
                 "Worker is not pinned to the direct Python PID1 command")
    mounts = owned[worker_id]["inspect"].get("Mounts")
    life.require(isinstance(mounts, list) and plan["synthetic_mounts"] == mounts
                 and len(mounts) == 3
                 and sum(m.get("Destination") == "/g6run" and m.get("RW") is True for m in mounts) == 1
                 and sum(m.get("Destination") == "/orq41-synthetic" and m.get("RW") is False for m in mounts) == 1
                 and sum(m.get("Destination") == "/orq41-lifecycle" and m.get("RW") is False for m in mounts) == 1
                 and all(m.get("Destination") in ("/g6run", "/orq41-synthetic", "/orq41-lifecycle")
                         for m in mounts),
                 "Worker mounts must pin one writable receipt volume and read-only source/lifecycle volumes")
    life.require(all(sum(value["role"] == role for value in owned.values()) == 1
                     for role in ("api", "postgres", "redis", "collector")) and len(owned) == 4,
                 "Synthetic case requires exactly one worker and each owned service")
    manifest = dict(schema="orq41-dedicated-lifecycle-v1", run_id=plan["run_id"],
                    plan_sha256=life.digest(plan), boot_id=boot_id, limits=dict(life.LIMITS),
                    controller=controller, schedule=[dict(worker=worker_id, sample=sample)],
                    owned=owned, expected_binding=plan["environment_binding"])
    return life.validate_manifest(manifest)


def prepare_sealed_installation(plan, manifest, source_bytes, *, reviewed_sources, source_review):
    """Return exact file payloads/ordered sealing requirements, never install.

    No execution authorization is generated. The caller must protect this private
    review material: supplied inspect projections may contain local credentials.
    Live copying, no-overwrite checks and fsync still require a reviewed installer.
    """
    expected_manifest = author_manifest(plan, manifest["controller"], manifest["owned"],
        manifest["boot_id"], worker_id=plan["synthetic_worker_id"], sample=plan["synthetic_slot"])
    life.require(manifest == expected_manifest, "Plan/manifest mismatch")
    expected = plan["synthetic_adapter_sha256"]
    life.require(set(source_bytes) == set(expected), "Incomplete synthetic source set")
    actual = {name: sha(content) for name, content in source_bytes.items()}
    life.require(actual == expected, "Synthetic source hash mismatch")
    life.require(set(reviewed_sources) == set(REVIEWED) | {"admin.py"}, "Incomplete reviewed sources")
    review = life.decode(source_review)
    life.require(review.get("status") == "WORKLOAD_LIFECYCLE_SOURCE_REVIEW_PASS"
                 and review.get("new_blocker_high_medium_findings") == []
                 and all(review.get("technical_files_sha256", {}).get(path) == sha(reviewed_sources[name])
                         for name, path in REVIEWED.items())
                 and sha(reviewed_sources["admin.py"]) == LEGACY_SHA
                 and sha(reviewed_sources["core.py"]) == CORE_SHA, "Reviewed source identity differs")
    state = "/var/lib/orq41-cpuset/" + plan["run_id"]
    mount_sources = {m["Destination"]: m.get("Source") for m in plan["synthetic_mounts"]}
    life.require(mount_sources == {"/orq41-synthetic": state + "/synthetic",
                                  "/orq41-lifecycle": "/run/orq41-lifecycle/" + plan["run_id"],
                                  "/g6run": state + "/receipts"}, "Unsealed mount sources")
    plan_raw, manifest_raw = life.encode(plan), life.encode(manifest)
    deployment = dict(schema=1, files={name: sha(raw) for name, raw in reviewed_sources.items()},
                      plan_sha256=sha(plan_raw), manifest_sha256=sha(manifest_raw),
                      source_review_sha256=sha(source_review))
    # Keep the helper's exact five-file allowlist unchanged. Adapters are pinned
    # transitively through plan.json and its harness hashes; root-owned copies
    # must be verified against these payload hashes before mounting read-only.
    payloads = {**reviewed_sources, "source-review.json": source_review,
                "plan.json": plan_raw, "deployment.json": life.encode(deployment),
                "journal/manifest.json": manifest_raw, "journal/events.jsonl": b"",
                "journal/head.json": life.encode(dict(count=0, hash="0" * 64)),
                "journal/lock": b"", "synthetic/core.py": reviewed_sources["core.py"],
                "synthetic/plan.json": plan_raw,
                **{"synthetic/synthetic_" + name + ".py": raw for name, raw in source_bytes.items()}}
    files = {name: dict(content=raw.decode("utf-8"), sha256=sha(raw), uid=0,
                       gid=manifest["controller"]["gid"] if name.startswith("synthetic/") else 0,
                       mode="0640" if name.startswith("synthetic/") else "0600")
             for name, raw in payloads.items()}
    # Search-only on the root run directory lets the controller reach its owned
    # receipt directory, without exposing private root files or permitting writes.
    directories = [dict(path=".", uid=0, gid=0, mode="0711"),
                   dict(path="journal", uid=0, gid=0, mode="0700"),
                   dict(path="synthetic", uid=0, gid=manifest["controller"]["gid"], mode="0750"),
                   dict(path="receipts", uid=manifest["controller"]["uid"],
                        gid=manifest["controller"]["gid"], mode="0700")]
    return dict(status="PREPARATION_ONLY_NOT_EXECUTABLE", executable=False,
        writes_performed=0, state_path=state, source_sha256=actual, files=files,
        directories=directories, deployment_sha256=life.digest(deployment), authorization=None,
        installation_order=["verify reviewed sources and adapter review; require explicit staging approval",
            "verify root-owned nonsymlink ancestry; reject any existing run directory",
            "create directories exclusively in listed order; fsync each directory and its parent",
            "create files exclusively with O_NOFOLLOW; set owner/mode; fsync file and parent",
            "read back every byte/hash/owner/mode/link count and exact manifest mount sources",
            "verify private receipts directory is empty and worker UID/GID can write it",
            "obtain separate deployment-hash-bound execution authorization; never generate approval",
            "only then may separately reviewed supervisor-start commands be considered"],
        unresolved=["Independent adapter review and reviewed installer execution are required.",
                    "Actual container/image/interpreter identities and namespace access remain unvalidated.",
                    "Live staging/execution authorization absent; no commands executed or generated."],
        gate="Offline payloads only; no staging, root installation or live execution authorized")
