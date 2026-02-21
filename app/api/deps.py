# app/api/deps.py
from app.core.domain.provider import ProviderPort
from app.core.domain.provider_factory import build_provider
from app.core.domain.chat_service import ChatService
from app.core.settings import settings


def get_provider() -> ProviderPort:
    return build_provider(settings)


def get_chat_service() -> ChatService:
    return ChatService(provider=get_provider(), timeout_s=settings.PROVIDER_TIMEOUT_S)