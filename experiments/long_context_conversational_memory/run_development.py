"""One-shot ORQ-30 development runner; networking exists only behind ``--execute``."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .development import (
    AMENDED_DEVELOPMENT_ARMS,
    AMENDED_DEVELOPMENT_REQUESTS,
    DEVELOPMENT_REQUESTS,
    PreparedDevelopmentRequest,
    api_request_body,
    build_amended_development_requests,
    build_development_dataset,
    build_development_requests,
    write_development_dataset,
)
from .guards import (
    AttemptLedger,
    AttemptRecord,
    AuthorizationState,
    BudgetSnapshot,
    DispatchRequest,
    Phase,
    Usage,
    validate_pre_dispatch,
)
from .scoring import score_response
from .tokenization import load_offline_encoding


ROOT = Path(__file__).resolve().parents[2]
ORQ_DIR = ROOT / ".framework/orqs/ORQ-30-long-context-conversational-memory"
DEFAULT_OUTPUT_DIR = ORQ_DIR / "development"
AMENDED_OUTPUT_DIR = ORQ_DIR / "development-amended"
REPLACEMENT_OUTPUT_DIR = ORQ_DIR / "development-replacement"
DEFAULT_CACHE_DIR = ROOT / ".framework/cache/orq-30/tiktoken"
MODEL = "gpt-4o-mini-2024-07-18"
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


class DevelopmentRunError(RuntimeError):
    """A development run cannot continue safely."""


def _configured_api_key() -> str | None:
    """Read only the configured key without importing application/provider code."""

    if value := os.environ.get("OPENAI_API_KEY"):
        return value
    env_path = ROOT / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != "OPENAI_API_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            stream.write("\n")
    temporary.replace(path)


def _body(prepared: PreparedDevelopmentRequest) -> bytes:
    return api_request_body(prepared.context.prompt_text)


def _require_configured_api_key() -> str:
    value = _configured_api_key()
    if not value:
        raise DevelopmentRunError(
            "OPENAI_API_KEY is unavailable through the configured settings"
        )
    return value


def _request(prepared: PreparedDevelopmentRequest, api_key: str) -> Request:
    return Request(
        CHAT_COMPLETIONS_URL,
        data=_body(prepared),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )


def _extract_response(payload: dict[str, Any]) -> tuple[str | None, Usage | None]:
    choices = payload.get("choices")
    content: str | None = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = message["content"]
    usage_object = payload.get("usage")
    usage: Usage | None = None
    if isinstance(usage_object, dict):
        prompt = usage_object.get("prompt_tokens")
        completion = usage_object.get("completion_tokens")
        if isinstance(prompt, int) and isinstance(completion, int):
            usage = Usage(prompt, completion)
    return content, usage


def _snapshot(
    ledger: AttemptLedger,
    *,
    prior_reserved_cost: Decimal = Decimal("0"),
) -> BudgetSnapshot:
    reserved = sum(
        (record.reserved_worst_case_cost for record in ledger.records),
        start=Decimal("0"),
    )
    development_reserved = sum(
        (record.reserved_worst_case_cost for record in ledger.phase_records(Phase.DEVELOPMENT)),
        start=Decimal("0"),
    )
    return BudgetSnapshot(
        available_prepaid_credit_usd=Decimal("3.85") - prior_reserved_cost - reserved,
        cumulative_spend_usd=prior_reserved_cost + reserved,
        phase_spend_usd=prior_reserved_cost + development_reserved,
        auto_recharge_enabled=False,
    )


def _authorization() -> AuthorizationState:
    return AuthorizationState(
        stage_0_enabled=True,
        development_enabled=True,
        confirmatory_enabled=False,
        external_calls_enabled=True,
        openai_calls_enabled=True,
        embedding_calls_enabled=False,
        bedrock_inference_enabled=False,
    )


def _attempt_record(
    ledger: AttemptLedger,
    prepared: PreparedDevelopmentRequest,
    *,
    usage: Usage | None,
    received_candidate: bool,
    failure_class: str | None,
    http_status: int | None,
    prior_reserved_cost: Decimal = Decimal("0"),
) -> AttemptRecord:
    input_cap = 512 if prepared.arm_id == "A" else 3_072 if prepared.arm_id == "ORACLE-GOLD" else 4_608
    reservation = validate_pre_dispatch(
        DispatchRequest(
            phase=Phase.DEVELOPMENT,
            operation="openai_generation",
            arm_id=prepared.arm_id,
            input_token_ceiling=input_cap,
            output_token_ceiling=256,
            attempt_ordinal=1,
            step_id=prepared.step.step_id,
        ),
        authorization=_authorization(),
        snapshot=_snapshot(ledger, prior_reserved_cost=prior_reserved_cost),
        ledger=ledger,
    )
    return AttemptRecord(
        step_id=prepared.step.step_id,
        arm_id=prepared.arm_id,
        phase=Phase.DEVELOPMENT,
        attempt_ordinal=1,
        parent_attempt_id=None,
        failure_class=failure_class,
        request_parameter_hash=prepared.request_parameter_hash,
        reported_usage_or_null=usage,
        reserved_worst_case_cost=reservation.worst_case_cost_usd,
        reserved_input_tokens=input_cap,
        reserved_output_tokens=256,
        response_token_or_candidate_received=received_candidate,
        http_status=http_status,
    )


def _ledger_row(record: AttemptRecord) -> dict[str, object]:
    return {
        "attempt_id": record.attempt_id,
        "step_id": record.step_id,
        "arm_id": record.arm_id,
        "phase": record.phase.value,
        "attempt_ordinal": record.attempt_ordinal,
        "parent_attempt_id": record.parent_attempt_id,
        "failure_class": record.failure_class,
        "http_status": record.http_status,
        "request_parameter_hash": record.request_parameter_hash,
        "reserved_worst_case_cost_usd": str(record.reserved_worst_case_cost),
        "reserved_input_tokens": record.reserved_input_tokens,
        "reserved_output_tokens": record.reserved_output_tokens,
        "reported_usage_or_null": (
            None
            if record.reported_usage_or_null is None
            else asdict(record.reported_usage_or_null)
        ),
        "response_token_or_candidate_received": record.response_token_or_candidate_received,
    }


def _reserve_before_dispatch(
    ledger: AttemptLedger,
    ledger_rows: list[dict[str, object]],
    ledger_path: Path,
    prepared: PreparedDevelopmentRequest,
    *,
    prior_reserved_cost: Decimal = Decimal("0"),
) -> AttemptRecord:
    """Persist a validated reservation before the provider transport is reachable."""

    record = _attempt_record(
        ledger,
        prepared,
        usage=None,
        received_candidate=False,
        failure_class=None,
        http_status=None,
        prior_reserved_cost=prior_reserved_cost,
    )
    ledger.append(record)
    ledger_rows.append(_ledger_row(record))
    _atomic_jsonl(ledger_path, ledger_rows)
    return record


def _finalize_attempt(
    ledger: AttemptLedger,
    ledger_rows: list[dict[str, object]],
    ledger_path: Path,
    record: AttemptRecord,
    *,
    usage: Usage | None,
    received_candidate: bool,
    failure_class: str | None,
    http_status: int | None,
) -> AttemptRecord:
    """Replace the persisted reservation with its immutable completed outcome."""

    if not ledger.records or ledger.records[-1].attempt_id != record.attempt_id:
        raise DevelopmentRunError("attempt outcome does not match the pre-dispatch reservation")
    finalized = replace(
        record,
        reported_usage_or_null=usage,
        response_token_or_candidate_received=received_candidate,
        failure_class=failure_class,
        http_status=http_status,
    )
    ledger.records[-1] = finalized
    try:
        ledger.validate_integrity()
    except Exception:
        ledger.records[-1] = record
        raise
    ledger_rows[-1] = _ledger_row(finalized)
    _atomic_jsonl(ledger_path, ledger_rows)
    return finalized


def execute(
    output_dir: Path,
    cache_dir: Path,
    *,
    amended: bool = False,
    replacement: bool = False,
) -> dict[str, object]:
    """Generate the development split and perform its single permitted 256-call pass."""

    if output_dir.exists():
        if any(output_dir.iterdir()):
            raise DevelopmentRunError("development output directory is non-empty; reruns are prohibited")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
    encoding = load_offline_encoding(cache_dir)
    dataset = build_development_dataset(encoding)
    if amended and replacement:
        raise DevelopmentRunError("amended and replacement modes are mutually exclusive")
    prepared = (
        build_amended_development_requests(encoding, dataset)
        if amended or replacement
        else build_development_requests(encoding, dataset)
    )
    expected_attempts = AMENDED_DEVELOPMENT_REQUESTS if amended or replacement else DEVELOPMENT_REQUESTS
    if len(prepared) != expected_attempts:
        raise DevelopmentRunError("prepared development request count does not match the registered stage")
    prior_reserved_cost = (
        Decimal("0.2703360")
        if replacement
        else Decimal("0.1622016")
        if amended
        else Decimal("0")
    )
    if amended or replacement:
        historical = ORQ_DIR / "development" / "attempt-ledger.jsonl"
        if not historical.exists() or hashlib.sha256(historical.read_bytes()).hexdigest() != "896522a6b35c3cab71787e584c24b67284ee0cbf0e592be3fc1aae960508563a":
            raise DevelopmentRunError("frozen prior development ledger is unavailable or mismatched")
    dataset_digest = write_development_dataset(output_dir / "development-dataset.json", dataset)
    _atomic_json(output_dir / "run-registration.json", {
        "orq": "ORQ-30",
        "phase": "development_replacement" if replacement else "development_amended" if amended else "development",
        "model": MODEL,
        "temperature": 0,
        "top_p": 1,
        "response_format": "json_object",
        "attempts_planned": expected_attempts,
        "retries_allowed": 0,
        "reported_balance_usd": "3.85",
        "auto_recharge_enabled": False,
        "dataset_sha256": dataset_digest,
        "prior_development_reserved_cost_usd": str(prior_reserved_cost),
        "arms": list(AMENDED_DEVELOPMENT_ARMS if amended or replacement else ("A", "B", "E-BM25", "ORACLE-GOLD")),
    })

    ledger = AttemptLedger()
    results: list[dict[str, object]] = []
    ledger_rows: list[dict[str, object]] = []
    for prepared_request in prepared:
        started = time.perf_counter()
        content: str | None = None
        usage: Usage | None = None
        status: int | None = None
        failure_class: str | None = None
        try:
            record = _reserve_before_dispatch(
                ledger,
                ledger_rows,
                output_dir / "attempt-ledger.jsonl",
                prepared_request,
                prior_reserved_cost=prior_reserved_cost,
            )
            with urlopen(
                _request(prepared_request, _require_configured_api_key()),
                timeout=60,
            ) as response:
                status = response.status
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                failure_class = "provider_payload_invalid"
            else:
                content, usage = _extract_response(payload)
                if content is None:
                    failure_class = "provider_content_missing"
        except HTTPError as exc:
            status = exc.code
            failure_class = "http_error"
        except URLError:
            failure_class = "transport_error"
        except (UnicodeError, json.JSONDecodeError):
            failure_class = "provider_payload_invalid"
        latency_ms = round((time.perf_counter() - started) * 1_000, 3)
        record = _finalize_attempt(
            ledger,
            ledger_rows,
            output_dir / "attempt-ledger.jsonl",
            record,
            usage=usage,
            received_candidate=content is not None,
            failure_class=failure_class,
            http_status=status,
        )
        score = score_response(content if content is not None else b"", prepared_request.step.gold_atoms)
        results.append({
            "conversation_index": prepared_request.conversation_index,
            "step_id": prepared_request.step.step_id,
            "step_type": prepared_request.step.step_type,
            "arm_id": prepared_request.arm_id,
            "request_parameter_hash": prepared_request.request_parameter_hash,
            "candidate_or_null": content,
            "score": asdict(score),
            "latency_ms": latency_ms,
            "ttft_ms_or_null": None,
        })
        _atomic_jsonl(output_dir / "attempt-ledger.jsonl", ledger_rows)
        _atomic_jsonl(output_dir / "results.jsonl", results)
        if failure_class is not None:
            _atomic_json(output_dir / "run-summary.json", {
                "state": "DEVELOPMENT_INCOMPLETE",
                "failure_class": failure_class,
                "attempts_recorded": len(ledger.records),
                "retries_used": 0,
                "dataset_sha256": dataset_digest,
            })
            raise DevelopmentRunError("development attempt failed; continuation is prohibited")

    correct = sum(bool(row["score"]["correct"]) for row in results)  # type: ignore[index]
    summary = {
        "state": "DEVELOPMENT_COMPLETE",
        "run_kind": "replacement_b_e_bm25" if replacement else "amended_b_e_bm25" if amended else "original",
        "attempts_recorded": len(ledger.records),
        "retries_used": 0,
        "dataset_sha256": dataset_digest,
        "correct_answers": correct,
        "scored_answers": len(results),
        "reserved_cost_usd": str(sum((record.reserved_worst_case_cost for record in ledger.records), start=Decimal("0"))),
    }
    _atomic_json(output_dir / "run-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="perform the one permitted development run")
    parser.add_argument("--amended", action="store_true", help="run the separately authorized 128-attempt B/E-BM25 amendment pass")
    parser.add_argument("--replacement", action="store_true", help="run the separately authorized replacement B/E-BM25 pass")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("refusing to dispatch without --execute")
    try:
        output_dir = args.output_dir or (REPLACEMENT_OUTPUT_DIR if args.replacement else AMENDED_OUTPUT_DIR if args.amended else DEFAULT_OUTPUT_DIR)
        summary = execute(output_dir.resolve(), args.cache_dir.resolve(), amended=args.amended, replacement=args.replacement)
    except DevelopmentRunError as exc:
        raise SystemExit(f"DEVELOPMENT_BLOCKED: {exc}") from exc
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
    build_amended_development_requests,
