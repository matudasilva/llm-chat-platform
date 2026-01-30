import pytest
from uuid import uuid4

from app.core.domain.chat_service import ChatService
from app.core.domain.types import ChatMessage
from app.core.domain.errors import ProviderExecutionError
from app.core.domain.provider import ProviderInput, ProviderPort


class ExplodingProvider(ProviderPort):
    async def generate(self, provider_in: ProviderInput):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_chat_service_maps_provider_exception():
    svc = ChatService(ExplodingProvider(), timeout_s=1.0)
    with pytest.raises(ProviderExecutionError):
        await svc.run(request_id=uuid4(), messages=[ChatMessage(role="user", content="hi")])
