from __future__ import annotations

import asyncio
from typing import Sequence
from uuid import UUID

from .types import ChatMessage
from .chat_types import ChatServiceResult
from .provider import ProviderInput, ProviderPort
from .errors import ProviderTimeoutError, ProviderExecutionError


class ChatService:
    """
    Pure orchestration service.

    Rules:
    - No DB access
    - No transactions
    - No FastAPI/HTTP semantics
    """

    def __init__(self, provider: ProviderPort, *, timeout_s: float) -> None:
        self._provider = provider
        self._timeout_s = timeout_s

    async def run(self, *, request_id: UUID, messages: Sequence[ChatMessage]) -> ChatServiceResult:
        provider_in = ProviderInput(
            request_id=request_id,
            messages=messages,
        )

        try:
            provider_out = await asyncio.wait_for(
                self._provider.generate(provider_in),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError as e:
            raise ProviderTimeoutError("provider timeout") from e
        except Exception as e:
            # Keep provider internals out of the boundary. Details belong in logs.
            raise ProviderExecutionError("provider execution failed") from e

        assistant = ChatMessage(role="assistant", content=provider_out.content)

        return ChatServiceResult(
            request_id=request_id,
            assistant_message=assistant,
            provider_result=provider_out,
        )
