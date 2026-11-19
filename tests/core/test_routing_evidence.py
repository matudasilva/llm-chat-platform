import asyncio
import json
import logging
from uuid import uuid4

import pytest

from app.core.domain.chat_service import ChatService
from app.core.domain.provider import ProviderResult, ProviderStreamResult, ProviderStreamSession
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.domain.provider_factory import ResolvedProvider
from app.core.domain.routing.routing_types import RoutingDecision
from app.core.domain.types import ChatMessage
from app.core.observability import routing_evidence as evidence_module
from app.core.observability.routing_evidence import RoutingEvidence, emit_cache_hit_evidence
from app.core.providers.resilient_provider import ResilientProvider


def result():
    return ProviderResult(content="secret answer", provider="stub", model_version="m", prompt_version="v1", input_tokens=2, output_tokens=3, total_tokens=5, latency_ms=7)


def events(caplog):
    return [json.loads(r.message) for r in caplog.records if getattr(r, "event", None) == "routing.evidence"]


class Provider:
    provider_name = "stub"

    def __init__(self, fail=False):
        self.fail = fail

    async def generate(self, input):
        if self.fail:
            raise ProviderError(kind=ProviderErrorKind.upstream, message="secret failure", provider="stub", retryable=True)
        return result()

    async def stream(self, input):
        async def chunks():
            yield "chunk"
        async def final():
            return ProviderStreamResult(content="chunk", provider_result=result())
        return ProviderStreamSession(chunks=chunks(), get_final_result=final)


def service(fail=False):
    decision = RoutingDecision(provider="stub", model="selected", model_tier="balanced", rationale="static_default", fallback_provider="stub", fallback_model="m")
    def resolve(context):
        state = RoutingEvidence(decision, fallback_known=True)
        provider = ResilientProvider(Provider(fail), Provider(), evidence=state)
        return ResolvedProvider(provider, decision, state)
    return ChatService(provider_resolver=resolve, routing_context_builder=lambda **kwargs: object(), timeout_s=1)


@pytest.mark.asyncio
async def test_terminal_evidence_preserves_explicit_same_provider_fallback_and_unknown_price(caplog):
    caplog.set_level(logging.INFO)
    answer = await service(fail=True).run(request_id=uuid4(), messages=[ChatMessage(role="user", content="secret prompt")])
    assert answer.provider_result.content == "secret answer"
    event, = events(caplog)
    assert (event["selected_model"], event["final_model"], event["generation_fallback"]) == ("selected", "m", True)
    assert event["input_tokens"] == 2 and event["final_generation_estimated_cost_usd"] is None
    assert "secret" not in json.dumps(event)
    assert event["request_total_cost_usd"] is None


@pytest.mark.asyncio
async def test_stream_eof_is_not_terminal_and_finalization_emits_once(caplog):
    caplog.set_level(logging.INFO)
    session = await service().stream_chat(request_id=uuid4(), messages=[])
    assert [x async for x in session.chunks] == ["chunk"]
    assert events(caplog) == []
    await session.get_final_result()
    await session.get_final_result()
    event, = events(caplog)
    assert event["stream"] is True and event["status"] == "success"


@pytest.mark.asyncio
async def test_sink_failure_preserves_error_and_cancellation(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("sink failed")
    monkeypatch.setattr(evidence_module.logger, "info", fail)
    monkeypatch.setattr("app.core.domain.chat_service.logger.exception", fail)
    class Broken:
        async def generate(self, input):
            raise RuntimeError("original")
    from app.core.domain.errors import ProviderExecutionError
    with pytest.raises(ProviderExecutionError, match="provider execution failed"):
        await ChatService(Broken(), timeout_s=1).run(request_id=uuid4(), messages=[])
    class Cancelled:
        async def generate(self, input):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await ChatService(Cancelled(), timeout_s=1).run(request_id=uuid4(), messages=[])
    assert (await ChatService(Provider(), timeout_s=1).run(request_id=uuid4(), messages=[])).assistant_message.content == "secret answer"


def test_cache_event_has_no_current_usage(caplog):
    caplog.set_level(logging.INFO)
    class Source:
        provider_result = result()
    emit_cache_hit_evidence(request_id=uuid4(), source_result=Source())
    event, = events(caplog)
    assert event["cache_hit"] and event["inference_performed"] is False
    assert event["input_tokens"] is None and event["final_model"] is None
    assert "cached_source_model" not in event


def test_hostile_clock_and_estimator_preserve_emission(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    def fail(*args, **kwargs):
        raise RuntimeError("hostile")
    monkeypatch.setattr(evidence_module.time, "monotonic", fail)
    monkeypatch.setattr(evidence_module, "estimate_generation_cost_usd", fail)
    state = RoutingEvidence()
    state.terminal(request_id=uuid4(), stream=False, status="success", result=result())
    event, = events(caplog)
    assert event["service_elapsed_ms"] is None and event["final_generation_estimated_cost_usd"] is None


@pytest.mark.asyncio
async def test_stream_error_and_cancellation_emit_once(caplog):
    caplog.set_level(logging.INFO)
    class BrokenStream:
        async def stream(self, input):
            async def chunks():
                yield "first"
                raise RuntimeError("private failure")
            async def final():
                raise RuntimeError("private failure")
            return ProviderStreamSession(chunks=chunks(), get_final_result=final)
    session = await ChatService(BrokenStream(), timeout_s=1).stream_chat(request_id=uuid4(), messages=[])
    with pytest.raises(RuntimeError, match="private failure"):
        _ = [chunk async for chunk in session.chunks]
    with pytest.raises(RuntimeError, match="private failure"):
        await session.get_final_result()
    event, = events(caplog)
    assert event["status"] == "error" and event["final_model"] is None
    caplog.clear()
    class CancelStream:
        async def stream(self, input):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await ChatService(CancelStream(), timeout_s=1).stream_chat(request_id=uuid4(), messages=[])
    event, = events(caplog)
    assert event["status"] == "cancelled" and event["generation_attempted"]


@pytest.mark.asyncio
async def test_compatibility_path_reports_only_actual_run(caplog):
    caplog.set_level(logging.INFO)
    class NoStream(Provider):
        async def stream(self, input):
            return None
    session = await ChatService(NoStream(), timeout_s=1).stream_chat(request_id=uuid4(), messages=[])
    assert [chunk async for chunk in session.chunks] == ["secret answer"]
    await session.get_final_result()
    event, = events(caplog)
    assert event["stream"] is False and event["status"] == "success"


@pytest.mark.asyncio
async def test_resilience_logging_failure_does_not_trigger_or_block_fallback(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("log failure")
    monkeypatch.setattr("app.core.providers.resilient_provider.logger.info", fail)
    monkeypatch.setattr("app.core.providers.resilient_provider.logger.warning", fail)
    assert (await service(fail=True).run(request_id=uuid4(), messages=[])).provider_result.content == "secret answer"
    session = await service().stream_chat(request_id=uuid4(), messages=[])
    assert [chunk async for chunk in session.chunks] == ["chunk"]
    assert (await session.get_final_result()).assistant_message.content == "chunk"


def test_known_price_is_only_final_generation_estimate(caplog):
    caplog.set_level(logging.INFO)
    priced = ProviderResult(content="", provider="openai", model_version="gpt-4.1-mini", prompt_version="v1", input_tokens=100, output_tokens=10)
    decision = RoutingDecision(provider="openai", model="gpt-4.1-mini", model_tier="balanced", rationale="static_default")
    state = RoutingEvidence(decision)
    state.terminal(request_id=uuid4(), stream=False, status="success", result=priced)
    event, = events(caplog)
    assert event["final_generation_estimated_cost_usd"] == pytest.approx(0.000056)
    assert event["price_snapshot_date"] == "2026-09-12"
    assert event["cost_scope"] == "final_generation_only" and event["request_total_cost_usd"] is None


@pytest.mark.asyncio
async def test_concurrent_states_remain_isolated(caplog):
    caplog.set_level(logging.INFO)
    first, second = uuid4(), uuid4()
    await asyncio.gather(service(fail=True).run(request_id=first, messages=[]), service().run(request_id=second, messages=[]))
    observed = {event["request_id"]: event for event in events(caplog)}
    assert observed[str(first)]["generation_fallback"] is True
    assert observed[str(second)]["generation_fallback"] is False


@pytest.mark.asyncio
async def test_factory_decision_log_failure_does_not_block_resolution(monkeypatch):
    from app.core.domain.provider_factory import build_provider_resolver
    from app.core.domain.routing.routing_types import RoutingContext
    from app.core.settings import Settings
    def fail(*args, **kwargs):
        raise RuntimeError("logger failure")
    monkeypatch.setattr("app.core.domain.provider_factory.logger.info", fail)
    cfg = Settings(provider="stub")
    context = RoutingContext(request_id=uuid4(), stream=False, message_length=1, estimated_tokens=1, primary_provider_available=True)
    resolved = build_provider_resolver(cfg)(context)
    assert resolved.decision.provider == "stub" and resolved.evidence is not None


def test_evidence_is_serialized_in_production_formatter_message(caplog):
    caplog.set_level(logging.INFO)
    decision = RoutingDecision(provider="stub", model="m", model_tier="balanced", rationale="static_default")
    state = RoutingEvidence(decision)
    state.terminal(request_id=uuid4(), stream=False, status="success", result=result())
    record = next(r for r in caplog.records if getattr(r, "event", None) == "routing.evidence")
    record.tenant_id = "test"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s tenant_id=%(tenant_id)s")
    line = formatter.format(record)
    assert '"final_model":"m"' in line and '"generation_fallback":null' in line


def test_untrusted_fields_and_nonfinite_cost_are_not_serialized(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(evidence_module, "estimate_generation_cost_usd", lambda **kwargs: float("nan"))
    decision = RoutingDecision(provider="api_key_123", model="sk-secret123", model_tier="balanced", rationale="sensitive words")
    poisoned = ProviderResult(content="private", provider="password-123", model_version="bad identifier spaces", prompt_version="v1", input_tokens=True, output_tokens=-1, total_tokens="secret", latency_ms=float("inf"))
    state = RoutingEvidence(decision)
    state.terminal(request_id=uuid4(), stream=False, status="success", result=poisoned)
    event, = events(caplog)
    for field in ("selected_provider", "selected_model", "reason", "final_provider", "final_model", "input_tokens", "output_tokens", "total_tokens", "provider_latency_ms", "final_generation_estimated_cost_usd"):
        assert event[field] is None
    assert "secret" not in json.dumps(event) and "password" not in json.dumps(event)


@pytest.mark.asyncio
async def test_normalized_error_kind_is_safe(caplog):
    caplog.set_level(logging.INFO)
    class Failure:
        async def generate(self, input):
            raise ProviderError(kind=ProviderErrorKind.auth, message="private", provider="stub")
    from app.core.domain.errors import ProviderExecutionError
    with pytest.raises(ProviderExecutionError):
        await ChatService(Failure(), timeout_s=1).run(request_id=uuid4(), messages=[])
    event, = events(caplog)
    assert event["failure_kind"] == "auth" and "private" not in json.dumps(event)


@pytest.mark.asyncio
async def test_broken_fallback_observer_cannot_block_generate_or_stream():
    class BrokenObserver:
        def fallback_dispatched(self):
            raise RuntimeError("observer failure")
    class BadPrimary(Provider):
        async def stream(self, input):
            raise ProviderError(kind=ProviderErrorKind.upstream, message="failure", provider="stub", retryable=True)
    from app.core.domain.provider import ProviderInput
    inp = ProviderInput(request_id=uuid4(), messages=[])
    resilient = ResilientProvider(BadPrimary(fail=True), Provider(), evidence=BrokenObserver())
    assert (await resilient.generate(inp)).content == "secret answer"
    session = await resilient.stream(inp)
    assert [chunk async for chunk in session.chunks] == ["chunk"]
    assert (await session.get_final_result()).content == "chunk"
    class CancelFallback(Provider):
        async def generate(self, input):
            raise asyncio.CancelledError()
        async def stream(self, input):
            raise asyncio.CancelledError()
    resilient = ResilientProvider(BadPrimary(fail=True), CancelFallback(), evidence=BrokenObserver())
    with pytest.raises(asyncio.CancelledError):
        await resilient.generate(inp)
    with pytest.raises(asyncio.CancelledError):
        await resilient.stream(inp)


def test_unmatched_upstream_identifier_and_unbound_provider_are_unknown(caplog):
    caplog.set_level(logging.INFO)
    decision = RoutingDecision(provider="stub", model="m", model_tier="balanced", rationale="static_default", fallback_provider="other", fallback_model="fallback-m")
    state = RoutingEvidence(decision)
    poison = ProviderResult(content="", provider="stub", model_version="private-answer", prompt_version="v1", input_tokens=2, output_tokens=3)
    state.terminal(request_id=uuid4(), stream=False, status="success", result=poison)
    event, = events(caplog)
    assert event["final_provider"] is None and event["final_model"] is None
    assert "private-answer" not in json.dumps(event)
    caplog.clear()
    fallback = ProviderResult(content="", provider="other", model_version="fallback-m", prompt_version="v1")
    state = RoutingEvidence(decision)
    state.terminal(request_id=uuid4(), stream=False, status="success", result=fallback)
    event, = events(caplog)
    assert (event["final_provider"], event["final_model"]) == ("other", "fallback-m")
    caplog.clear()
    RoutingEvidence().terminal(request_id=uuid4(), stream=False, status="success", result=result())
    event, = events(caplog)
    assert event["final_provider"] is None and event["final_model"] is None


def test_untrusted_identity_never_reaches_cost_estimator(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    monkeypatch.setattr(evidence_module, "estimate_generation_cost_usd", lambda **kwargs: calls.append(kwargs) or 0.01)
    state = RoutingEvidence()
    state.terminal(
        request_id=uuid4(), stream=False, status="success",
        result=ProviderResult(content="", provider="injected", model_version="alias-v2", prompt_version="v1", input_tokens=2, output_tokens=3),
    )
    event, = events(caplog)
    assert event["final_provider"] is None and event["final_model"] is None
    assert event["final_generation_estimated_cost_usd"] is None
    assert calls == []
