from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


ModelTier = Literal["cheap", "balanced", "smart"]
RoutingFinalStatus = Literal["success", "error"]
RoutingFailureKind = Literal["timeout", "provider_error", "other"]
RoutingLatencyBucket = Literal["lt_1s", "1s_to_5s", "gte_5s"]


@dataclass(frozen=True, slots=True)
class RoutingContext:
    request_id: UUID
    stream: bool
    message_length: int
    estimated_tokens: int
    primary_provider_available: bool
    conversation_id: UUID | None = None
    envelope: EnvelopeSignals | None = None


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    provider: str
    model: str | None
    model_tier: ModelTier
    rationale: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    policy_name: str = "static"
    policy_version: str = "v1"


@dataclass(frozen=True, slots=True)
class RoutingOutcome:
    final_status: RoutingFinalStatus
    final_provider: str
    fallback_used: bool
    stream_completed: bool
    latency_bucket: RoutingLatencyBucket
    failure_kind: RoutingFailureKind | None = None


@dataclass(frozen=True, slots=True)
class EnvelopeSignals:
    character_count: int
    utf8_bytes: int
    message_count: int
    has_history: bool
    has_memory: bool
    has_rag: bool
    requested_output: int | None
    fingerprint: str
    stream: bool


@dataclass(frozen=True, slots=True)
class RoutingDestination:
    provider: str
    model: str | None
    configuration_id: str | None
    restriction_id: str | None


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    provider: str
    model: str
    status: Literal["eligible", "capacity_ineligible", "other_ineligible", "unknown"]
    fingerprint: str
    configuration_id: str
    restriction_id: str
    certification_id: str
    reserved_output: int
    stream: bool


@dataclass(frozen=True, slots=True)
class QualityEvidence:
    evidence_id: str
    default_configuration_id: str
    alternative_configuration_id: str
    condition: str
    capacity_certification_id: str
    stream: bool
    restriction_id: str
