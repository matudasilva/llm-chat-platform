"""Offline attempt accounting and fail-closed pre-dispatch budget guards."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import math

INPUT_PRICE_PER_MILLION = Decimal("0.15")
OUTPUT_PRICE_PER_MILLION = Decimal("0.60")
STAGE_0_HARD_CAP_USD = Decimal("0")
DEVELOPMENT_HARD_CAP_USD = Decimal("3")
CONFIRMATORY_HARD_CAP_USD = Decimal("7")
CUMULATIVE_HARD_CAP_USD = Decimal("10")
ABSOLUTE_ATTEMPT_CAP = 1_100
CONFIRMATORY_RETRY_CAP = 76

_ARM_INPUT_CAPS = {
    "A": 512,
    "B": 4_608,
    "E-BM25": 4_608,
    "ORACLE-GOLD": 3_072,
}
_ELIGIBLE_TRANSPORT_FAILURES = {
    "timeout_before_first_response_byte_or_token",
    "connection_reset_before_first_response_byte_or_token",
    "premature_eof_before_first_response_byte_or_token",
}
_ELIGIBLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


class Phase(str, Enum):
    STAGE_0 = "stage_0"
    DEVELOPMENT = "development"
    CONFIRMATORY = "confirmatory"


class GuardBlocked(RuntimeError):
    """A dispatch or accounting operation failed closed."""


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.input_tokens, self.output_tokens)
        ):
            raise ValueError("usage tokens must be non-negative integers")


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    step_id: str
    arm_id: str
    phase: Phase
    attempt_ordinal: int
    parent_attempt_id: str | None
    failure_class: str | None
    request_parameter_hash: str
    reported_usage_or_null: Usage | None
    reserved_worst_case_cost: Decimal
    reserved_input_tokens: int
    reserved_output_tokens: int
    response_token_or_candidate_received: bool = False
    http_status: int | None = None

    def __post_init__(self) -> None:
        if not self.step_id or not self.arm_id:
            raise ValueError("step_id and arm_id must be non-empty")
        if self.attempt_ordinal not in {1, 2}:
            raise GuardBlocked("a step-arm cell permits at most two attempts")
        if self.attempt_ordinal == 1 and self.parent_attempt_id is not None:
            raise GuardBlocked("first attempts cannot have a parent")
        if self.attempt_ordinal == 2 and self.parent_attempt_id is None:
            raise GuardBlocked("retry attempts require their first-attempt parent")
        if self.phase == Phase.STAGE_0:
            raise GuardBlocked("Stage 0 cannot contain external attempt records")
        allowed_arms = {"A", "B", "E-BM25"}
        if self.phase == Phase.DEVELOPMENT:
            allowed_arms.add("ORACLE-GOLD")
        if self.arm_id not in allowed_arms:
            raise GuardBlocked("attempt record uses an arm unavailable in its phase")
        if self.reserved_input_tokens != _ARM_INPUT_CAPS[self.arm_id]:
            raise GuardBlocked("attempt record must reserve the frozen arm input ceiling")
        if self.reserved_output_tokens != 256:
            raise GuardBlocked("attempt record must reserve the frozen output ceiling")
        if len(self.request_parameter_hash) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.request_parameter_hash
        ):
            raise ValueError("request_parameter_hash must be lowercase SHA-256 hex")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.reserved_input_tokens, self.reserved_output_tokens)
        ):
            raise ValueError("reserved tokens must be non-negative integers")
        expected_cost = worst_case_generation_cost(
            self.reserved_input_tokens, self.reserved_output_tokens
        )
        if self.reserved_worst_case_cost != expected_cost:
            raise ValueError("reserved cost must equal the frozen worst-case price")
        if self.reported_usage_or_null is not None and (
            self.reported_usage_or_null.input_tokens > self.reserved_input_tokens
            or self.reported_usage_or_null.output_tokens > self.reserved_output_tokens
        ):
            raise GuardBlocked("reported usage exceeded its reserved token ceilings")
        if (
            self.reported_usage_or_null is not None
            and self.reported_usage_or_null.output_tokens > 0
            and not self.response_token_or_candidate_received
        ):
            raise GuardBlocked("nonzero output usage proves response emission")

    @property
    def attempt_id(self) -> str:
        return f"{self.phase.value}:{self.step_id}:{self.arm_id}:{self.attempt_ordinal}"


@dataclass(slots=True)
class AttemptLedger:
    records: list[AttemptRecord] = field(default_factory=list)
    _confirmatory_conversations: int | None = field(
        default=None, init=False, repr=False
    )

    @property
    def confirmatory_conversations(self) -> int | None:
        return self._confirmatory_conversations

    def freeze_confirmatory_sample(self, conversations: int) -> None:
        if conversations not in {48, 64}:
            raise GuardBlocked("confirmatory sample must be 48 or 64")
        if any(record.phase == Phase.CONFIRMATORY for record in self.records):
            raise GuardBlocked("sample size must be frozen before confirmatory attempts")
        if self._confirmatory_conversations not in {None, conversations}:
            raise GuardBlocked("confirmatory sample size is immutable once frozen")
        self._confirmatory_conversations = conversations

    def append(self, record: AttemptRecord) -> None:
        self.validate_integrity()
        if len(self.records) >= ABSOLUTE_ATTEMPT_CAP:
            raise GuardBlocked("ORQ cumulative attempt cap is exceeded")
        if record.attempt_ordinal not in {1, 2}:
            raise GuardBlocked("a step-arm cell permits at most two attempts")
        cell = [
            existing
            for existing in self.records
            if (existing.phase, existing.step_id, existing.arm_id)
            == (record.phase, record.step_id, record.arm_id)
        ]
        if record.attempt_ordinal != len(cell) + 1:
            raise GuardBlocked("attempt ordinals must be consecutive and one-based")
        if record.attempt_ordinal == 1 and record.parent_attempt_id is not None:
            raise GuardBlocked("first attempts cannot have a parent")
        if record.attempt_ordinal == 2:
            if not cell or record.parent_attempt_id != cell[0].attempt_id:
                raise GuardBlocked("retry must reference the first attempt in its cell")
            if not retry_is_eligible(cell[0]):
                raise GuardBlocked("previous attempt is not eligible for retry")
            if sum(
                existing.phase == Phase.CONFIRMATORY
                and existing.attempt_ordinal == 2
                for existing in self.records
            ) >= CONFIRMATORY_RETRY_CAP:
                raise GuardBlocked("confirmatory retry cap is exceeded")
        if any(existing.attempt_id == record.attempt_id for existing in self.records):
            raise GuardBlocked("duplicate attempt ledger entry")
        self.records.append(record)
        try:
            self.validate_integrity()
        except GuardBlocked:
            self.records.pop()
            raise

    def validate_integrity(self) -> None:
        if self.confirmatory_conversations not in {None, 48, 64}:
            raise GuardBlocked("attempt ledger has an invalid frozen sample size")
        seen: set[str] = set()
        cells: dict[tuple[Phase, str, str], list[AttemptRecord]] = {}
        retries = 0
        for record in self.records:
            try:
                record.__post_init__()
            except (GuardBlocked, ValueError) as exc:
                raise GuardBlocked("attempt ledger contains an invalid record") from exc
            if record.attempt_ordinal not in {1, 2}:
                raise GuardBlocked("attempt ledger contains an ordinal above two")
            if record.attempt_ordinal == 1 and record.parent_attempt_id is not None:
                raise GuardBlocked("attempt ledger contains a parented first attempt")
            if record.attempt_id in seen:
                raise GuardBlocked("attempt ledger contains duplicate IDs")
            seen.add(record.attempt_id)
            key = (record.phase, record.step_id, record.arm_id)
            cell = cells.setdefault(key, [])
            if record.attempt_ordinal != len(cell) + 1:
                raise GuardBlocked("attempt ledger contains a non-consecutive cell")
            if record.attempt_ordinal == 2:
                if not cell or record.parent_attempt_id != cell[0].attempt_id:
                    raise GuardBlocked("attempt ledger contains an orphan retry")
                if not retry_is_eligible(cell[0]):
                    raise GuardBlocked("attempt ledger contains an ineligible retry")
                retries += 1
            cell.append(record)
        if len(self.records) > ABSOLUTE_ATTEMPT_CAP:
            raise GuardBlocked("attempt ledger exceeds the cumulative cap")
        if retries > CONFIRMATORY_RETRY_CAP:
            raise GuardBlocked("attempt ledger exceeds the confirmatory retry cap")
        if any(record.phase == Phase.CONFIRMATORY for record in self.records) and (
            self.confirmatory_conversations not in {48, 64}
        ):
            raise GuardBlocked("confirmatory ledger has no frozen sample size")
        for phase in (Phase.STAGE_0, Phase.DEVELOPMENT, Phase.CONFIRMATORY):
            phase_records = self.phase_records(phase)
            if not phase_records:
                continue
            attempt_cap, input_cap, output_cap, cost_cap = _phase_limits(
                phase, self.confirmatory_conversations
            )
            if len(phase_records) > attempt_cap:
                raise GuardBlocked("attempt ledger exceeds a phase attempt cap")
            if sum(record.reserved_input_tokens for record in phase_records) > input_cap:
                raise GuardBlocked("attempt ledger exceeds a phase input-token cap")
            if sum(record.reserved_output_tokens for record in phase_records) > output_cap:
                raise GuardBlocked("attempt ledger exceeds a phase output-token cap")
            phase_cost = sum(
                (record.reserved_worst_case_cost for record in phase_records),
                start=Decimal("0"),
            )
            if phase_cost > cost_cap:
                raise GuardBlocked("attempt ledger exceeds a phase cost cap")
        if self.confirmatory_conversations in {48, 64}:
            first_attempt_cap = 576 if self.confirmatory_conversations == 48 else 768
            first_attempts = sum(
                record.phase == Phase.CONFIRMATORY and record.attempt_ordinal == 1
                for record in self.records
            )
            if first_attempts > first_attempt_cap:
                raise GuardBlocked("attempt ledger exceeds the confirmatory first-attempt cap")
        if self.reserved_input_tokens > 3_659_776:
            raise GuardBlocked("attempt ledger exceeds the cumulative input-token cap")
        if self.reserved_output_tokens > 281_600:
            raise GuardBlocked("attempt ledger exceeds the cumulative output-token cap")
        cumulative_cost = sum(
            (record.reserved_worst_case_cost for record in self.records),
            start=Decimal("0"),
        )
        if cumulative_cost > CUMULATIVE_HARD_CAP_USD:
            raise GuardBlocked("attempt ledger exceeds the cumulative cost cap")

    def phase_records(self, phase: Phase) -> tuple[AttemptRecord, ...]:
        return tuple(record for record in self.records if record.phase == phase)

    @property
    def reserved_input_tokens(self) -> int:
        return sum(record.reserved_input_tokens for record in self.records)

    @property
    def reserved_output_tokens(self) -> int:
        return sum(record.reserved_output_tokens for record in self.records)


def retry_is_eligible(record: AttemptRecord) -> bool:
    if record.phase != Phase.CONFIRMATORY:
        return False
    if record.attempt_ordinal != 1 or record.response_token_or_candidate_received:
        return False
    if record.failure_class in _ELIGIBLE_TRANSPORT_FAILURES:
        return True
    return record.failure_class == "eligible_http_status" and (
        record.http_status in _ELIGIBLE_HTTP_STATUSES
    )


@dataclass(frozen=True, slots=True)
class AuthorizationState:
    stage_0_enabled: bool
    development_enabled: bool = False
    confirmatory_enabled: bool = False
    external_calls_enabled: bool = False
    openai_calls_enabled: bool = False
    embedding_calls_enabled: bool = False
    bedrock_inference_enabled: bool = False


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    available_prepaid_credit_usd: Decimal | None
    cumulative_spend_usd: Decimal | None
    phase_spend_usd: Decimal | None
    auto_recharge_enabled: bool | None


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    phase: Phase
    operation: str
    arm_id: str
    input_token_ceiling: int
    output_token_ceiling: int
    attempt_ordinal: int = 1
    step_id: str = "UNSPECIFIED_STEP"
    confirmatory_conversations: int | None = None


@dataclass(frozen=True, slots=True)
class DispatchReservation:
    worst_case_cost_usd: Decimal
    cumulative_attempt_number: int
    phase_attempt_number: int


def worst_case_generation_cost(input_tokens: int, output_tokens: int) -> Decimal:
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (input_tokens, output_tokens)
    ):
        raise ValueError("token ceilings must be non-negative integers")
    return (
        Decimal(input_tokens) * INPUT_PRICE_PER_MILLION
        + Decimal(output_tokens) * OUTPUT_PRICE_PER_MILLION
    ) / Decimal(1_000_000)


def _phase_limits(
    phase: Phase, confirmatory_conversations: int | None
) -> tuple[int, int, int, Decimal]:
    if phase == Phase.STAGE_0:
        return 0, 0, 0, STAGE_0_HARD_CAP_USD
    if phase == Phase.DEVELOPMENT:
        return 256, 819_200, 65_536, DEVELOPMENT_HARD_CAP_USD
    if confirmatory_conversations == 48:
        return 652, 2_217_984, 166_912, CONFIRMATORY_HARD_CAP_USD
    if confirmatory_conversations == 64:
        return 844, 2_840_576, 216_064, CONFIRMATORY_HARD_CAP_USD
    raise GuardBlocked("confirmatory sample must be frozen to 48 or 64")


def _require_known_money(snapshot: BudgetSnapshot) -> tuple[Decimal, Decimal, Decimal]:
    values = (
        snapshot.available_prepaid_credit_usd,
        snapshot.cumulative_spend_usd,
        snapshot.phase_spend_usd,
    )
    if any(value is None for value in values):
        raise GuardBlocked("unknown balance or consumption blocks dispatch")
    if snapshot.auto_recharge_enabled is not False:
        raise GuardBlocked("Auto Recharge must be explicitly disabled")
    known = tuple(value for value in values if value is not None)
    if any(not value.is_finite() or value < 0 for value in known):
        raise GuardBlocked("budget values must be finite and non-negative")
    return known  # type: ignore[return-value]


def validate_pre_dispatch(
    request: DispatchRequest,
    *,
    authorization: AuthorizationState,
    snapshot: BudgetSnapshot,
    ledger: AttemptLedger,
) -> DispatchReservation:
    """Validate every frozen authorization, attempt, token, balance, and cost cap.

    This function returns accounting data only. The Stage 0 package intentionally
    exposes no function that can dispatch a provider request.
    """

    if request.phase == Phase.STAGE_0:
        raise GuardBlocked("Stage 0 permits zero external dispatches")
    ledger.validate_integrity()
    if not authorization.external_calls_enabled:
        raise GuardBlocked("external calls are not authorized")
    if request.operation != "openai_generation":
        raise GuardBlocked("embeddings, Bedrock, and other operations have zero cap")
    if not authorization.openai_calls_enabled:
        raise GuardBlocked("OpenAI calls are not authorized")
    if request.phase == Phase.DEVELOPMENT and not authorization.development_enabled:
        raise GuardBlocked("development is not authorized")
    if request.phase == Phase.CONFIRMATORY and not authorization.confirmatory_enabled:
        raise GuardBlocked("confirmatory execution is not authorized")
    if request.phase == Phase.CONFIRMATORY:
        if ledger.confirmatory_conversations not in {48, 64}:
            raise GuardBlocked("confirmatory sample size is not frozen")
        if request.confirmatory_conversations != ledger.confirmatory_conversations:
            raise GuardBlocked("request conflicts with the frozen confirmatory sample")
    allowed_arms = {"A", "B", "E-BM25"}
    if request.phase == Phase.DEVELOPMENT:
        allowed_arms.add("ORACLE-GOLD")
    if request.arm_id not in allowed_arms:
        raise GuardBlocked("arm is unavailable in the requested phase")
    if request.input_token_ceiling != _ARM_INPUT_CAPS[request.arm_id]:
        raise GuardBlocked("request must reserve the frozen arm input ceiling")
    if request.output_token_ceiling != 256:
        raise GuardBlocked("request must reserve the frozen output ceiling")
    if request.attempt_ordinal not in {1, 2}:
        raise GuardBlocked("attempt ordinal must be one or two")
    cell = [
        record
        for record in ledger.records
        if (record.phase, record.step_id, record.arm_id)
        == (request.phase, request.step_id, request.arm_id)
    ]
    if request.attempt_ordinal != len(cell) + 1:
        raise GuardBlocked("pre-dispatch attempt ordinal is not consecutive")
    if request.attempt_ordinal == 2 and (not cell or not retry_is_eligible(cell[0])):
        raise GuardBlocked("retry is not eligible before dispatch")

    available_credit, cumulative_spend, phase_spend = _require_known_money(snapshot)
    cost = worst_case_generation_cost(
        request.input_token_ceiling, request.output_token_ceiling
    )
    phase_attempt_cap, phase_input_cap, phase_output_cap, phase_cost_cap = _phase_limits(
        request.phase, ledger.confirmatory_conversations
    )
    phase_records = ledger.phase_records(request.phase)
    phase_attempt_number = len(phase_records) + 1
    cumulative_attempt_number = len(ledger.records) + 1
    if phase_attempt_number > phase_attempt_cap:
        raise GuardBlocked("phase attempt cap would be exceeded")
    if cumulative_attempt_number > ABSOLUTE_ATTEMPT_CAP:
        raise GuardBlocked("ORQ cumulative attempt cap would be exceeded")
    if request.phase == Phase.DEVELOPMENT and request.attempt_ordinal != 1:
        raise GuardBlocked("development permits zero retries")
    if request.phase == Phase.CONFIRMATORY:
        planned_first_attempt_cap = (
            576 if ledger.confirmatory_conversations == 48 else 768
        )
        first_attempts = sum(
            record.attempt_ordinal == 1 for record in phase_records
        )
        if first_attempts + (request.attempt_ordinal == 1) > planned_first_attempt_cap:
            raise GuardBlocked("confirmatory first-attempt cap is exceeded")
        retries = sum(record.attempt_ordinal == 2 for record in phase_records)
        if retries + (request.attempt_ordinal == 2) > CONFIRMATORY_RETRY_CAP:
            raise GuardBlocked("confirmatory retry cap is exceeded")

    phase_input = sum(record.reserved_input_tokens for record in phase_records)
    phase_output = sum(record.reserved_output_tokens for record in phase_records)
    if phase_input + request.input_token_ceiling > phase_input_cap:
        raise GuardBlocked("phase input-token ceiling would be exceeded")
    if phase_output + request.output_token_ceiling > phase_output_cap:
        raise GuardBlocked("phase output-token ceiling would be exceeded")
    if ledger.reserved_input_tokens + request.input_token_ceiling > 3_659_776:
        raise GuardBlocked("ORQ cumulative input-token ceiling would be exceeded")
    if ledger.reserved_output_tokens + request.output_token_ceiling > 281_600:
        raise GuardBlocked("ORQ cumulative output-token ceiling would be exceeded")
    if cost > available_credit:
        raise GuardBlocked("prepaid balance cannot cover the worst-case reservation")
    ledger_phase_cost = sum(
        (record.reserved_worst_case_cost for record in phase_records),
        start=Decimal("0"),
    )
    ledger_cumulative_cost = sum(
        (record.reserved_worst_case_cost for record in ledger.records),
        start=Decimal("0"),
    )
    if ledger_phase_cost + cost > phase_cost_cap:
        raise GuardBlocked("phase reserved-cost hard cap would be exceeded")
    if ledger_cumulative_cost + cost > CUMULATIVE_HARD_CAP_USD:
        raise GuardBlocked("ORQ reserved-cost hard cap would be exceeded")
    if phase_spend + cost > phase_cost_cap:
        raise GuardBlocked("phase monetary hard cap would be exceeded")
    if cumulative_spend + cost > CUMULATIVE_HARD_CAP_USD:
        raise GuardBlocked("ORQ cumulative monetary hard cap would be exceeded")
    if not math.isfinite(float(cost)):
        raise GuardBlocked("cost reservation is not finite")
    return DispatchReservation(cost, cumulative_attempt_number, phase_attempt_number)
