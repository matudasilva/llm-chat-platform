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


def make_routing_context(*, provider_input, stream) -> RoutingContext:
    request_id = provider_input.request_id
    message_text = provider_input.messages[-1].content
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


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_resolver_and_actual_provider_share_same_input(stream):
    from app.core.domain.provider import ProviderStreamResult, ProviderStreamSession

    observed = []
    delivered = []
    class Provider:
        async def generate(self, input):
            delivered.append(input)
            return ProviderResult(content="ok", provider="stub", model_version="m", prompt_version="v1")

        async def stream(self, input):
            delivered.append(input)
            async def chunks():
                yield "ok"
            async def final():
                return ProviderStreamResult(content="ok", provider_result=ProviderResult(content="ok", provider="stub", model_version="m", prompt_version="v1"))
            return ProviderStreamSession(chunks=chunks(), get_final_result=final)

    def builder(*, provider_input, stream):
        observed.append((provider_input, stream))
        return make_routing_context(provider_input=provider_input, stream=stream)

    service = ChatService(provider_resolver=lambda context: ResolvedProvider(provider=Provider(), decision=RoutingDecision(provider="stub", model=None, model_tier="balanced", rationale="static_default")), routing_context_builder=builder, timeout_s=1)
    metadata = {"test": ["value"]}
    messages = [ChatMessage(role="user", content="hello")]
    if stream:
        session = await service.stream_chat(request_id=uuid.uuid4(), messages=messages, provider_metadata=metadata)
        assert [part async for part in session.chunks] == ["ok"]
        await session.get_final_result()
    else:
        await service.run(request_id=uuid.uuid4(), messages=messages, provider_metadata=metadata)
    assert observed == [(delivered[0], stream)]
    assert observed[0][0] is delivered[0]
    assert delivered[0].messages is messages and delivered[0].metadata is metadata


@pytest.mark.asyncio
async def test_stream_compatibility_fallback_resolves_again_for_run():
    seen = []
    class Provider:
        async def stream(self, input):
            return None
        async def generate(self, input):
            assert input is seen[1][0]
            return ProviderResult(content="ok", provider="stub", model_version="m", prompt_version="v1")
    def builder(*, provider_input, stream):
        seen.append((provider_input, stream))
        return make_routing_context(provider_input=provider_input, stream=stream)
    service = ChatService(provider_resolver=lambda context: ResolvedProvider(provider=Provider(), decision=RoutingDecision(provider="stub", model=None, model_tier="balanced", rationale="static_default")), routing_context_builder=builder, timeout_s=1)
    session = await service.stream_chat(request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="x")])
    assert [part async for part in session.chunks] == ["ok"]
    assert [flag for _, flag in seen] == [True, False]
    assert seen[0][0] is not seen[1][0]
