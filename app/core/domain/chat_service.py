from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from .chat_types import ChatMessage
from .provider import ProviderInput, ProviderPort, ProviderResult


@dataclass(frozen=True, slots=True)
class ChatServiceResult:
    """
    Output of the DB-agnostic orchestration layer.

    It returns:
    - request_id: correlation id propagated end-to-end
    - assistant_message: what should be persisted as the assistant output message
    - provider_result: metadata/metrics needed to later emit a UsageEvent
    """
    request_id: UUID
    assistant_message: ChatMessage
    provider_result: ProviderResult


class ChatService:
    """
    Pure orchestration service.

    Rules:
    - No DB access
    - No transactions
    - No FastAPI/HTTP semantics
    """
    def __init__(self, provider: ProviderPort) -> None:
        self._provider = provider

    async def run(self, *, request_id: UUID, messages: Sequence[ChatMessage]) -> ChatServiceResult:
        provider_in = ProviderInput(
            request_id=request_id,
            messages=messages,
        )

        provider_out = await self._provider.generate(provider_in)
        assistant = ChatMessage(role="assistant", content=provider_out.content)

        return ChatServiceResult(
            request_id=request_id,
            assistant_message=assistant,
            provider_result=provider_out,
        )
