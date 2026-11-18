import uuid
from types import SimpleNamespace

from app.core.domain.types import ChatMessage
from app.core.domain.provider import ProviderInput
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
        provider_input=ProviderInput(request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="hello world")]),
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
        provider_input=ProviderInput(request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content="abcd" * 10)]),
        stream=False,
    )

    assert context.estimated_tokens == 10
    assert context.primary_provider_available is True


def test_preview_is_identical_uninstrumented_and_does_not_mutate():
    import copy
    from app.core.domain.provider_prompt import messages_for_provider, preview_messages_for_provider, MEMORY_SCHEMA_VERSION
    from app.core.observability import context_evidence as c1

    settings = SimpleNamespace(provider="stub")
    metadata = {"memory": {"schema_version": MEMORY_SCHEMA_VERSION, "events": [{"event_id": 1, "content": "memoria ñ"}]},
                "rag": {"schema_version": "invalid", "sources": []}}
    messages = [ChatMessage(role="assistant", content="前"), ChatMessage(role="user", content="hola")]
    input = ProviderInput(request_id=uuid.uuid4(), messages=messages, metadata=metadata, max_tokens=100)
    before = copy.deepcopy((messages, metadata))
    with c1.request_evidence("test", "test") as evidence:
        context = build_routing_context_builder(settings, observe_envelope=True)(provider_input=input, stream=False)
        preview = preview_messages_for_provider(input)
        assert not [r for r in evidence.records if r["stage"].startswith("prompt.")]
        assert list(preview) == list(messages_for_provider(input))
        assert [r["stage"] for r in evidence.records if r["stage"].startswith("prompt.")] == ["prompt.mapping", "prompt.rendered"]
    assert (messages, metadata) == before
    assert context.envelope.has_history and context.envelope.has_memory and not context.envelope.has_rag
    assert context.envelope.message_count == 3
    assert context.envelope.character_count == sum(len(m.content) for m in preview)
    assert context.envelope.utf8_bytes == sum(len(m.content.encode()) for m in preview)
    assert context.envelope.utf8_bytes > context.envelope.character_count
    assert context.envelope.requested_output == 100
    other = build_routing_context_builder(settings, observe_envelope=True)(provider_input=input, stream=True)
    assert context.envelope.fingerprint != other.envelope.fingerprint


def test_envelope_contains_both_canonical_channels_and_history():
    from app.core.domain.provider_prompt import MEMORY_SCHEMA_VERSION, preview_messages_for_provider
    from app.core.domain.rag_generation import RAG_SCHEMA_VERSION
    settings = SimpleNamespace(provider="stub")
    metadata = {
        "memory": {"schema_version": MEMORY_SCHEMA_VERSION, "events": [{"event_id": 1, "content": "memory"}]},
        "rag": {"schema_version": RAG_SCHEMA_VERSION, "sources": [{"citation": "S1", "document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4()), "rank": 1, "truncated": False, "content": "café"}]},
    }
    input = ProviderInput(request_id=uuid.uuid4(), messages=[ChatMessage(role="assistant", content="old"), ChatMessage(role="user", content="new")], metadata=metadata, max_tokens=100)
    messages = preview_messages_for_provider(input)
    signal = build_routing_context_builder(settings, observe_envelope=True)(provider_input=input, stream=False).envelope
    assert [m.role for m in messages] == ["system", "system", "assistant", "user"]
    assert "memory" in messages[0].content and "café" in messages[1].content
    assert signal.has_memory and signal.has_rag and signal.has_history
    assert signal.character_count == sum(len(m.content) for m in messages)
    assert signal.character_count > len(input.messages[-1].content)
