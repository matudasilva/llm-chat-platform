import uuid
from types import SimpleNamespace

from app.core.domain.types import ChatMessage
from app.services.routing_signals import build_routing_context_builder


def test_build_routing_context_builder_derives_mvp_signals() -> None:
    settings = SimpleNamespace(
        provider="openai",
        openai_api_key="test-key",
        bedrock_region=None,
        bedrock_model=None,
    )
    builder = build_routing_context_builder(settings)

    context = builder(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content="hello world")],
        stream=False,
    )

    assert context.message_length == 11
    assert context.estimated_tokens == 3
    assert context.primary_provider_available is True


def test_build_routing_context_builder_uses_provider_agnostic_best_effort_estimation() -> None:
    settings = SimpleNamespace(
        provider="bedrock",
        openai_api_key=None,
        bedrock_region="us-east-1",
        bedrock_model="anthropic.claude-3-haiku-20240307-v1:0",
    )
    builder = build_routing_context_builder(settings)

    context = builder(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content="abcd" * 10)],
        stream=False,
    )

    assert context.estimated_tokens == 10
    assert context.primary_provider_available is True
