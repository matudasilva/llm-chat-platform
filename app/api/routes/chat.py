import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse, ChatStatus

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.usage_event import UsageEvent

from app.api.deps import get_chat_service
from app.core.domain.chat_service import ChatService
from app.core.domain.types import ChatMessage

from app.core.domain.errors import ProviderTimeoutError, ProviderExecutionError
from app.core.settings import settings
from app.core.utils.limits import sanitize_error_message, truncate


router = APIRouter(tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    start = time.perf_counter()
    request_id = uuid.uuid4()

    status = ChatStatus.error
    error_message: str | None = None

    conversation_id = payload.conversation_id
    user_message_id: uuid.UUID | None = None
    assistant_message_id: uuid.UUID | None = None
    assistant_content: str | None = None

    try:
        # Single transaction: either everything is persisted, or nothing is.
        async with db.begin():
            # 1) Conversation: create or validate
            if conversation_id is None:
                conv = Conversation(id=uuid.uuid4())
                db.add(conv)
                await db.flush()
                conversation_id = conv.id
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

            # 3) Execute model (via ChatService + ProviderPort)
            service_result = await chat_service.run(
                request_id=request_id,
                messages=[ChatMessage(role="user", content=payload.message)],
            )

            assistant_content = service_result.assistant_message.content
            assistant_content = truncate(assistant_content, settings.MAX_ASSISTANT_CHARS)
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
            latency_ms = int((time.perf_counter() - start) * 1000)

            # Telemetry must never break the request.
            try:
                ev = UsageEvent(
                    id=uuid.uuid4(),
                    provider=provider_result.provider,
                    model_version=provider_result.model_version,
                    prompt_version=provider_result.prompt_version,
                    status=status.value,  # "success" | "error"
                    request_id=request_id,
                    latency_ms=latency_ms,
                    error_message=None,
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,  # convention: assistant message
                    input_tokens=provider_result.input_tokens,
                    output_tokens=provider_result.output_tokens,
                    total_tokens=provider_result.total_tokens,
                )
                db.add(ev)
            except Exception:
                pass

        # commit OK (exits db.begin())
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
        # Controlled provider failure: return error response (no stack trace).
        error_message = sanitize_error_message(str(e), settings.MAX_ERROR_MESSAGE_CHARS)

        try:
            await db.rollback()
        except Exception:
            pass

        latency_ms = int((time.perf_counter() - start) * 1000)

        # Best-effort UsageEvent without FKs
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
        # Unexpected server error: still return controlled error response.
        error_message = sanitize_error_message("internal error", settings.MAX_ERROR_MESSAGE_CHARS)

        try:
            await db.rollback()
        except Exception:
            pass

        latency_ms = int((time.perf_counter() - start) * 1000)

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
