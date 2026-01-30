import asyncio
import pytest
from uuid import uuid4

from app.core.domain.chat_service import ChatService
from app.core.domain.types import ChatMessage
from app.core.domain.errors import ProviderTimeoutError
from app.core.domain.provider import ProviderInput, ProviderPort


class SlowProvider(ProviderPort):
    async def generate(self, provider_in: ProviderInput):
        await asyncio.sleep(0.05)
        # nunca llega si timeout es menor
        raise AssertionError("should have timed out")


@pytest.mark.asyncio
async def test_chat_service_enforces_provider_timeout():
    svc = ChatService(SlowProvider(), timeout_s=0.01)
    with pytest.raises(ProviderTimeoutError):
        await svc.run(request_id=uuid4(), messages=[ChatMessage(role="user", content="hi")])
