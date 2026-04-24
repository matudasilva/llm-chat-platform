from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.domain.provider import ProviderPort
from app.core.domain.disabled_provider import DisabledProvider
from app.core.domain.routing.heuristic_routing_policy import HeuristicRoutingPolicy
from app.core.domain.routing.routing_policy import RoutingPolicy
from app.core.domain.routing.routing_types import RoutingContext, RoutingDecision
from app.core.domain.routing.static_routing_policy import StaticRoutingPolicy
from app.core.providers.bedrock_provider import BedrockProvider, BedrockProviderConfig
from app.core.providers.resilient_provider import ResilientProvider
from app.core.providers.stub_provider import StubProvider
from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig
from app.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedProvider:
    provider: ProviderPort
    decision: RoutingDecision


ProviderResolver = Callable[[RoutingContext], ResolvedProvider]


def build_provider(_settings=None) -> ProviderPort:
    cfg = _settings or settings
    primary_name = cfg.provider.lower()
    primary = _build_single_provider(primary_name, cfg)

    fallback_name = getattr(cfg, "fallback_provider", None)
    if not isinstance(fallback_name, str) or not fallback_name.strip():
        return primary

    fallback_name = fallback_name.lower()
    if fallback_name == primary_name:
        return primary

    fallback = _build_single_provider(fallback_name, cfg)
    return ResilientProvider(primary=primary, fallback=fallback)


def build_routing_policy(_settings=None) -> RoutingPolicy:
    cfg = _settings or settings
    return _build_named_routing_policy(cfg, cfg.routing_policy)


def _build_named_routing_policy(cfg, policy_name: str) -> RoutingPolicy:
    primary_name = cfg.provider.lower()
    fallback_name = getattr(cfg, "fallback_provider", None)
    fallback_name = fallback_name.lower() if isinstance(fallback_name, str) and fallback_name.strip() else None
    primary_model = _model_for_provider(primary_name, cfg)
    fallback_model = _model_for_provider(fallback_name, cfg) if fallback_name else None

    if policy_name == "heuristic":
        return HeuristicRoutingPolicy(
            primary_provider=primary_name,
            primary_model=primary_model,
            fallback_provider=fallback_name,
            fallback_model=fallback_model,
            message_length_cheap_max=cfg.routing_message_length_cheap_max,
            estimated_tokens_smart_min=cfg.routing_estimated_tokens_smart_min,
        )

    return StaticRoutingPolicy(
        provider=primary_name,
        model=primary_model,
        fallback_provider=fallback_name,
        fallback_model=fallback_model,
    )


def build_provider_resolver(_settings=None) -> ProviderResolver:
    cfg = _settings or settings
    policy = build_routing_policy(cfg)
    shadow_policy = _build_shadow_policy(cfg)

    def _resolve(context: RoutingContext) -> ResolvedProvider:
        decision = policy.decide(context)
        _log_routing_decision(context=context, decision=decision)
        _maybe_log_shadow_divergence(cfg=cfg, context=context, active_decision=decision, shadow_policy=shadow_policy)
        provider = build_provider_for_decision(cfg, decision)
        return ResolvedProvider(provider=provider, decision=decision)

    return _resolve


def build_provider_for_decision(cfg, decision: RoutingDecision) -> ProviderPort:
    primary = _build_single_provider(decision.provider, cfg, model_override=decision.model)

    fallback_name = decision.fallback_provider
    if not isinstance(fallback_name, str) or not fallback_name.strip():
        return primary

    fallback_name = fallback_name.lower()
    if fallback_name == decision.provider:
        return primary

    fallback = _build_single_provider(
        fallback_name,
        cfg,
        model_override=decision.fallback_model,
    )
    return ResilientProvider(primary=primary, fallback=fallback)


def _build_single_provider(provider: str, cfg, *, model_override: str | None = None) -> ProviderPort:
    if provider == "stub":
        return StubProvider(
            mode=cfg.stub_provider_mode,
            simulated_latency_ms=cfg.stub_simulated_latency_ms,
        )

    if provider == "openai":
        if not cfg.openai_api_key:
            return DisabledProvider("openai", "OPENAI_API_KEY missing")

        openai_cfg = OpenAIProviderConfig(
            api_key=cfg.openai_api_key,
            model=model_override or cfg.openai_model,
            timeout_s=cfg.provider_timeout_s,
            max_attempts=cfg.openai_max_attempts,
            backoff_base_ms=cfg.openai_backoff_base_ms,
            backoff_max_ms=cfg.openai_backoff_max_ms,
        )
        return OpenAIProvider(openai_cfg)

    if provider == "bedrock":
        if not cfg.bedrock_region:
            return DisabledProvider("bedrock", "BEDROCK_REGION missing")
        if not cfg.bedrock_model:
            return DisabledProvider("bedrock", "BEDROCK_MODEL missing")

        bedrock_cfg = BedrockProviderConfig(
            region=cfg.bedrock_region,
            model=model_override or cfg.bedrock_model,
            prompt_version=cfg.bedrock_prompt_version,
            timeout_s=cfg.provider_timeout_s,
            max_attempts=cfg.bedrock_max_attempts,
            backoff_base_ms=cfg.bedrock_backoff_base_ms,
            backoff_max_ms=cfg.bedrock_backoff_max_ms,
            aws_access_key_id=cfg.aws_access_key_id,
            aws_secret_access_key=cfg.aws_secret_access_key,
            aws_session_token=cfg.aws_session_token,
        )
        return BedrockProvider(bedrock_cfg)

    raise ValueError(f"Unsupported provider: {provider}")


def _model_for_provider(provider: str | None, cfg) -> str | None:
    if provider == "openai":
        return cfg.openai_model
    if provider == "bedrock":
        return cfg.bedrock_model
    return None


def _log_routing_decision(*, context: RoutingContext, decision: RoutingDecision) -> None:
    logger.info(
        "routing.decision",
        extra={
            "event": "routing.decision",
            "request_id": context.request_id,
            "policy_name": decision.policy_name,
            "policy_version": decision.policy_version,
            "provider": decision.provider,
            "model": decision.model,
            "model_tier": decision.model_tier,
            "fallback_provider": decision.fallback_provider,
            "rationale": decision.rationale,
            "stream": context.stream,
            "message_length": context.message_length,
            "estimated_tokens": context.estimated_tokens,
            "primary_provider_available": context.primary_provider_available,
        },
    )


def _build_shadow_policy(cfg) -> RoutingPolicy | None:
    if not getattr(cfg, "routing_shadow_mode_enabled", False):
        return None

    shadow_policy_name = getattr(cfg, "routing_shadow_policy", None)
    if not shadow_policy_name:
        shadow_policy_name = "heuristic" if cfg.routing_policy == "static" else "static"

    if shadow_policy_name == cfg.routing_policy:
        return None

    return _build_named_routing_policy(cfg, shadow_policy_name)


def _maybe_log_shadow_divergence(*, cfg, context: RoutingContext, active_decision: RoutingDecision, shadow_policy: RoutingPolicy | None) -> None:
    if shadow_policy is None:
        return

    timeout_ms = cfg.routing_shadow_timeout_ms
    started_at = time.monotonic()

    try:
        shadow_decision = shadow_policy.decide(context)
    except Exception:
        logger.warning(
            "routing.shadow_error",
            extra={
                "event": "routing.shadow_error",
                "request_id": context.request_id,
                "shadow_policy_name": getattr(shadow_policy, "__class__", type(shadow_policy)).__name__,
            },
            exc_info=True,
        )
        return

    elapsed_ms = (time.monotonic() - started_at) * 1000.0
    if elapsed_ms > timeout_ms:
        logger.warning(
            "routing.shadow_timeout",
            extra={
                "event": "routing.shadow_timeout",
                "request_id": context.request_id,
                "shadow_elapsed_ms": round(elapsed_ms, 3),
                "shadow_timeout_ms": timeout_ms,
            },
        )
        return

    if not _decisions_diverge(active_decision, shadow_decision):
        return

    logger.info(
        "routing.shadow_divergence",
        extra={
            "event": "routing.shadow_divergence",
            "request_id": context.request_id,
            "active_policy_name": active_decision.policy_name,
            "active_policy_version": active_decision.policy_version,
            "active_provider": active_decision.provider,
            "active_model_tier": active_decision.model_tier,
            "shadow_policy_name": shadow_decision.policy_name,
            "shadow_policy_version": shadow_decision.policy_version,
            "shadow_provider": shadow_decision.provider,
            "shadow_model_tier": shadow_decision.model_tier,
            "shadow_elapsed_ms": round(elapsed_ms, 3),
        },
    )


def _decisions_diverge(active_decision: RoutingDecision, shadow_decision: RoutingDecision) -> bool:
    return (
        active_decision.provider != shadow_decision.provider
        or active_decision.model != shadow_decision.model
        or active_decision.model_tier != shadow_decision.model_tier
        or active_decision.fallback_provider != shadow_decision.fallback_provider
        or active_decision.fallback_model != shadow_decision.fallback_model
    )
