import json
import logging
from uuid import uuid4

import pytest

from app.core.domain.provider import ProviderResult
from app.core.domain.routing.routing_types import RoutingDecision
from app.core.observability import routing_evidence


@pytest.mark.parametrize(
    ("provider", "model", "source", "reported"),
    [
        ("vertex", "gemini-alias", "configured", "gemini-alias"),
        ("vertex", "gemini-alias", "provider", "gemini-alias"),
        ("vertex", "gemini-alias", "provider", "gemini-version"),
        ("bedrock", "bedrock-alias", None, "bedrock-alias"),
    ],
)
def test_manual_identity_requires_certified_exact_version(
    provider, model, source, reported, monkeypatch, caplog
):
    caplog.set_level(logging.INFO)
    calls = []
    monkeypatch.setattr(routing_evidence, "estimate_generation_cost_usd", lambda **kw: calls.append(kw) or 1)
    decision = RoutingDecision(provider=provider, model=model, model_tier="balanced", rationale="manual_selection", policy_name="manual")
    result = ProviderResult(
        content="private prompt response", provider=provider, model_version=reported,
        prompt_version="v1", input_tokens=2, output_tokens=3, total_tokens=5,
        latency_ms=7, raw={"model_version_source": source, "private": "credential"},
    )
    state = routing_evidence.RoutingEvidence(decision, fallback_known=True)
    state.terminal(request_id=uuid4(), stream=False, status="success", result=result)
    event, = [json.loads(record.message) for record in caplog.records if getattr(record, "event", None) == "routing.evidence"]
    assert (event["selected_provider"], event["selected_model"], event["reason"]) == (provider, model, "manual_selection")
    assert event["final_provider"] is None and event["final_model"] is None
    assert event["final_generation_estimated_cost_usd"] is None and event["price_snapshot_date"] is None
    assert event["generation_fallback"] is False
    assert (event["input_tokens"], event["output_tokens"], event["total_tokens"], event["provider_latency_ms"]) == (2, 3, 5, 7)
    assert calls == []
    assert "private" not in json.dumps(event) and "credential" not in json.dumps(event)
