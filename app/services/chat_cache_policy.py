"""Configuration-only admission for the existing response cache."""
from __future__ import annotations

import hashlib
import json

from app.services.routing_signals import _is_provider_available

_CACHE_CONFIGURATION_FIELDS = (
    "provider", "fallback_provider", "openai_model", "bedrock_model",
    "bedrock_prompt_version", "bedrock_region", "stub_provider_mode", "routing_policy",
    "routing_message_length_cheap_max", "routing_estimated_tokens_smart_min",
)


def cache_configuration(cfg) -> dict:
    values = {name: getattr(cfg, name) for name in _CACHE_CONFIGURATION_FIELDS}
    # Bind the routing signal without including credential material or identity.
    values["primary_provider_available"] = _is_provider_available(cfg.provider, cfg)
    return values


def cache_bypass_reason(cfg) -> str | None:
    if cfg.chat_rag_augmentation_enabled:
        return "rag_augmentation"
    if cfg.ebm25_enabled:
        return "ebm25_memory"
    if cfg.routing_policy == "deterministic":
        return "routing_policy"
    if cfg.provider == "vertex" or cfg.fallback_provider == "vertex":
        return "provider_configuration"
    return None


def execution_configuration_id(cfg) -> str:
    # Match the existing cache-key configuration and add admission conditions.
    # No credentials, prompt content or provider request data are included.
    values = cache_configuration(cfg)
    values.update(
        chat_rag_augmentation_enabled=cfg.chat_rag_augmentation_enabled,
        ebm25_enabled=cfg.ebm25_enabled,
    )
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
