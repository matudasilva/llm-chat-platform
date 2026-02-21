from __future__ import annotations

import asyncio
import logging
from typing import Sequence
from uuid import UUID

from .types import ChatMessage
from .chat_types import ChatServiceResult
from .provider import ProviderInput, ProviderPort
from .errors import ProviderTimeoutError, ProviderExecutionError
from .provider_errors import ProviderError, ProviderErrorKind

logger = logging.getLogger(__name__)


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
            # Internal diagnostics: full stacktrace in logs, sanitized error outward.
            logger.exception(
                "provider_timeout request_id=%s provider=%s messages_count=%d timeout_s=%.3f",
                str(request_id),
                type(self._provider).__name__,
                len(messages),
                float(self._timeout_s),
            )
            raise ProviderTimeoutError("provider timeout") from e

        except ProviderError as e:
            # Provider already normalized the failure; keep outward message safe and short.
            logger.exception(
                "provider_error request_id=%s provider=%s kind=%s messages_count=%d",
                str(request_id),
                type(self._provider).__name__,
                getattr(e.kind, "value", str(e.kind)),
                len(messages),
            )
            if e.kind == ProviderErrorKind.timeout:
                raise ProviderTimeoutError("provider timeout") from e
            raise ProviderExecutionError(str(e)) from e

        except Exception as e:
            # Keep provider internals out of the boundary. Details belong in logs.
            logger.exception(
                "provider_execution_error request_id=%s provider=%s messages_count=%d",
                str(request_id),
                type(self._provider).__name__,
                len(messages),
            )
            raise ProviderExecutionError("provider execution failed") from e

        assistant = ChatMessage(role="assistant", content=provider_out.content)

        return ChatServiceResult(
            request_id=request_id,
            assistant_message=assistant,
            provider_result=provider_out,
        )
