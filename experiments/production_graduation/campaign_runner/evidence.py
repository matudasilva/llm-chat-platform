"""Parse existing text logging. Provider call counts never determine S2."""
import re
from dataclasses import dataclass, field
from uuid import UUID

BEDROCK = "app.core.providers.bedrock_provider"
PIPELINE = "app.core.domain.retrieval_pipeline"
EVENT = "retrieval_pipeline.evaluator_triggered"
RETRY_LOGGER = "app.core.observability.retry_evidence"
SUMMARY = "campaign.retry_summary"
COMPLETION = "retrieval_pipeline.completed"
LINE = re.compile(
    r"^(?:\d{4}-\d\d-\d\dT\S+\s+)?"
    r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4} "
    r"(DEBUG|INFO|WARNING|ERROR|CRITICAL) ([\w.]+) (.*?) tenant_id=([\w-]+)$"
)


@dataclass
class Evidence:
    retry: bool = False
    evaluator: bool = False
    reasons: list[str] = field(default_factory=list)


def parse(lines: list[str], request_id: str, *, complete: bool) -> Evidence:
    result = Evidence()
    summaries = 0
    announced = None
    provider_error = False
    completed = activation = 0
    evaluator_failed = False
    completion_evaluator = None
    if not complete:
        result.reasons.append("INCOMPLETE_LOG_WINDOW")
    for line in lines:
        match = LINE.fullmatch(line)
        if not match:
            # Skip non-evidence lines (tracebacks, JSON access logs, uvicorn output).
            # Only matching lines carry provider/pipeline evidence. Failing on every
            # benign line produces false UNPARSEABLE_LOG_WINDOW that kills the campaign.
            continue
        level, logger, message, _ = match.groups()
        # retry_summary is emitted by the middleware after request completion,
        # so Bedrock/Pipeline events naturally precede it. The "after" check
        # was a false constraint that killed valid campaign requests.
        if message.startswith(SUMMARY):
            summaries += 1
            receipt = re.fullmatch(
                re.escape(SUMMARY) + r" request_id=(\S+) retry_announced=(true|false) evidence_valid=true",
                message,
            )
            if (not receipt or receipt[1] != request_id or logger != RETRY_LOGGER
                    or level != "INFO"):
                if receipt and receipt[1] != request_id:
                    # Skip retry_summary for different request (e.g. health checks)
                    summaries -= 1
                    continue
                result.reasons.append("INVALID_RETRY_SUMMARY")
            else:
                try:
                    if str(UUID(receipt[1])) != receipt[1]:
                        raise ValueError()
                    announced = receipt[2] == "true"
                except ValueError:
                    result.reasons.append("INVALID_RETRY_SUMMARY")
        if logger == BEDROCK and message == "provider.error":
            provider_error = True
        if message.startswith("provider.retry") and (logger != BEDROCK or message != "provider.retry"):
            result.reasons.append("AMBIGUOUS_RETRY_EVENT")
        if message.startswith(EVENT) and logger != PIPELINE:
            result.reasons.append("AMBIGUOUS_ACTIVATION_LOGGER")
        if message.startswith(COMPLETION) and logger != PIPELINE:
            result.reasons.append("AMBIGUOUS_COMPLETION_LOGGER")
        if logger == BEDROCK and message == "provider.retry":
            result.retry = True
            if level != "INFO":
                result.reasons.append("INVALID_RETRY_LEVEL")
        if logger == PIPELINE:
            if message.startswith(EVENT):
                activation += 1
                if completed:
                    result.reasons.append("ACTIVATION_AFTER_PIPELINE_COMPLETION")
                try:
                    value = message.removeprefix(EVENT + " request_id=")
                    if str(UUID(value)) != value or value != request_id or level != "INFO":
                        raise ValueError("Mismatched activation")
                    result.evaluator = True
                except ValueError:
                    result.reasons.append("INVALID_ACTIVATION_IDENTITY")
            elif message.startswith(COMPLETION):
                completed += 1
                receipt = re.fullmatch(
                    re.escape(COMPLETION) + r" request_id=(\S+) evaluator_triggered=(true|false)",
                    message,
                )
                if (not receipt or receipt[1] != request_id or level != "INFO"):
                    result.reasons.append("INVALID_COMPLETION_IDENTITY")
                else:
                    completion_evaluator = receipt[2] == "true"
            elif message == "retrieval_pipeline.evaluator_failed":
                if completed:
                    result.reasons.append("FAILURE_AFTER_COMPLETION")
                if evaluator_failed:
                    result.reasons.append("DUPLICATE_EVALUATOR_FAILURE")
                evaluator_failed = True
                if not result.evaluator:
                    result.reasons.append("FAILURE_BEFORE_ACTIVATION")
            elif message == "retrieval_pipeline.rewrite_failed":
                result.reasons.append("REWRITE_FAILED")
        if logger == "app.core.domain.rag_generation" and message == "chat_rag.degraded":
            result.reasons.append("RETRIEVAL_DEGRADED")
        if logger == BEDROCK and message == "provider.stream.error":
            result.reasons.append("STREAM_ERROR")
    if summaries != 1:
        result.reasons.append("MISSING_OR_DUPLICATE_RETRY_SUMMARY")
    if announced is not None and announced != result.retry:
        result.reasons.append("CONTRADICTORY_RETRY_SUMMARY")
    if provider_error and not result.retry:
        result.reasons.append("PROVIDER_ERROR_WITHOUT_RETRY")
    if activation > 1:
        result.reasons.append("DUPLICATE_ACTIVATION")
    if completed != 1:
        result.reasons.append("MISSING_OR_DUPLICATE_COMPLETION")
    if completion_evaluator is True and not result.evaluator:
        result.reasons.append("MISSING_ACTIVATION")
    if completion_evaluator is False and result.evaluator:
        result.reasons.append("CONTRADICTORY_ACTIVATION")
    if evaluator_failed and not result.evaluator:
        result.reasons.append("EVALUATOR_FAILURE_WITHOUT_ACTIVATION")
    return result
