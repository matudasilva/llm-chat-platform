"""One fixed synthetic lifecycle slot; no application or provider imports."""
from pathlib import Path
import os
import json
import runpy
import sys

life = None


def _lifecycle():
    global life
    if life is None:
        bootstrap = Path(__file__).resolve().with_name("synthetic_bootstrap.py")
        life = runpy.run_path(str(bootstrap))["load_lifecycle"]()
    return life


def run_one(plan, worker_id, sample, client, receipt_directory, *, cleanup=lambda: None):
    """Complete one real lifecycle protocol slot and finalize after cleanup.

    The caller is responsible for launching this process as the container PID1
    and mounting the receipt directory. This function performs no networking
    except the existing Unix socket client exchanges.
    """
    core = _lifecycle()
    core.require(plan.get("packet_kind") == "synthetic_no_benchmark_v1",
                 "Worker plan is not explicitly synthetic")
    core.require(plan.get("synthetic_slot") == sample and plan.get("synthetic_worker_id") == worker_id
                 and plan.get("synthetic_worker_key") == "synthetic-worker-b0",
                 "Synthetic slot/worker identity drift")
    row = dict(kind="synthetic_no_benchmark_v1", status="PASS", worker=worker_id,
               sample=sample, application_requests=0, provider_calls=0, benchmark_samples=0)
    completed = False
    try:
        client.begin(sample)
        client.ingress()
        client.finish(row)
        completed = True
    finally:
        cleanup()
    core.require(completed, "Synthetic protocol slot did not complete")
    synthetic = dict(schema="orq41-synthetic-receipt-v1", kind="synthetic_no_benchmark_v1",
                     plan=core.digest(plan), worker=worker_id, sample=sample,
                     application_requests=0, provider_calls=0, benchmark_samples=0,
                     result=core.digest(row))
    finalizer = dict(plan=core.digest(plan), worker=worker_id, finalized=True)
    directory = Path(receipt_directory)
    core.create_file(directory / "synthetic-receipt.json", core.encode(synthetic))
    key = plan["synthetic_worker_key"]
    core.require(isinstance(key, str) and key, "Missing pinned synthetic worker key")
    core.create_file(directory / (key + "-finalized.json"), core.encode(finalizer))
    return synthetic


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        raise ValueError("Expected frozen plan and mounted receipt directory")
    plan_path = Path(argv[0])
    plan = json.loads(plan_path.read_bytes())
    if os.getpid() != 1:
        raise ValueError("Synthetic worker must run as container PID1")
    core = _lifecycle()
    core.require(plan.get("packet_kind") == "synthetic_no_benchmark_v1"
                 and plan.get("synthetic_worker_id") and plan.get("synthetic_slot"),
                 "Incomplete frozen synthetic plan")
    entry = dict(arm="synthetic", cell="worker", block=0)
    client = core.worker_client(plan, entry)
    core.require(client.worker == plan["synthetic_worker_id"]
                 and plan["synthetic_worker_key"] == "synthetic-worker-b0",
                 "Synthetic worker identity differs from lifecycle descriptor")
    run_one(plan, plan["synthetic_worker_id"], plan["synthetic_slot"], client, argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
