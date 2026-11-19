from dataclasses import replace
from uuid import uuid4

import pytest

from app.core.domain.routing.deterministic_routing_policy import DeterministicRoutingPolicy, RoutingEligibilityError
from app.core.domain.routing.routing_types import CandidateAssessment, EnvelopeSignals, QualityEvidence, RoutingContext, RoutingDestination
from app.core.domain.routing.static_routing_policy import StaticRoutingPolicy


DEFAULT = RoutingDestination("default", "model-a", "config-a", "restriction")
ALTERNATIVE = RoutingDestination("alternative", "model-b", "config-b", "restriction")
ENVELOPE = EnvelopeSignals(10, 10, 1, False, False, False, 100, "request", False)
CONTEXT = RoutingContext(uuid4(), False, 10, 3, True, envelope=ENVELOPE)
DEFAULT_CAPACITY = CandidateAssessment("default", "model-a", "capacity_ineligible", "request", "config-a", "restriction", "cert-a", 100, False)
ALT_ELIGIBLE = CandidateAssessment("alternative", "model-b", "eligible", "request", "config-b", "restriction", "cert-b", 100, False)
QUALITY = QualityEvidence("quality", "config-a", "config-b", "default_capacity_exceeded", "cert-a", False, "restriction")


def policy(**kwargs):
    options = dict(default=DEFAULT, alternative=ALTERNATIVE, enabled=True,
                   default_assessment=DEFAULT_CAPACITY, alternative_assessment=ALT_ELIGIBLE, quality=QUALITY)
    options.update(kwargs)
    return DeterministicRoutingPolicy(**options)


def test_disabled_is_exact_static_decision_with_fallback():
    subject = DeterministicRoutingPolicy(default=DEFAULT, fallback_provider="fallback", fallback_model="m")
    assert subject.decide(CONTEXT) == StaticRoutingPolicy(provider="default", model="model-a", fallback_provider="fallback", fallback_model="m").decide(CONTEXT)


def test_default_eligible_does_not_need_quality_or_attach_fallback():
    decision = policy(default_assessment=replace(DEFAULT_CAPACITY, status="eligible"), quality=None).decide(CONTEXT)
    assert decision.provider == "default"
    assert decision.fallback_provider is None


def test_capacity_alternative_has_no_ineligible_fallback():
    decision = policy().decide(CONTEXT)
    assert decision.provider == "alternative"
    assert decision.fallback_provider is None


@pytest.mark.parametrize("field,value", [
    ("fingerprint", "stale"), ("configuration_id", "wrong"), ("restriction_id", "wrong"),
    ("certification_id", ""), ("reserved_output", 99), ("reserved_output", True),
    ("status", "other_ineligible"), ("status", "unknown"),
])
def test_invalid_default_evidence_fails_closed(field, value):
    with pytest.raises(RoutingEligibilityError):
        policy(default_assessment=replace(DEFAULT_CAPACITY, **{field: value})).decide(CONTEXT)


@pytest.mark.parametrize("field,value", [
    ("fingerprint", "stale"), ("configuration_id", "wrong"), ("restriction_id", "wrong"),
    ("certification_id", ""), ("reserved_output", 99), ("status", "unknown"),
])
def test_invalid_alternative_evidence_fails_closed(field, value):
    with pytest.raises(RoutingEligibilityError):
        policy(alternative_assessment=replace(ALT_ELIGIBLE, **{field: value})).decide(CONTEXT)


@pytest.mark.parametrize("field,value", [
    ("evidence_id", ""), ("default_configuration_id", "wrong"),
    ("alternative_configuration_id", "wrong"), ("condition", "fallback"),
    ("capacity_certification_id", "wrong"), ("stream", True), ("restriction_id", "wrong"),
])
def test_quality_must_match_its_complete_scope(field, value):
    with pytest.raises(RoutingEligibilityError):
        policy(quality=replace(QUALITY, **{field: value})).decide(CONTEXT)


@pytest.mark.parametrize("output", [None, 0, -1, True])
def test_missing_or_invalid_output_fails_closed(output):
    with pytest.raises(RoutingEligibilityError):
        policy().decide(replace(CONTEXT, envelope=replace(ENVELOPE, requested_output=output)))


def test_transport_and_destination_restrictions_are_bound():
    with pytest.raises(RoutingEligibilityError):
        policy().decide(replace(CONTEXT, stream=True))
    with pytest.raises(RoutingEligibilityError):
        policy(alternative=replace(ALTERNATIVE, restriction_id="different"),
               alternative_assessment=replace(ALT_ELIGIBLE, restriction_id="different")).decide(CONTEXT)


@pytest.mark.parametrize("field", ["fingerprint", "configuration_id", "restriction_id", "certification_id"])
def test_malformed_assessment_identity_type_fails_closed(field):
    with pytest.raises(RoutingEligibilityError):
        policy(default_assessment=replace(DEFAULT_CAPACITY, **{field: 1})).decide(CONTEXT)


@pytest.mark.parametrize("field", ["evidence_id", "default_configuration_id", "alternative_configuration_id", "capacity_certification_id", "restriction_id"])
def test_malformed_quality_identity_type_fails_closed(field):
    with pytest.raises(RoutingEligibilityError):
        policy(quality=replace(QUALITY, **{field: 1})).decide(CONTEXT)


def test_invalid_destination_and_transport_types_fail_closed():
    with pytest.raises(RoutingEligibilityError):
        policy(default=replace(DEFAULT, configuration_id=1), default_assessment=replace(DEFAULT_CAPACITY, configuration_id=1)).decide(CONTEXT)
    with pytest.raises(RoutingEligibilityError):
        policy().decide(replace(CONTEXT, stream=0))
    with pytest.raises(RoutingEligibilityError):
        policy(default_assessment=replace(DEFAULT_CAPACITY, fingerprint=1)).decide(replace(CONTEXT, envelope=replace(ENVELOPE, fingerprint=1)))


@pytest.mark.parametrize("destination", [replace(DEFAULT, provider=""), replace(DEFAULT, model=None), replace(DEFAULT, model="other"), replace(DEFAULT, provider="other")])
def test_destination_identity_must_match_assessment(destination):
    with pytest.raises(RoutingEligibilityError):
        policy(default=destination, default_assessment=replace(DEFAULT_CAPACITY, status="eligible")).decide(CONTEXT)


def test_transport_reuse_is_rejected_even_for_eligible_default():
    eligible = policy(default_assessment=replace(DEFAULT_CAPACITY, status="eligible"))
    with pytest.raises(RoutingEligibilityError):
        eligible.decide(replace(CONTEXT, stream=True))
    stream_context = replace(CONTEXT, stream=True, envelope=replace(ENVELOPE, stream=True))
    with pytest.raises(RoutingEligibilityError):
        eligible.decide(stream_context)
    stream_eligible = policy(default_assessment=replace(DEFAULT_CAPACITY, status="eligible", stream=True))
    assert stream_eligible.decide(stream_context).provider == "default"
    with pytest.raises(RoutingEligibilityError):
        stream_eligible.decide(replace(stream_context, stream=False))
    with pytest.raises(RoutingEligibilityError):
        stream_eligible.decide(CONTEXT)


def test_unhashable_status_fails_with_safe_policy_error():
    with pytest.raises(RoutingEligibilityError):
        policy(default_assessment=replace(DEFAULT_CAPACITY, status=[])).decide(CONTEXT)


def test_invalid_assessment_transport_type_fails_closed():
    with pytest.raises(RoutingEligibilityError):
        policy(default_assessment=replace(DEFAULT_CAPACITY, stream=0)).decide(CONTEXT)
