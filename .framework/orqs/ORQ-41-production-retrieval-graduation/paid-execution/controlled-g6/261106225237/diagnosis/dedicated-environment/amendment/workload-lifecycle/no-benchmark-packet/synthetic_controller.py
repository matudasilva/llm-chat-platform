"""Controller gate for one synthetic worker; no provisioning or retries."""
from pathlib import Path
import runpy

life = None


def _lifecycle():
    global life
    if life is None:
        bootstrap = Path(__file__).resolve().with_name("synthetic_bootstrap.py")
        life = runpy.run_path(str(bootstrap))["load_lifecycle"]()
    return life


def finish_after_worker_exit(client, worker_id, inspect, receipt_directory, *, sleep=None):
    """Send finish once, after Docker reports the actual worker exit and receipts."""
    plan = client.plan
    core = _lifecycle()
    sleep = sleep or core.time.sleep
    core.require(plan.get("packet_kind") == "synthetic_no_benchmark_v1",
                 "Controller plan is not explicitly synthetic")
    core.require(plan.get("synthetic_worker_id") == worker_id
                 and plan.get("synthetic_worker_key") == "synthetic-worker-b0",
                 "Controller plan worker identity differs")
    core.require(client.worker_id(dict(arm="synthetic", cell="worker", block=0)) == worker_id,
                 "Controller worker identity differs")
    exit_code = core.wait_worker(inspect, client.stopped, clock=client.clock, sleep=sleep)
    core.require(exit_code == 0, "Synthetic PID1 did not exit successfully")
    directory = Path(receipt_directory)
    synthetic = core.decode(core.read_file(directory / "synthetic-receipt.json")[0])
    finalizer = core.decode(core.read_file(directory / (plan["synthetic_worker_key"] + "-finalized.json"))[0])
    row = dict(kind="synthetic_no_benchmark_v1", status="PASS", worker=worker_id,
        sample=plan["synthetic_slot"], application_requests=0, provider_calls=0,
               benchmark_samples=0)
    core.require(synthetic == dict(schema="orq41-synthetic-receipt-v1",
        kind="synthetic_no_benchmark_v1", plan=core.digest(plan), worker=worker_id,
        sample=plan["synthetic_slot"], application_requests=0, provider_calls=0,
        benchmark_samples=0, result=core.digest(row)),
        "Synthetic receipt identity/evidence differs")
    core.require(finalizer == dict(plan=core.digest(plan), worker=worker_id, finalized=True),
                 "Existing worker finalizer receipt differs")
    return client.finish(synthetic, sleep=sleep)
