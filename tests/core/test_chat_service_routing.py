import uuid

import pytest

from app.core.domain.chat_service import ChatService
from app.core.domain.provider import ProviderInput, ProviderPort, ProviderResult
from app.core.domain.provider_factory import ResolvedProvider
from app.core.domain.routing.routing_types import RoutingContext, RoutingDecision
from app.core.domain.types import ChatMessage


class TrackingProvider(ProviderPort):
    def __init__(self, name: str) -> None:
        self.name = name
        self.generate_calls = 0

    async def generate(self, input: ProviderInput) -> ProviderResult:
        self.generate_calls += 1
        return ProviderResult(
            content=f"reply from {self.name}",
            provider=self.name,
            model_version=f"{self.name}-model",
            prompt_version="v1",
        )

    async def stream(self, input: ProviderInput):
        raise AssertionError("stream not expected in this test")


def make_routing_context(*, request_id, messages, stream) -> RoutingContext:
    message_text = messages[-1].content
    return RoutingContext(
        request_id=request_id,
        stream=stream,
        message_length=len(message_text),
        estimated_tokens=max(1, (len(message_text) + 3) // 4),
        primary_provider_available=True,
    )


@pytest.mark.asyncio
async def test_chat_service_uses_provider_resolver_and_logs_routing_decision(caplog) -> None:
    caplog.set_level("INFO")
    provider = TrackingProvider("stub")
    seen_contexts: list[RoutingContext] = []

    def resolve(context: RoutingContext) -> ResolvedProvider:
        seen_contexts.append(context)
        return ResolvedProvider(
            provider=provider,
            decision=RoutingDecision(
                provider="stub",
                model=None,
                model_tier="balanced",
                rationale="static_default",
            ),
        )

    service = ChatService(
        provider_resolver=resolve,
        routing_context_builder=make_routing_context,
        timeout_s=1.0,
    )

    result = await service.run(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content="hello")],
    )

    assert result.provider_result.provider == "stub"
    assert provider.generate_calls == 1
    assert seen_contexts and seen_contexts[0].message_length == 5
    assert seen_contexts[0].estimated_tokens == 2
    assert seen_contexts[0].primary_provider_available is True
    assert seen_contexts[0].stream is False


@pytest.mark.asyncio
async def test_chat_service_passes_stream_flag_to_provider_resolver() -> None:
    seen_contexts: list[RoutingContext] = []

    class NonStreamingProvider(ProviderPort):
        async def generate(self, input: ProviderInput) -> ProviderResult:
            return ProviderResult(
                content="hello",
                provider="stub",
                model_version="stub-model",
                prompt_version="v1",
            )

        async def stream(self, input: ProviderInput):
            return None

    def resolve(context: RoutingContext) -> ResolvedProvider:
        seen_contexts.append(context)
        return ResolvedProvider(
            provider=NonStreamingProvider(),
            decision=RoutingDecision(
                provider="stub",
                model=None,
                model_tier="balanced",
                rationale="static_default",
            ),
        )

    service = ChatService(
        provider_resolver=resolve,
        routing_context_builder=make_routing_context,
        timeout_s=1.0,
    )
    session = await service.stream_chat(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content="hello stream")],
    )

    chunks = [chunk async for chunk in session.chunks]
    result = await session.get_final_result()

    assert seen_contexts and seen_contexts[0].stream is True
    assert chunks == ["hello"]
    assert result.assistant_message.content == "hello"
