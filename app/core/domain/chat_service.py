from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Sequence
from uuid import UUID

from .types import ChatMessage
from .chat_types import ChatServiceResult
from .provider import ProviderInput, ProviderPort, ProviderStreamResult
from .errors import ProviderTimeoutError, ProviderExecutionError
from .provider_errors import ProviderError, ProviderErrorKind


logger = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class StreamChatResult:
    request_id: UUID
    assistant_message: ChatMessage
    provider_result: ProviderStreamResult | None


@dataclass(frozen=True, slots=True)
class ChatServiceStreamSession:
    chunks: AsyncIterator[str]
    get_final_result: Callable[[], Awaitable[StreamChatResult]]

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

    async def stream_chat(
        self, *, request_id: UUID, messages: Sequence[ChatMessage]
    ) -> ChatServiceStreamSession:
        provider_in = ProviderInput(request_id=request_id, messages=messages)

        try:
            provider_session = await self._provider.stream(provider_in)
        except AttributeError:
            result = await self.run(request_id=request_id, messages=messages)

            async def fallback_chunks() -> AsyncIterator[str]:
                yield result.assistant_message.content

            async def fallback_final_result() -> StreamChatResult:
                return StreamChatResult(
                    request_id=request_id,
                    assistant_message=result.assistant_message,
                    provider_result=None,
                )

            return ChatServiceStreamSession(
                chunks=fallback_chunks(),
                get_final_result=fallback_final_result,
            )

        if provider_session is None:
            result = await self.run(request_id=request_id, messages=messages)

            async def fallback_chunks() -> AsyncIterator[str]:
                yield result.assistant_message.content

            async def fallback_final_result() -> StreamChatResult:
                return StreamChatResult(
                    request_id=request_id,
                    assistant_message=result.assistant_message,
                    provider_result=None,
                )

            return ChatServiceStreamSession(
                chunks=fallback_chunks(),
                get_final_result=fallback_final_result,
            )

        async def final_result() -> StreamChatResult:
            provider_stream_result = await provider_session.get_final_result()
            assistant = ChatMessage(
                role="assistant",
                content=provider_stream_result.content,
            )
            return StreamChatResult(
                request_id=request_id,
                assistant_message=assistant,
                provider_result=provider_stream_result,
            )

        return ChatServiceStreamSession(
            chunks=provider_session.chunks,
            get_final_result=final_result,
        )