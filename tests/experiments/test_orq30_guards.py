from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
import unittest

from experiments.long_context_conversational_memory.guards import (
    AttemptLedger,
    AttemptRecord,
    AuthorizationState,
    BudgetSnapshot,
    DispatchRequest,
    GuardBlocked,
    Phase,
    Usage,
    retry_is_eligible,
    validate_pre_dispatch,
    worst_case_generation_cost,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "experiments/long_context_conversational_memory"


def snapshot(
    *,
    balance: Decimal | None = Decimal("3.85"),
    cumulative: Decimal | None = Decimal("0"),
    phase: Decimal | None = Decimal("0"),
) -> BudgetSnapshot:
    return BudgetSnapshot(balance, cumulative, phase, False)


def authorization(**overrides: bool) -> AuthorizationState:
    values = {
        "stage_0_enabled": True,
        "development_enabled": True,
        "confirmatory_enabled": True,
        "external_calls_enabled": True,
        "openai_calls_enabled": True,
    }
    values.update(overrides)
    return AuthorizationState(**values)


def record(
    step_id: str,
    phase: Phase,
    *,
    ordinal: int = 1,
    parent: str | None = None,
    failure: str | None = None,
    status: int | None = None,
    input_tokens: int = 512,
    output_tokens: int = 256,
    usage: Usage | None = None,
    response_received: bool = False,
    arm_id: str = "A",
) -> AttemptRecord:
    return AttemptRecord(
        step_id=step_id,
        arm_id=arm_id,
        phase=phase,
        attempt_ordinal=ordinal,
        parent_attempt_id=parent,
        failure_class=failure,
        request_parameter_hash="0" * 64,
        reported_usage_or_null=usage,
        reserved_worst_case_cost=worst_case_generation_cost(
            input_tokens, output_tokens
        ),
        reserved_input_tokens=input_tokens,
        reserved_output_tokens=output_tokens,
        response_token_or_candidate_received=response_received,
        http_status=status,
    )


class Orq30GuardTests(unittest.TestCase):
    def test_stage_0_blocks_every_provider_operation_even_if_flags_are_true(self) -> None:
        for operation in ("openai_generation", "embedding", "bedrock_inference"):
            with self.assertRaises(GuardBlocked):
                validate_pre_dispatch(
                    DispatchRequest(Phase.STAGE_0, operation, "A", 512, 256),
                    authorization=authorization(),
                    snapshot=snapshot(),
                    ledger=AttemptLedger(),
                )

    def test_current_unapproved_external_authorization_blocks_dispatch(self) -> None:
        with self.assertRaises(GuardBlocked):
            validate_pre_dispatch(
                DispatchRequest(Phase.DEVELOPMENT, "openai_generation", "A", 512, 256),
                authorization=AuthorizationState(stage_0_enabled=True),
                snapshot=snapshot(),
                ledger=AttemptLedger(),
            )

    def test_unknown_balance_or_consumption_blocks_fail_closed(self) -> None:
        for unknown in (
            snapshot(balance=None),
            snapshot(cumulative=None),
            snapshot(phase=None),
        ):
            with self.assertRaises(GuardBlocked):
                validate_pre_dispatch(
                    DispatchRequest(
                        Phase.DEVELOPMENT, "openai_generation", "A", 512, 256
                    ),
                    authorization=authorization(),
                    snapshot=unknown,
                    ledger=AttemptLedger(),
                )

    def test_balance_phase_and_cumulative_cost_caps_block(self) -> None:
        request = DispatchRequest(
            Phase.DEVELOPMENT, "openai_generation", "A", 512, 256
        )
        cost = worst_case_generation_cost(512, 256)
        cases = (
            snapshot(balance=cost - Decimal("0.0000001")),
            snapshot(phase=Decimal("3") - cost + Decimal("0.0000001")),
            snapshot(cumulative=Decimal("10") - cost + Decimal("0.0000001")),
        )
        for budget in cases:
            with self.assertRaises(GuardBlocked):
                validate_pre_dispatch(
                    request,
                    authorization=authorization(),
                    snapshot=budget,
                    ledger=AttemptLedger(),
                )

    def test_frozen_arm_and_token_limits_are_enforced(self) -> None:
        invalid_requests = (
            DispatchRequest(Phase.DEVELOPMENT, "embedding", "A", 512, 256),
            DispatchRequest(Phase.DEVELOPMENT, "openai_generation", "A", 511, 256),
            DispatchRequest(Phase.DEVELOPMENT, "openai_generation", "A", 512, 255),
            DispatchRequest(
                Phase.CONFIRMATORY,
                "openai_generation",
                "ORACLE-GOLD",
                3_072,
                256,
                confirmatory_conversations=64,
            ),
        )
        for request in invalid_requests:
            with self.assertRaises(GuardBlocked):
                validate_pre_dispatch(
                    request,
                    authorization=authorization(),
                    snapshot=snapshot(),
                    ledger=AttemptLedger(),
                )

    def test_development_permits_zero_retries(self) -> None:
        first = record(
            "STEP_0",
            Phase.DEVELOPMENT,
            failure="timeout_before_first_response_byte_or_token",
        )
        ledger = AttemptLedger()
        ledger.append(first)
        self.assertFalse(retry_is_eligible(first))
        with self.assertRaises(GuardBlocked):
            ledger.append(
                record(
                    "STEP_0",
                    Phase.DEVELOPMENT,
                    ordinal=2,
                    parent=first.attempt_id,
                )
            )
        with self.assertRaises(GuardBlocked):
            validate_pre_dispatch(
                DispatchRequest(
                    Phase.DEVELOPMENT,
                    "openai_generation",
                    "A",
                    512,
                    256,
                    attempt_ordinal=2,
                    step_id="STEP_0",
                ),
                authorization=authorization(),
                snapshot=snapshot(),
                ledger=ledger,
            )

    def test_attempt_records_reject_third_attempts_and_parented_firsts(self) -> None:
        with self.assertRaises(GuardBlocked):
            record("THIRD", Phase.CONFIRMATORY, ordinal=3)
        with self.assertRaises(GuardBlocked):
            record("PARENTED_FIRST", Phase.CONFIRMATORY, parent="unexpected")

    def test_preloaded_ledger_revalidates_records_and_frozen_sample(self) -> None:
        understated = record("UNDERSTATED", Phase.DEVELOPMENT)
        object.__setattr__(understated, "reserved_input_tokens", 0)
        object.__setattr__(understated, "reserved_output_tokens", 0)
        object.__setattr__(understated, "reserved_worst_case_cost", Decimal("0"))
        with self.assertRaises(GuardBlocked):
            AttemptLedger(records=[understated]).validate_integrity()

        invalid_sample = AttemptLedger()
        object.__setattr__(invalid_sample, "_confirmatory_conversations", 49)
        with self.assertRaises(GuardBlocked):
            invalid_sample.validate_integrity()

    def test_confirmatory_allows_at_most_76_eligible_retries(self) -> None:
        ledger = AttemptLedger()
        ledger.freeze_confirmatory_sample(64)
        for index in range(76):
            first = record(
                f"STEP_{index}",
                Phase.CONFIRMATORY,
                failure="eligible_http_status",
                status=429,
            )
            ledger.append(first)
            ledger.append(
                record(
                    f"STEP_{index}",
                    Phase.CONFIRMATORY,
                    ordinal=2,
                    parent=first.attempt_id,
                )
            )
        next_first = record(
            "STEP_76",
            Phase.CONFIRMATORY,
            failure="eligible_http_status",
            status=429,
        )
        ledger.append(next_first)
        with self.assertRaises(GuardBlocked):
            validate_pre_dispatch(
                DispatchRequest(
                    Phase.CONFIRMATORY,
                    "openai_generation",
                    "A",
                    512,
                    256,
                    attempt_ordinal=2,
                    step_id="STEP_76",
                    confirmatory_conversations=64,
                ),
                authorization=authorization(),
                snapshot=snapshot(),
                ledger=ledger,
            )

    def test_confirmatory_sample_and_first_attempt_cap_are_immutable(self) -> None:
        ledger = AttemptLedger()
        ledger.freeze_confirmatory_sample(48)
        with self.assertRaises(GuardBlocked):
            ledger.freeze_confirmatory_sample(64)
        with self.assertRaises(GuardBlocked):
            validate_pre_dispatch(
                DispatchRequest(
                    Phase.CONFIRMATORY,
                    "openai_generation",
                    "A",
                    512,
                    256,
                    step_id="MISMATCH",
                    confirmatory_conversations=64,
                ),
                authorization=authorization(),
                snapshot=snapshot(),
                ledger=ledger,
            )
        for index in range(576):
            ledger.append(record(f"FIRST_{index}", Phase.CONFIRMATORY))
        with self.assertRaises(GuardBlocked):
            validate_pre_dispatch(
                DispatchRequest(
                    Phase.CONFIRMATORY,
                    "openai_generation",
                    "A",
                    512,
                    256,
                    step_id="FIRST_576",
                    confirmatory_conversations=48,
                ),
                authorization=authorization(),
                snapshot=snapshot(),
                ledger=ledger,
            )

    def test_nonzero_reported_output_proves_emission_and_blocks_retry(self) -> None:
        with self.assertRaises(GuardBlocked):
            record(
                "OUTPUT_USAGE",
                Phase.CONFIRMATORY,
                failure="eligible_http_status",
                status=429,
                usage=Usage(input_tokens=100, output_tokens=1),
                response_received=False,
            )
        emitted = record(
            "EMITTED",
            Phase.CONFIRMATORY,
            failure="eligible_http_status",
            status=429,
            usage=Usage(input_tokens=100, output_tokens=1),
            response_received=True,
        )
        self.assertFalse(retry_is_eligible(emitted))

    def test_attempt_input_output_and_absolute_ceiling_guards(self) -> None:
        over_attempts = AttemptLedger(
            records=[record(f"STEP_{index}", Phase.DEVELOPMENT) for index in range(256)]
        )
        with self.assertRaises(GuardBlocked):
            validate_pre_dispatch(
                DispatchRequest(Phase.DEVELOPMENT, "openai_generation", "A", 512, 256),
                authorization=authorization(),
                snapshot=snapshot(),
                ledger=over_attempts,
            )

        for input_tokens, output_tokens in ((0, 256), (4_608, 0), (4_607, 256)):
            with self.assertRaises(GuardBlocked):
                record(
                    "STEP_TOKENS",
                    Phase.DEVELOPMENT,
                    arm_id="B",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
        with self.assertRaises(GuardBlocked):
            record(
                "ORACLE_CONFIRMATORY",
                Phase.CONFIRMATORY,
                arm_id="ORACLE-GOLD",
                input_tokens=3_072,
            )

    def test_worst_case_ledger_arithmetic_matches_manifest(self) -> None:
        development = worst_case_generation_cost(819_200, 65_536)
        confirmatory = worst_case_generation_cost(2_490_368, 196_608)
        retry = worst_case_generation_cost(350_208, 19_456)
        self.assertEqual(development, Decimal("0.1622016"))
        self.assertEqual(confirmatory, Decimal("0.49152"))
        self.assertEqual(retry, Decimal("0.0642048"))
        self.assertEqual(development + confirmatory + retry, Decimal("0.7179264"))

    def test_reported_usage_can_be_null_but_never_coerced_to_zero(self) -> None:
        attempt = record("STEP_NULL", Phase.DEVELOPMENT)
        self.assertIsNone(attempt.reported_usage_or_null)
        self.assertNotEqual(attempt.reported_usage_or_null, Usage(0, 0))

    def test_experimental_package_has_no_network_or_provider_imports(self) -> None:
        forbidden = {
            "boto3",
            "botocore",
            "httpx",
            "openai",
            "redis",
            "requests",
            "socket",
            "urllib",
        }
        violations: list[tuple[str, str]] = []
        for source_path in PACKAGE.glob("*.py"):
            tree = ast.parse(source_path.read_text(), filename=str(source_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    names = []
                for name in names:
                    if name not in forbidden:
                        continue
                    if source_path.name == "run_development.py" and name == "urllib":
                        continue
                    violations.append((source_path.name, name))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
