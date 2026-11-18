"""Best-effort, request-local routing evidence; no content or raw errors."""
from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Any

from app.core.utils.costs import PRICE_SNAPSHOT_DATE, estimate_generation_cost_usd

logger = logging.getLogger(__name__)


def _clock() -> float | None:
    try:
        return time.monotonic()
    except Exception:
        return None


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SECRET_MARKERS = re.compile(r"(?i)(?:secret|password|credential|api[-_]?key|bearer|token|(?:^|[/:-])sk[-_]|AKIA[0-9A-Z]{12})")
_LONG_OPAQUE = re.compile(r"[A-Za-z0-9]{40,}")
_REASONS = frozenset({"static_default", "heuristic_stream_safe", "heuristic_primary_unavailable", "heuristic_message_length_cheap", "heuristic_estimated_tokens_smart", "heuristic_default", "deterministic_default_eligible", "deterministic_capacity_alternative"})
_FAILURE_KINDS = frozenset({"timeout", "network", "auth", "rate_limit", "bad_request", "upstream", "unknown"})


def _identifier(value: Any) -> str | None:
    if (not isinstance(value, str) or not _IDENTIFIER.fullmatch(value)
            or _SECRET_MARKERS.search(value) or _LONG_OPAQUE.search(value)):
        return None
    return value


def _failure_kind(status: str, error: BaseException | None) -> str | None:
    if status == "success":
        return None
    if status in {"cancelled", "timeout"}:
        return status
    from app.core.domain.provider_errors import ProviderError
    if isinstance(error, ProviderError):
        kind = getattr(error.kind, "value", None)
        if kind in _FAILURE_KINDS:
            return kind
    return "unknown"


def _token_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _emit(payload: dict[str, Any]) -> None:
    try:
        logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False), extra={"event": payload["event"]})
    except Exception:
        pass


class RoutingEvidence:
    """One invocation's observation; never shared between requests."""

    def __init__(self, decision=None, fallback_known: bool = False):
        self.decision = decision
        self.fallback_used: bool | None = False if fallback_known else None
        self.started = _clock()
        self.attempted = False
        self.emitted = False

    def fallback_dispatched(self) -> None:
        self.fallback_used = True

    def terminal(self, *, request_id, stream: bool, status: str, result=None, error: BaseException | None = None) -> None:
        if self.emitted:
            return
        self.emitted = True
        try:
            now = _clock()
            elapsed = None
            if now is not None and self.started is not None:
                delta = (now - self.started) * 1000
                if math.isfinite(delta) and delta >= 0:
                    elapsed = int(delta)
            decision = self.decision
            success = status == "success" and result is not None
            provider = _identifier(result.provider) if success else None
            model = _identifier(result.model_version) if success else None
            trusted_pairs = set()
            if decision is not None:
                for provider_attr, model_attr in (("provider", "model"), ("fallback_provider", "fallback_model")):
                    configured_provider = _identifier(getattr(decision, provider_attr, None))
                    configured_model = _identifier(getattr(decision, model_attr, None))
                    if configured_provider is not None and configured_model is not None:
                        trusted_pairs.add((configured_provider, configured_model))
            if (provider, model) not in trusted_pairs:
                provider = model = None
            it = _token_count(result.input_tokens) if success else None
            ot = _token_count(result.output_tokens) if success else None
            total = _token_count(result.total_tokens) if success else None
            cost = None
            if (success and provider is not None and model is not None
                    and type(it) is int and it >= 0 and type(ot) is int and ot >= 0):
                try:
                    cost = estimate_generation_cost_usd(provider=provider, model=model, input_tokens=it, output_tokens=ot)
                except Exception:
                    pass
            if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
                cost = None
            _emit({
                "event": "routing.evidence", "version": 1, "request_id": str(request_id),
                "status": status, "failure_kind": _failure_kind(status, error), "stream": stream, "cache_hit": False,
                "generation_attempted": self.attempted,
                "inference_performed": True if success else None,
                "selected_provider": _identifier(getattr(decision, "provider", None)),
                "selected_model": _identifier(getattr(decision, "model", None)),
                "policy": _identifier(getattr(decision, "policy_name", None)),
                "policy_version": _identifier(getattr(decision, "policy_version", None)),
                "reason": decision.rationale if decision and decision.rationale in _REASONS else None,
                "final_provider": provider, "final_model": model,
                "generation_fallback": self.fallback_used,
                "input_tokens": it, "output_tokens": ot, "total_tokens": total,
                "provider_latency_ms": _token_count(result.latency_ms) if success else None,
                "service_elapsed_ms": elapsed, "elapsed_scope": "service_generation" if elapsed is not None else None,
                "final_generation_estimated_cost_usd": cost,
                "price_snapshot_date": PRICE_SNAPSHOT_DATE if cost is not None else None,
                "cost_scope": "final_generation_only" if cost is not None else None,
                "request_total_cost_usd": None,
            })
        except Exception:
            pass


def emit_cache_hit_evidence(*, request_id, source_result) -> None:
    try:
        _emit({
            "event": "routing.evidence", "version": 1, "request_id": str(request_id),
            "status": "success", "failure_kind": None, "stream": False, "cache_hit": True,
            "generation_attempted": False, "inference_performed": False,
            "selected_provider": None, "selected_model": None, "policy": None,
            "policy_version": None, "reason": None, "final_provider": None,
            "final_model": None, "generation_fallback": None, "input_tokens": None,
            "output_tokens": None, "total_tokens": None, "provider_latency_ms": None,
            "service_elapsed_ms": None, "elapsed_scope": None, "final_generation_estimated_cost_usd": None,
            "price_snapshot_date": None, "cost_scope": None, "request_total_cost_usd": None,
        })
    except Exception:
        pass
