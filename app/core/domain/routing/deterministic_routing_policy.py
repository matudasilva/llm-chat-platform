"""Dormant, provider-neutral routing rule; assessments are supplied by composition."""
from __future__ import annotations

from .routing_types import (
    CandidateAssessment, QualityEvidence, RoutingContext, RoutingDecision,
    RoutingDestination,
)
from .static_routing_policy import StaticRoutingPolicy


def _identity(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


class RoutingEligibilityError(ValueError):
    """No destination is certified for this request."""


class DeterministicRoutingPolicy:
    def __init__(
        self, *, default: RoutingDestination, alternative: RoutingDestination | None = None,
        fallback_provider: str | None = None, fallback_model: str | None = None,
        enabled: bool = False, default_assessment: CandidateAssessment | None = None,
        alternative_assessment: CandidateAssessment | None = None,
        quality: QualityEvidence | None = None,
    ) -> None:
        self._default = default
        self._alternative = alternative
        self._enabled = enabled
        self._default_assessment = default_assessment
        self._alternative_assessment = alternative_assessment
        self._quality = quality
        self._static = StaticRoutingPolicy(
            provider=default.provider, model=default.model,
            fallback_provider=fallback_provider, fallback_model=fallback_model,
        )

    def decide(self, context: RoutingContext) -> RoutingDecision:
        if not self._enabled:
            return self._static.decide(context)
        default_status = self._status(context, self._default, self._default_assessment)
        if default_status == "eligible":
            return self._decision(self._default, "deterministic_default_eligible")
        if (default_status == "capacity_ineligible" and self._alternative is not None
                and self._status(context, self._alternative, self._alternative_assessment) == "eligible"
                and self._quality_matches(context)):
            return self._decision(self._alternative, "deterministic_capacity_alternative")
        raise RoutingEligibilityError("No certified eligible routing destination")

    @staticmethod
    def _status(context: RoutingContext, destination: RoutingDestination,
                assessment: CandidateAssessment | None) -> str:
        envelope = context.envelope
        if (envelope is None or assessment is None or type(context.stream) is not bool
                or type(envelope.stream) is not bool or context.stream != envelope.stream
                or type(assessment.stream) is not bool or assessment.stream != context.stream
                or not _identity(destination.provider) or not _identity(destination.model)
                or not _identity(assessment.provider) or not _identity(assessment.model)
                or assessment.provider != destination.provider or assessment.model != destination.model
                or type(envelope.requested_output) is not int or envelope.requested_output <= 0
                or type(assessment.reserved_output) is not int
                or assessment.reserved_output != envelope.requested_output
                or not _identity(destination.configuration_id) or not _identity(destination.restriction_id)
                or not _identity(assessment.configuration_id) or not _identity(assessment.restriction_id)
                or not _identity(assessment.certification_id)
                or not _identity(assessment.fingerprint) or not _identity(envelope.fingerprint)
                or not isinstance(assessment.status, str)
                or assessment.status not in {"eligible", "capacity_ineligible", "other_ineligible", "unknown"}
                or assessment.configuration_id != destination.configuration_id
                or assessment.restriction_id != destination.restriction_id
                or assessment.fingerprint != envelope.fingerprint):
            return "unknown"
        return assessment.status

    def _quality_matches(self, context: RoutingContext) -> bool:
        quality, default, alternative, assessment = (
            self._quality, self._default, self._alternative, self._default_assessment
        )
        return bool(
            quality and alternative and assessment and _identity(quality.evidence_id)
            and _identity(quality.default_configuration_id)
            and _identity(quality.alternative_configuration_id)
            and _identity(quality.capacity_certification_id) and _identity(quality.restriction_id)
            and quality.default_configuration_id == default.configuration_id
            and quality.alternative_configuration_id == alternative.configuration_id
            and quality.condition == "default_capacity_exceeded"
            and quality.capacity_certification_id == assessment.certification_id
            and type(quality.stream) is bool and quality.stream == context.stream
            and default.restriction_id == alternative.restriction_id == quality.restriction_id
        )

    @staticmethod
    def _decision(destination: RoutingDestination, rationale: str) -> RoutingDecision:
        return RoutingDecision(provider=destination.provider, model=destination.model,
                               model_tier="balanced", rationale=rationale,
                               policy_name="deterministic", policy_version="v1")
