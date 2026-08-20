from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path
import unittest

from experiments.long_context_conversational_memory.determinism import (
    CONFIRMATORY_BOOTSTRAP_PREFIX,
    SANITY_BOOTSTRAP_PREFIX,
    SANITY_UNIFORM_PREFIX,
    analytic_power,
    confirmatory_bootstrap_integer_sum,
    confirmatory_bootstrap_index,
    confirmatory_lower_bound_integer_sum,
    confirmatory_margin_passes,
    first_uint64,
    join_domain,
    open_binary64_uniform_from_x,
    sanity_acceptance_fraction,
    sanity_bootstrap_replicate_mean,
    sanity_bootstrap_index,
    sanity_inner_lower_bound,
    sanity_normal_observation,
    sanity_uniform_domain,
    select_48_or_stop,
    unbiased_zero_based_index,
)
from experiments.long_context_conversational_memory.scoring import score_response


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    ROOT
    / ".framework/orqs/ORQ-30-long-context-conversational-memory/experiment-manifest.json"
)


class Orq30DeterminismTests(unittest.TestCase):
    def test_open_uniform_is_total_and_open_at_sha256_uint64_extremes(self) -> None:
        low = open_binary64_uniform_from_x(0)
        high = open_binary64_uniform_from_x(2**64 - 1)
        self.assertGreater(low, 0.0)
        self.assertLess(low, 1.0)
        self.assertGreater(high, 0.0)
        self.assertLess(high, 1.0)

    def test_sha256_uint64_uses_first_eight_bytes_big_endian(self) -> None:
        payload = "á|0|1".encode("utf-8")
        expected = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        self.assertEqual(first_uint64(payload), expected)

    def test_domains_are_exact_utf8_unsigned_decimal_and_zero_based(self) -> None:
        self.assertEqual(
            sanity_uniform_domain(48, 0, 0),
            "ORQ-30|mve-v2|selector-normal-power|v1|48|0|0",
        )
        self.assertEqual(
            sanity_uniform_domain(48, 0, 0).encode("utf-8"),
            b"ORQ-30|mve-v2|selector-normal-power|v1|48|0|0",
        )
        with self.assertRaises(ValueError):
            join_domain(SANITY_UNIFORM_PREFIX, -1)
        self.assertGreaterEqual(sanity_bootstrap_index(48, 0, 0, 0), 0)
        self.assertLess(sanity_bootstrap_index(48, 0, 0, 0), 48)
        self.assertGreaterEqual(confirmatory_bootstrap_index(64, 0, 0), 0)
        self.assertLess(confirmatory_bootstrap_index(64, 0, 0), 64)

    def test_rejection_sampling_uses_no_counter_then_counter_one(self) -> None:
        payloads: list[bytes] = []

        def controlled(payload: bytes) -> int:
            payloads.append(payload)
            return 2**64 - 1 if len(payloads) == 1 else 7

        base = join_domain(CONFIRMATORY_BOOTSTRAP_PREFIX, 10, 0, 0)
        selected = unbiased_zero_based_index(base, 10, derive_x=controlled)
        self.assertEqual(selected, 7)
        self.assertEqual(payloads, [base.encode("utf-8"), base.encode("utf-8") + b"|1"])

    def test_rejection_sampling_fails_closed_after_1024_rehashes(self) -> None:
        base = join_domain(CONFIRMATORY_BOOTSTRAP_PREFIX, 10, 0, 0)
        payloads: list[bytes] = []

        def always_reject(payload: bytes) -> int:
            payloads.append(payload)
            return 2**64 - 1

        with self.assertRaises(RuntimeError):
            unbiased_zero_based_index(base, 10, derive_x=always_reject)
        self.assertEqual(len(payloads), 1_025)
        self.assertEqual(payloads[0], base.encode("utf-8"))
        self.assertEqual(payloads[-1], base.encode("utf-8") + b"|1024")

    def test_power_implementation_matches_manifest_operation_order(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        operations = manifest["sample_size_selector"]["authoritative_operation_order"]
        self.assertEqual(
            operations,
            [
                "sigma_plan = max(0.10, s * math.sqrt(15 / 7.260943927670032))",
                "z = 0.05 * math.sqrt(n) / sigma_plan - 1.644853626951",
                "power = statistics.NormalDist().cdf(z)",
                "eligible = power >= 0.80",
            ],
        )
        implementation_source = inspect.getsource(analytic_power)
        for operation in operations:
            self.assertIn(operation, implementation_source)
        result = analytic_power(0.15, 64)
        self.assertTrue(math.isfinite(result.sigma_plan))
        self.assertTrue(math.isfinite(result.z))
        self.assertTrue(math.isfinite(result.power))

    def test_unit_selector_can_choose_48_or_stop_without_simulation(self) -> None:
        self.assertEqual(select_48_or_stop(0.05, 0.78)[0], 48)
        self.assertIsNone(select_48_or_stop(1.0, 0.78)[0])
        for invalid in (-0.1, 1.1, True, float("nan")):
            with self.assertRaises(RuntimeError):
                select_48_or_stop(0.05, invalid)

    def test_registered_bootstrap_arithmetic_uses_exact_order_statistics(self) -> None:
        self.assertEqual(
            sanity_bootstrap_replicate_mean((0.0,) * 48, t=0, r=0), 0.0
        )
        self.assertTrue(math.isfinite(sanity_normal_observation(0.1, n=48, t=0, j=0)))
        inner_means = tuple(float(value) for value in range(1_000, 0, -1))
        self.assertEqual(sanity_inner_lower_bound(inner_means), 50.0)
        lower_bounds = (0.05,) * 500 + (0.0500001,) * 1_500
        self.assertEqual(sanity_acceptance_fraction(lower_bounds), 0.75)

        self.assertEqual(
            confirmatory_bootstrap_integer_sum((2,) * 48, r=0), 96
        )
        replicate_sums = tuple(range(10_000, 0, -1))
        self.assertEqual(confirmatory_lower_bound_integer_sum(replicate_sums), 500)
        self.assertTrue(confirmatory_margin_passes(5, 48))
        self.assertFalse(confirmatory_margin_passes(6, 64))

    def test_nonfinite_power_inputs_fail_integrity(self) -> None:
        for value in (float("nan"), float("inf"), -0.1):
            with self.assertRaises(RuntimeError):
                analytic_power(value, 48)

    def test_registered_domain_prefixes_match_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        domains = manifest["sha256_derivation_contract"]["declared_base_domains"]
        self.assertEqual(domains["sanity_uniform"], SANITY_UNIFORM_PREFIX + "|n|t|j")
        self.assertEqual(
            domains["sanity_bootstrap_index"], SANITY_BOOTSTRAP_PREFIX + "|n|t|r|j"
        )
        self.assertEqual(
            domains["confirmatory_bootstrap_index"],
            CONFIRMATORY_BOOTSTRAP_PREFIX + "|n|r|j",
        )


class Orq30ScoringTests(unittest.TestCase):
    def test_exact_answer_is_order_independent_after_duplicate_validation(self) -> None:
        result = score_response(
            b'{"decision":"answer","values":["NONCE_B","NONCE_A"]}',
            frozenset({"NONCE_A", "NONCE_B"}),
        )
        self.assertTrue(result.correct)
        self.assertFalse(result.retry_allowed)

    def test_only_exact_canonical_abstention_is_correct_without_evidence(self) -> None:
        self.assertTrue(
            score_response(
                b'{"decision":"abstain","values":[]}', frozenset()
            ).correct
        )
        variants = [
            b'{"decision": "abstain","values":[]}',
            b'{"values":[],"decision":"abstain"}',
            b'{"decision":"answer","values":["NONCE"]}',
        ]
        for variant in variants:
            self.assertFalse(score_response(variant, frozenset()).correct)

    def test_duplicate_keys_values_extra_keys_and_invalid_nonces_are_incorrect(self) -> None:
        cases = [
            b'{"decision":"answer","decision":"abstain","values":[]}',
            b'{"decision":"answer","values":["NONCE","NONCE"]}',
            b'{"decision":"answer","values":["NONCE"],"extra":0}',
            b'{"decision":"answer","values":["lowercase"]}',
            '{"decision":"answer","values":["NONCÉ"]}'.encode("utf-8"),
            b'{"decision":"answer","values":[]}',
        ]
        for content in cases:
            result = score_response(content, frozenset({"NONCE"}))
            self.assertFalse(result.correct)
            self.assertFalse(result.retry_allowed)

    def test_malformed_surrounding_content_refusal_and_nonstandard_constants_fail(self) -> None:
        cases = [
            b"not JSON",
            b"I refuse",
            b' {"decision":"abstain","values":[]}',
            b'{"decision":"abstain","values":[]}\n',
            b'{"decision":"answer","values":[NaN]}',
            b"\xff",
        ]
        for content in cases:
            result = score_response(content, frozenset())
            self.assertFalse(result.correct)
            self.assertEqual(result.failure_class, "parse_failure")
            self.assertFalse(result.retry_allowed)

    def test_superseded_extra_or_cross_scope_nonce_is_incorrect(self) -> None:
        for extra in ("SUPERSEDED_NONCE", "OTHER_TENANT_NONCE"):
            content = (
                '{"decision":"answer","values":["CURRENT_NONCE","'
                + extra
                + '"]}'
            )
            self.assertFalse(
                score_response(content, frozenset({"CURRENT_NONCE"})).correct
            )


if __name__ == "__main__":
    unittest.main()
