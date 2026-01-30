import uuid
import pytest

from app.core.domain.chat_service import ChatService
from app.core.domain.types import ChatMessage
from app.core.providers.stub_provider import StubProvider
from app.core.domain.errors import ProviderExecutionError


@pytest.mark.asyncio
async def test_chat_service_returns_assistant_message_and_provider_result() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="ok")
    service = ChatService(provider, timeout_s=1.0)


    request_id = uuid.uuid4()
    messages = [ChatMessage(role="user", content="Hola!")]

    res = await service.run(request_id=request_id, messages=messages)

    assert res.request_id == request_id
    assert res.assistant_message.role == "assistant"
    assert isinstance(res.assistant_message.content, str) and res.assistant_message.content

    pr = res.provider_result
    assert pr.provider == "stub"
    assert pr.model_version
    assert pr.prompt_version
    assert pr.content == res.assistant_message.content


@pytest.mark.asyncio
async def test_chat_service_propagates_provider_error() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="error")
    service = ChatService(provider, timeout_s=1.0)

    with pytest.raises(ProviderExecutionError, match="provider execution failed") as exc:
        await service.run(
            request_id=uuid.uuid4(),
            messages=[ChatMessage(role="user", content="boom")],
        )

    assert isinstance(exc.value.__cause__, RuntimeError)
    assert "simulated error" in str(exc.value.__cause__)