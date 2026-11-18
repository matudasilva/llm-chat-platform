"""Isolated policy mechanics using arbitrary fixture units, not model capacity."""
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_prompt import MEMORY_SCHEMA_VERSION, preview_messages_for_provider
from app.core.domain.rag_generation import RAG_SCHEMA_VERSION
from app.core.domain.routing.deterministic_routing_policy import DeterministicRoutingPolicy, RoutingEligibilityError
from app.core.domain.routing.routing_types import CandidateAssessment, QualityEvidence, RoutingDestination
from app.core.domain.routing.static_routing_policy import StaticRoutingPolicy
from app.core.domain.types import ChatMessage
from app.services.routing_signals import build_routing_context_builder


DEFAULT = RoutingDestination("synthetic-default", "model-a", "config-a", "restriction")
ALTERNATIVE = RoutingDestination("synthetic-alternative", "model-b", "config-b", "restriction")
CAPACITY = 10


def request(user_content="boundary", output=2):
    return ProviderInput(
        request_id=UUID(int=1),
        messages=[ChatMessage(role="assistant", content="history"), ChatMessage(role="user", content=user_content)],
        metadata={
            "memory": {"schema_version": MEMORY_SCHEMA_VERSION, "events": [{"event_id": 1, "content": "memory"}]},
            "rag": {"schema_version": RAG_SCHEMA_VERSION, "sources": [{"citation": "S1", "document_id": str(UUID(int=2)), "chunk_id": str(UUID(int=3)), "rank": 1, "truncated": False, "content": "source"}]},
        },
        max_tokens=output,
    )


def assess(input_, stream, capacity=CAPACITY):
    """Assign fixture units to each assembled message and output, then bind evidence."""
    messages = preview_messages_for_provider(input_)
    assert [m.role for m in messages] == ["system", "system", "assistant", "user"]
    assert "memory" in messages[0].content and "source" in messages[1].content
    assert messages[2].content == "history"
    # This lookup defines the entire synthetic input space; it is not a tokenizer.
    units = {"boundary": 2, "above": 3, "small": 1}[messages[3].content]
    total = 2 + 2 + 2 + units + input_.max_tokens
    context = build_routing_context_builder(SimpleNamespace(provider="stub"), observe_envelope=True)(provider_input=input_, stream=stream)
    assert context.envelope.has_history and context.envelope.has_memory and context.envelope.has_rag
    assert context.envelope.message_count == len(messages)
    def record(destination, status, cert):
        return CandidateAssessment(destination.provider, destination.model, status, context.envelope.fingerprint,
                                   destination.configuration_id, destination.restriction_id, cert, input_.max_tokens, stream)
    default = record(DEFAULT, "eligible" if total <= capacity else "capacity_ineligible", "synthetic-cert-a")
    alternative = record(ALTERNATIVE, "eligible", "synthetic-cert-b")
    quality = QualityEvidence("synthetic-quality", DEFAULT.configuration_id, ALTERNATIVE.configuration_id,
                              "default_capacity_exceeded", default.certification_id, stream, DEFAULT.restriction_id)
    return total, context, default, alternative, quality


def policy(default, alternative, quality, **kwargs):
    return DeterministicRoutingPolicy(default=DEFAULT, alternative=ALTERNATIVE, enabled=True,
                                      default_assessment=default, alternative_assessment=alternative,
                                      quality=quality, fallback_provider="fallback", fallback_model="fallback-model", **kwargs)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("content,total,provider", [("boundary", 10, "synthetic-default"), ("above", 11, "synthetic-alternative")])
def test_inclusive_synthetic_boundary_selects_initial_destination(stream, content, total, provider):
    measured, context, default, alternative, quality = assess(request(content), stream)
    assert measured == total
    decision = policy(default, alternative, quality).decide(context)
    assert decision.provider == provider
    assert decision.fallback_provider is None and decision.fallback_model is None
    if content == "above":
        with pytest.raises(RoutingEligibilityError):
            policy(default, alternative, None).decide(context)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("candidate,field,value", [
    ("default", "fingerprint", "different"), ("default", "reserved_output", 3),
    ("default", "configuration_id", "different"), ("default", "restriction_id", "different"),
    ("default", "stream", None), ("alternative", "fingerprint", "different"),
    ("alternative", "reserved_output", 3), ("alternative", "configuration_id", "different"),
    ("alternative", "restriction_id", "different"), ("alternative", "stream", None),
])
def test_mismatched_assessment_bindings_fail_closed(stream, candidate, field, value):
    _, context, default, alternative, quality = assess(request("above"), stream)
    value = not stream if field == "stream" else value
    if candidate == "default":
        default = replace(default, **{field: value})
    else:
        alternative = replace(alternative, **{field: value})
    with pytest.raises(RoutingEligibilityError):
        policy(default, alternative, quality).decide(context)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("default_status,alternative_status", [("unknown", "eligible"), ("capacity_ineligible", "unknown"), ("capacity_ineligible", "capacity_ineligible")])
def test_unknown_or_no_eligible_candidate_fails_closed(stream, default_status, alternative_status):
    _, context, default, alternative, quality = assess(request("above"), stream)
    with pytest.raises(RoutingEligibilityError):
        policy(replace(default, status=default_status), replace(alternative, status=alternative_status), quality).decide(context)


@pytest.mark.parametrize("stream", [False, True])
def test_finite_fixture_space_cannot_reach_alternative_and_disabled_matches_static(stream):
    # All four combinations in this explicitly finite space fit the fixture capacity.
    for content in ("small", "boundary"):
        for output in (1, 2):
            total, context, default, alternative, quality = assess(request(content, output), stream)
            assert total <= CAPACITY and default.status == "eligible"
            assert policy(default, alternative, quality).decide(context).provider == DEFAULT.provider
            disabled = DeterministicRoutingPolicy(default=DEFAULT, alternative=ALTERNATIVE, fallback_provider="fallback", fallback_model="fallback-model")
            static = StaticRoutingPolicy(provider=DEFAULT.provider, model=DEFAULT.model, fallback_provider="fallback", fallback_model="fallback-model")
            assert disabled.decide(context) == static.decide(context)
