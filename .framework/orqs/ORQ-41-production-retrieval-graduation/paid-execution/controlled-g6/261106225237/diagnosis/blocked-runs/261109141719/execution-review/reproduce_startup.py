"""Pure startup counterexample; no app lifespan, Redis, SQL or provider operation."""
import json
from pathlib import Path

from experiments.production_graduation.gate_validation.local_api import NamespacedRedis
from experiments.production_graduation.gate_validation.fixtures import HarnessError


def main():
    out = Path(__file__).resolve().parent
    plan = json.loads((out.parent / "plan.json").read_text())
    invalid, candidate_values = [], []
    for entry in plan["arm_cell_order"]:
        key = f'{entry["arm"]}-{entry["cell"]}-b{entry["block"]}'
        actual = f'orq41:g123:{plan["run_id"]}:{key}:'
        try:
            NamespacedRedis(None, actual)
        except HarnessError as exc:
            invalid.append(dict(entry=entry, namespace=actual, error=str(exc)))
        else:
            raise AssertionError("Expected the actual startup namespace to fail")
        # Counterfactual format check only, not a patch or execution of the worker.
        cell = ("EN-json", "EN-sse", "ES-json", "ES-sse").index(entry["cell"])
        candidate = f'orq41:g123:{plan["run_id"]}b{cell}{entry["block"]}:{entry["arm"]}:'
        NamespacedRedis(None, candidate)
        candidate_values.append(candidate)
    assert len(invalid) == len(set(candidate_values)) == 32
    result = dict(status="BLOCKED_AA_STARTUP_NAMESPACE_DEFECT_REPRODUCED", invalid_actual_namespaces=invalid,
                  counterfactual_namespaces=candidate_values, counterfactual_only_not_implemented=True,
                  network_calls=0, app_lifespan_calls=0, postgres_calls=0, provider_calls=0)
    path = out / "startup-reproduction.json"
    assert not path.exists()
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"])


if __name__ == "__main__":
    main()
