# app/api/deps.py
import uuid

from fastapi import Request

from app.core.domain.provider import ProviderPort
from app.core.domain.provider_factory import build_provider, build_provider_resolver
from app.core.domain.chat_service import ChatService
from app.core.domain.rag_generation import RagGenerationAugmentor, RagGenerationContext
from app.core.domain.retrieval_factory import build_retrieval_pipeline
from app.core.settings import settings
from app.http.request_context import get_request_id
from app.infra.db.session import short_lived_rag_session
from app.schemas.chat import ChatRequest
from app.services.notion_write import NotionWriteService
from app.services.routing_signals import build_routing_context_builder


def get_provider() -> ProviderPort:
    return build_provider(settings)


def get_chat_service() -> ChatService:
    return ChatService(
        provider_resolver=build_provider_resolver(settings),
        routing_context_builder=build_routing_context_builder(settings),
        timeout_s=settings.provider_timeout_s,
    )


async def get_chat_rag_context(payload: ChatRequest, request: Request) -> RagGenerationContext:
    if not settings.chat_rag_augmentation_enabled:
        return RagGenerationContext()

    rid = get_request_id()
    request_id = uuid.UUID(rid) if rid else uuid.uuid4()
    try:
        async with short_lived_rag_session(request) as db:
            augmentor = RagGenerationAugmentor(
                pipeline=build_retrieval_pipeline(db, settings),
                timeout_s=settings.chat_rag_retrieval_timeout_s,
                max_sources=settings.chat_rag_max_sources,
                max_source_chars=settings.chat_rag_max_source_chars,
                max_context_chars=settings.chat_rag_max_context_chars,
            )
            return await augmentor.augment(request_id=request_id, query=payload.message)
    except Exception as exc:
        # Construction/session failures happen outside RagGenerationAugmentor,
        # but remain the same best-effort pre-generation boundary.
        RagGenerationAugmentor._log_degraded(
            request_id=request_id,
            reason=type(exc).__name__,
        )
        return RagGenerationContext()


def get_notion_write_service() -> NotionWriteService:
    return NotionWriteService(settings)
