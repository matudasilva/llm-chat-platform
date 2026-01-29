# app/api/deps.py
import os
from app.core.domain.provider import ProviderPort
from app.core.providers.stub_provider import StubProvider
from app.core.domain.chat_service import ChatService


def get_provider() -> ProviderPort:
    mode = os.getenv("STUB_PROVIDER_MODE", "ok")
    latency_ms = int(os.getenv("STUB_SIMULATED_LATENCY_MS", "0"))
    return StubProvider(mode=mode, simulated_latency_ms=latency_ms)

def get_chat_service() -> ChatService:
    return ChatService(provider=get_provider())



