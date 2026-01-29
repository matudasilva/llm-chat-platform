from __future__ import annotations

from typing import Sequence
from uuid import UUID

from .types import ChatMessage
from .chat_types import ChatServiceResult
from .provider import ProviderInput, ProviderPort


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
