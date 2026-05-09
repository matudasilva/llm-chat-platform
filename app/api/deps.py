# app/api/deps.py
from app.core.domain.provider import ProviderPort
from app.core.domain.provider_factory import build_provider, build_provider_resolver
from app.core.domain.chat_service import ChatService
from app.core.settings import settings
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


def get_notion_write_service() -> NotionWriteService:
    return NotionWriteService(settings)
