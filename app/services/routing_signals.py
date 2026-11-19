from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_prompt import (
    preview_messages_for_provider, _validated_memory_events, _validated_sources,
)
from app.core.domain.routing.routing_types import EnvelopeSignals, RoutingContext
from app.core.domain.types import ChatMessage


def build_routing_context_builder(settings, *, observe_envelope: bool = False):
    def _build(*, provider_input: ProviderInput, stream: bool) -> RoutingContext:
        messages = provider_input.messages
        last_user_message = _last_user_message(messages)
        message_length = len(last_user_message)
        return RoutingContext(
            request_id=provider_input.request_id,
            stream=stream,
            message_length=message_length,
            estimated_tokens=_estimate_tokens(last_user_message),
            primary_provider_available=_is_provider_available(settings.provider, settings),
            envelope=_observe_envelope(provider_input, stream) if observe_envelope else None,
        )

    return _build


def _last_user_message(messages: Sequence[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return messages[-1].content if messages else ""


def _estimate_tokens(message_text: str) -> int:
    # Best-effort, provider-agnostic proxy used only for routing heuristics.
    # It does not represent exact tokenization for any concrete provider.
    stripped = message_text.strip()
    if not stripped:
        return 0
    return max(1, (len(stripped) + 3) // 4)


def _is_provider_available(provider: str, settings) -> bool:
    provider_name = provider.lower()
    if provider_name == "stub":
        return True
    if provider_name == "openai":
        return bool(settings.openai_api_key)
    if provider_name == "bedrock":
        return bool(settings.bedrock_region and settings.bedrock_model)
    return False


def _observe_envelope(provider_input: ProviderInput, stream: bool) -> EnvelopeSignals:
    messages = preview_messages_for_provider(provider_input)
    identity = {
        "messages": [(message.role, message.content) for message in messages],
        "temperature": provider_input.temperature,
        "max_tokens": provider_input.max_tokens,
        "stream": stream,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":"),
                   sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    return EnvelopeSignals(
        character_count=sum(len(message.content) for message in messages),
        utf8_bytes=sum(len(message.content.encode("utf-8")) for message in messages),
        message_count=len(messages),
        has_history=len(provider_input.messages) > 1,
        has_memory=_validated_memory_events(provider_input.metadata) is not None,
        has_rag=_validated_sources(provider_input.metadata) is not None,
        requested_output=provider_input.max_tokens,
        fingerprint=fingerprint,
        stream=stream,
    )
