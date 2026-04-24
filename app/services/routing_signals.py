from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.core.domain.routing.routing_types import RoutingContext
from app.core.domain.types import ChatMessage


def build_routing_context_builder(settings):
    def _build(*, request_id: UUID, messages: Sequence[ChatMessage], stream: bool) -> RoutingContext:
        last_user_message = _last_user_message(messages)
        message_length = len(last_user_message)
        return RoutingContext(
            request_id=request_id,
            stream=stream,
            message_length=message_length,
            estimated_tokens=_estimate_tokens(last_user_message),
            primary_provider_available=_is_provider_available(settings.provider, settings),
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
