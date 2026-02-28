import json
import logging
import time
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_chat_service
from app.core.domain.chat_service import ChatService
from app.core.domain.errors import ProviderExecutionError, ProviderTimeoutError
from app.core.domain.types import ChatMessage
from app.core.settings import settings
from app.core.utils.limits import sanitize_error_message, truncate
from app.http.request_context import get_request_id
from app.infra.db.session import get_db
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.usage_event import UsageEvent
from app.schemas.chat import ChatRequest, ChatResponse, ChatStatus
from app.core.domain.provider_errors import ProviderError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

def _sse(event: str, data: str) -> str:
    # SSE format: event + data lines + blank line
    return f"event: {event}\ndata: {data}\n\n"


def _sse_json(event: str, payload: dict) -> str:
    return _sse(event, json.dumps(payload, separators=(",", ":")))

@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    start = time.perf_counter()
    rid = get_request_id()
    request_id = uuid.UUID(rid) if rid else uuid.uuid4()

    status = ChatStatus.error
    error_message: str | None = None
    is_new_conversation = payload.conversation_id is None
    conversation_id = payload.conversation_id or uuid.uuid4()
    user_message_id: uuid.UUID | None = None
    assistant_message_id: uuid.UUID | None = None
    assistant_content: str | None = None
    
    if getattr(payload, "stream", False):

        async def event_generator() -> AsyncIterator[str]:
            logger.info(
                "chat_streaming_start request_id=%s conversation_id=%s is_new=%s",
                str(request_id),
                str(conversation_id),
                str(is_new_conversation),
            )
            start_stream = time.perf_counter()
            chunks: list[str] = []

            try:
                # 1) Stream from provider (no DB, no transaction)
                async for chunk in chat_service.stream_chat(
                    request_id=request_id,
                    messages=[ChatMessage(role="user", content=payload.message)],
                ):
                    chunks.append(chunk)
                    yield _sse("token", chunk)

                # 2) Persist AFTER provider finishes (single atomic transaction)
                assistant_text = "".join(chunks)
                assistant_content_final = truncate(assistant_text, settings.MAX_ASSISTANT_CHARS)

                user_msg_id = uuid.uuid4()
                assistant_msg_id = uuid.uuid4()

                async with db.begin():
                    # Conversation: create or validate
                    if is_new_conversation:
                        conv = Conversation(id=conversation_id)
                        db.add(conv)
                        await db.flush()
                    else:
                        conv = await db.get(Conversation, conversation_id)
                        if conv is None:
                            yield _sse_json("error", {"error_kind": "not_found"})
                            return

                    # Persist user message
                    db.add(
                        Message(
                            id=user_msg_id,
                            conversation_id=conversation_id,
                            role=MessageRole.user,
                            content=payload.message,
                        )
                    )
                    await db.flush()

                    # Persist assistant message
                    db.add(
                        Message(
                            id=assistant_msg_id,
                            conversation_id=conversation_id,
                            role=MessageRole.assistant,
                            content=assistant_content_final,
                        )
                    )
                    await db.flush()

                    # Usage event best-effort (success)
                    latency_ms = max(0, int((time.perf_counter() - start_stream) * 1000))
                    try:
                        db.add(
                            UsageEvent(
                                id=uuid.uuid4(),
                                provider="stub",
                                model_version="local",
                                prompt_version="v0",
                                status=ChatStatus.success.value,
                                request_id=request_id,
                                latency_ms=latency_ms,
                                error_message=None,
                                conversation_id=None,
                                message_id=assistant_msg_id,
                                input_tokens=0,
                                output_tokens=0,
                                total_tokens=0,
                            )
                        )
                    except Exception:
                        pass

                # 3) Done
                yield _sse_json(
                    "done",
                    {
                        "request_id": str(request_id),
                        "conversation_id": str(conversation_id),
                        "user_message_id": str(user_msg_id),
                        "assistant_message_id": str(assistant_msg_id),
                        "status": "success",
                    },
                )

            except ProviderError as e:
                yield _sse_json(
                    "error",
                    {
                        "error_kind": getattr(e.kind, "value", str(e.kind)),
                        "retryable": bool(getattr(e, "retryable", False)),
                    },
                )
                return
            except Exception as e:
                logger.exception(
                    "chat_streaming_unhandled_error request_id=%s conversation_id=%s",
                    str(request_id),
                    str(conversation_id),
                )
                yield _sse_json("error", {"error_kind": "internal"})
                return

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    


    try:
        # Single transaction: either everything is persisted, or nothing is.
        async with db.begin():
            # 1) Conversation: create or validate
            if is_new_conversation:
                conv = Conversation(id=conversation_id)
                db.add(conv)
                await db.flush()
            else:
                conv = await db.get(Conversation, conversation_id)
                if conv is None:
                    raise HTTPException(status_code=404, detail="conversation_id not found")

            # 2) Persist user message
            user_msg = Message(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                role=MessageRole.user,
                content=payload.message,
            )
            db.add(user_msg)
            await db.flush()
            user_message_id = user_msg.id

            # 3) Execute model (via ChatService)
            service_result = await chat_service.run(
                request_id=request_id,
                messages=[ChatMessage(role="user", content=payload.message)],
            )

            assistant_content = truncate(
                service_result.assistant_message.content,
                settings.MAX_ASSISTANT_CHARS,
            )
            provider_result = service_result.provider_result

            # 4) Persist assistant message
            assistant_msg = Message(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                role=MessageRole.assistant,
                content=assistant_content,
            )
            db.add(assistant_msg)
            await db.flush()
            assistant_message_id = assistant_msg.id

            status = ChatStatus.success

            # 5) UsageEvent WITH valid FKs (best-effort)
            latency_ms = max(0, int((time.perf_counter() - start) * 1000))

            def _as_int_or_zero(v) -> int:
                try:
                    return max(0, int(v or 0))
                except Exception:
                    return 0

            input_tokens = _as_int_or_zero(provider_result.input_tokens)
            output_tokens = _as_int_or_zero(provider_result.output_tokens)
            total_tokens = _as_int_or_zero(provider_result.total_tokens)

            # Telemetry must never break the request.
            try:
                ev = UsageEvent(
                    id=uuid.uuid4(),
                    provider=provider_result.provider,
                    model_version=provider_result.model_version,
                    prompt_version=provider_result.prompt_version,
                    status=status.value,
                    request_id=request_id,
                    latency_ms=latency_ms,
                    error_message=None,
                    conversation_id=None,
                    message_id=assistant_message_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
                db.add(ev)
            except Exception:
                pass

        # commit OK (exit db.begin)
        return ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            assistant_content=assistant_content,
            status=status,
            error_message=None,
        )

    except HTTPException:
        raise

    except (ProviderTimeoutError, ProviderExecutionError) as e:
        error_message = sanitize_error_message(str(e), settings.MAX_ERROR_MESSAGE_CHARS)

        try:
            await db.rollback()
        except Exception:
            pass

        latency_ms = max(0, int((time.perf_counter() - start) * 1000))

        try:
            async with db.begin():
                db.add(
                    UsageEvent(
                        id=uuid.uuid4(),
                        provider="stub",
                        model_version="local",
                        prompt_version="v0",
                        status=ChatStatus.error.value,
                        request_id=request_id,
                        latency_ms=latency_ms,
                        error_message=error_message,
                        conversation_id=None,
                        message_id=None,
                    )
                )
        except Exception:
            pass

        return ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            user_message_id=None,
            assistant_message_id=None,
            assistant_content=None,
            status=ChatStatus.error,
            error_message=error_message,
        )

    except Exception as e:

        logger.exception(
            "chat_unhandled_error request_id=%s conversation_id=%s",
            str(request_id),
            str(conversation_id),
)
        error_message = sanitize_error_message("internal error", settings.MAX_ERROR_MESSAGE_CHARS)

        try:
            await db.rollback()
        except Exception:
            pass

        latency_ms = max(0, int((time.perf_counter() - start) * 1000))

        try:
            async with db.begin():
                db.add(
                    UsageEvent(
                        id=uuid.uuid4(),
                        provider="stub",
                        model_version="local",
                        prompt_version="v0",
                        status=ChatStatus.error.value,
                        request_id=request_id,
                        latency_ms=latency_ms,
                        error_message=sanitize_error_message(str(e), settings.MAX_ERROR_MESSAGE_CHARS),
                        conversation_id=None,
                        message_id=None,
                    )
                )
        except Exception:
            pass

        return ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            user_message_id=None,
            assistant_message_id=None,
            assistant_content=None,
            status=ChatStatus.error,
            error_message=error_message,
        )
