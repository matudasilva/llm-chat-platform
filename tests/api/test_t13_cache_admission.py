from __future__ import annotations

import json
import hashlib
import uuid

import pytest

import app.api.deps as deps
import app.api.routes.chat as route
from app.core.domain.provider import ProviderResult
from app.core.domain.types import ChatMessage
from app.core.settings import settings
from app.schemas.chat import ChatRequest
from app.services.chat_cache_policy import cache_bypass_reason, execution_configuration_id
from app.services.chat_response_cache import ChatResponseCache
from tests.api.test_chat_response_cache import (
    FakeAsyncSession, FakeCache, FakeChatService, _DictRedis, _chat_service_result,
)


def test_cache_policy_precedence_and_legacy_configurations():
    cfg = settings.model_copy(deep=True)
    cfg.chat_rag_augmentation_enabled = False
    cfg.ebm25_enabled = False
    for policy in ("static", "heuristic"):
        cfg.routing_policy = policy
        for provider in ("stub", "openai", "bedrock"):
            cfg.provider = provider
            cfg.fallback_provider = None
            assert cache_bypass_reason(cfg) is None
    cfg.routing_policy = "deterministic"
    assert cache_bypass_reason(cfg) is not None
    cfg.routing_policy = "static"
    cfg.provider = "vertex"
    assert cache_bypass_reason(cfg) is not None
    cfg.provider, cfg.fallback_provider = "openai", "vertex"
    assert cache_bypass_reason(cfg) is not None
    cfg.ebm25_enabled = True
    assert cache_bypass_reason(cfg) == "ebm25_memory"
    cfg.chat_rag_augmentation_enabled = True
    assert cache_bypass_reason(cfg) == "rag_augmentation"


def test_service_composition_owns_deep_snapshot(monkeypatch):
    captured = {}
    def resolver(cfg):
        captured['resolver'] = cfg
        return object()
    def context(cfg):
        captured['context'] = cfg
        return object()
    class Service:
        def __init__(self, **kwargs):
            captured.update(kwargs)
    monkeypatch.setattr(deps, 'build_provider_resolver', resolver)
    monkeypatch.setattr(deps, 'build_routing_context_builder', context)
    monkeypatch.setattr(deps, 'ChatService', Service)
    deps.get_chat_service()
    snapshot = captured['resolver']
    assert snapshot is captured['context'] and snapshot is not settings
    assert captured['execution_configuration_id'] == execution_configuration_id(snapshot)
    old = snapshot.openai_model
    monkeypatch.setattr(settings, 'openai_model', 'changed')
    assert snapshot.openai_model == old
    assert captured['timeout_s'] == snapshot.provider_timeout_s


@pytest.mark.asyncio
@pytest.mark.parametrize('initial,after', [
    ('static', 'deterministic'), ('deterministic', 'static'), ('static', 'static'),
])
async def test_generation_transitions_only_write_when_bound_to_initial_scope(monkeypatch, initial, after):
    monkeypatch.setattr(settings, 'routing_policy', initial)
    cache = FakeCache()
    monkeypatch.setattr(route, 'get_chat_response_cache', lambda: cache)
    class TransitionService(FakeChatService):
        async def run(self, **kwargs):
            monkeypatch.setattr(settings, 'routing_policy', after)
            return await super().run(**kwargs)
    service = TransitionService()
    response = await route.chat(ChatRequest(message='hi'), db=FakeAsyncSession(), chat_service=service)
    assert response.status == route.ChatStatus.success
    assert cache.reads == (1 if initial == 'static' else 0)
    assert cache.writes == (1 if initial == after == 'static' else 0)


@pytest.mark.asyncio
async def test_stale_hit_is_discarded_and_no_hit_evidence(monkeypatch):
    cache = FakeCache(hit_result=_chat_service_result(request_id=uuid.uuid4(), content='stale'))
    original = cache.get
    async def changed(**kwargs):
        result = await original(**kwargs)
        monkeypatch.setattr(settings, 'openai_model', 'changed-during-read')
        return result
    cache.get = changed
    events = []
    monkeypatch.setattr(route, 'emit_cache_hit_evidence', lambda **kw: events.append(kw))
    monkeypatch.setattr(route, 'get_chat_response_cache', lambda: cache)
    service = FakeChatService(content='fresh')
    response = await route.chat(ChatRequest(message='hi'), db=FakeAsyncSession(), chat_service=service)
    assert response.assistant_content == 'fresh'
    assert service.run_calls == 1 and cache.writes == 0 and events == []


@pytest.mark.asyncio
async def test_unbound_and_mismatched_services_bypass(monkeypatch):
    cache = FakeCache(hit_result=_chat_service_result(request_id=uuid.uuid4(), content='stale'))
    monkeypatch.setattr(route, 'get_chat_response_cache', lambda: cache)
    for binding in (None, 'mismatch'):
        service = FakeChatService(execution_configuration_id=binding)
        response = await route.chat(ChatRequest(message='hi'), db=FakeAsyncSession(), chat_service=service)
        assert response.status == route.ChatStatus.success and service.run_calls == 1
    assert cache.reads == cache.writes == 0


@pytest.mark.asyncio
async def test_post_commit_configuration_change_prevents_write(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(route, 'get_chat_response_cache', lambda: cache)
    class Transaction:
        async def __aenter__(self): return self
        async def __aexit__(self, *args):
            monkeypatch.setattr(settings, 'openai_model', 'changed-at-commit')
    class Session(FakeAsyncSession):
        def begin(self): return Transaction()
    response = await route.chat(ChatRequest(message='hi'), db=Session(), chat_service=FakeChatService())
    assert response.status == route.ChatStatus.success
    assert cache.reads == 1 and cache.writes == 0


@pytest.mark.asyncio
async def test_cache_hit_usage_unknown_and_malformed_usage_stays_miss(monkeypatch):
    from app.services import chat_response_cache as module
    redis = _DictRedis()
    monkeypatch.setattr(module, 'redis_client', redis)
    cache = ChatResponseCache()
    messages = [ChatMessage(role='user', content='hi')]
    result = _chat_service_result(request_id=uuid.uuid4(), content='cached')
    await cache.set(messages=messages, result=result, tenant_id='a')
    hit = await cache.get(request_id=uuid.uuid4(), messages=messages, tenant_id='a')
    assert hit.assistant_message.content == 'cached'
    assert hit.provider_result.provider == result.provider_result.provider
    assert (hit.provider_result.input_tokens, hit.provider_result.output_tokens,
            hit.provider_result.total_tokens, hit.provider_result.latency_ms) == (None, None, None, None)
    assert await cache.get(request_id=uuid.uuid4(), messages=messages, tenant_id='b') is None
    key = cache._cache_key(messages=messages, tenant_id='a')
    payload = json.loads(redis.store[key])
    payload['provider_result']['input_tokens'] = 'bad'
    redis.store[key] = json.dumps(payload)
    assert await cache.get(request_id=uuid.uuid4(), messages=messages, tenant_id='a') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['openai_model', 'routing_message_length_cheap_max', 'routing_estimated_tokens_smart_min'])
async def test_aba_generation_uses_owned_snapshot(monkeypatch, field):
    import app.core.domain.provider_factory as factory
    original = getattr(settings, field)
    transient = original + 1 if isinstance(original, int) else 'transient-model'
    seen = []
    cache = FakeCache()
    async def change_before_generation(**kwargs):
        cache.reads += 1
        monkeypatch.setattr(settings, field, transient)
        return None
    cache.get = change_before_generation
    class Provider:
        provider_name = 'stub'
        async def generate(self, provider_input):
            monkeypatch.setattr(settings, field, original)
            return ProviderResult(content='owned snapshot', provider='stub', model_version='stub-model',
                                  prompt_version='v1', input_tokens=1, output_tokens=1,
                                  total_tokens=2, latency_ms=1)
    def build(provider, cfg, **kwargs):
        seen.append((getattr(cfg, field), getattr(settings, field), cfg is settings))
        return Provider()
    monkeypatch.setattr(factory, '_build_single_provider', build)
    monkeypatch.setattr(route, 'get_chat_response_cache', lambda: cache)
    service = deps.get_chat_service()
    response = await route.chat(ChatRequest(message='hi'), db=FakeAsyncSession(), chat_service=service)
    assert response.assistant_content == 'owned snapshot'
    assert seen == [(original, transient, False)]
    assert cache.reads == cache.writes == 1


@pytest.mark.asyncio
async def test_accepted_hit_evidence_is_best_effort(monkeypatch):
    cache = FakeCache(hit_result=_chat_service_result(request_id=uuid.uuid4(), content='cached'))
    monkeypatch.setattr(route, 'get_chat_response_cache', lambda: cache)
    called = []
    def fail(**kwargs):
        called.append(kwargs)
        raise RuntimeError('telemetry unavailable')
    monkeypatch.setattr(route, 'emit_cache_hit_evidence', fail)
    service = FakeChatService()
    response = await route.chat(ChatRequest(message='hi'), db=FakeAsyncSession(), chat_service=service)
    assert response.assistant_content == 'cached' and service.run_calls == 0
    assert len(called) == 1 and called[0]['source_result'] is not None


@pytest.mark.asyncio
async def test_static_cache_rollback_and_hit_usage_event(monkeypatch):
    from app.models.usage_event import UsageEvent
    from app.services import chat_response_cache as module
    redis = _DictRedis()
    monkeypatch.setattr(module, 'redis_client', redis)
    cache = ChatResponseCache()
    monkeypatch.setattr(route, 'get_chat_response_cache', lambda: cache)
    monkeypatch.setattr(settings, 'routing_policy', 'static')
    class Session(FakeAsyncSession):
        def __init__(self):
            super().__init__()
            self.usage = []
        def add(self, obj):
            super().add(obj)
            if isinstance(obj, UsageEvent): self.usage.append(obj)
    request = ChatRequest(message='rollback')
    await route.chat(request, db=Session(), chat_service=FakeChatService(content='original'))
    monkeypatch.setattr(settings, 'routing_policy', 'deterministic')
    service = FakeChatService(content='bypass')
    bypassed = await route.chat(request, db=Session(), chat_service=service)
    assert bypassed.assistant_content == 'bypass' and service.run_calls == 1
    monkeypatch.setattr(settings, 'routing_policy', 'static')
    db = Session()
    service = FakeChatService(content='unexpected')
    hit = await route.chat(request, db=db, chat_service=service)
    assert hit.assistant_content == 'original' and service.run_calls == 0
    assert len(db.usage) == 1
    assert (db.usage[0].input_tokens, db.usage[0].output_tokens, db.usage[0].total_tokens) == (0, 0, 0)


@pytest.mark.parametrize('field', ['routing_message_length_cheap_max', 'routing_estimated_tokens_smart_min'])
@pytest.mark.asyncio
async def test_threshold_changes_discard_stale_hits_and_prevent_generation_and_commit_writes(monkeypatch, field):
    original = getattr(settings, field)
    for phase in ('hit', 'generation', 'commit'):
        monkeypatch.setattr(settings, field, original)
        cache = FakeCache(hit_result=_chat_service_result(request_id=uuid.uuid4(), content='stale') if phase == 'hit' else None)
        monkeypatch.setattr(route, 'get_chat_response_cache', lambda: cache)
        if phase == 'hit':
            get = cache.get
            async def changed_get(**kwargs):
                result = await get(**kwargs)
                monkeypatch.setattr(settings, field, original + 1)
                return result
            cache.get = changed_get
        class Service(FakeChatService):
            async def run(self, **kwargs):
                if phase == 'generation':
                    monkeypatch.setattr(settings, field, original + 1)
                return await super().run(**kwargs)
        class Transaction:
            async def __aenter__(self): return self
            async def __aexit__(self, *args):
                if phase == 'commit':
                    monkeypatch.setattr(settings, field, original + 1)
        class Session(FakeAsyncSession):
            def begin(self): return Transaction()
        service = Service(content='fresh')
        response = await route.chat(ChatRequest(message='hi'), db=Session(), chat_service=service)
        assert response.assistant_content == 'fresh'
        assert service.run_calls == 1 and cache.reads == 1 and cache.writes == 0


@pytest.mark.asyncio
async def test_legacy_key_cold_miss_and_static_heuristic_static_isolation(monkeypatch):
    from app.services import chat_response_cache as module
    redis = _DictRedis()
    monkeypatch.setattr(module, 'redis_client', redis)
    cache = ChatResponseCache()
    messages = [ChatMessage(role='user', content='same')]
    monkeypatch.setattr(settings, 'routing_policy', 'static')
    await cache.set(messages=messages, tenant_id='a', result=_chat_service_result(request_id=uuid.uuid4(), content='static'))
    legacy = {'messages': [{'role': 'user', 'content': 'same'}]}
    for name in ('provider', 'fallback_provider', 'openai_model', 'bedrock_model', 'bedrock_prompt_version', 'stub_provider_mode'):
        legacy[name] = getattr(settings, name)
    digest = hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    redis.store[f'chat:response:b:{digest}'] = next(iter(redis.store.values()))
    assert await cache.get(request_id=uuid.uuid4(), messages=messages, tenant_id='b') is None
    monkeypatch.setattr(settings, 'routing_policy', 'heuristic')
    assert await cache.get(request_id=uuid.uuid4(), messages=messages, tenant_id='a') is None
    await cache.set(messages=messages, tenant_id='a', result=_chat_service_result(request_id=uuid.uuid4(), content='heuristic'))
    monkeypatch.setattr(settings, 'routing_policy', 'static')
    hit = await cache.get(request_id=uuid.uuid4(), messages=messages, tenant_id='a')
    assert hit.assistant_message.content == 'static'


@pytest.mark.parametrize(('field', 'low', 'high', 'message'), [
    ('routing_message_length_cheap_max', 4, 5, 'hello'),
    ('routing_estimated_tokens_smart_min', 4, 5, 'sixteen chars!!!'),
])
def test_threshold_crosses_real_heuristic_decision_and_cache_identity(monkeypatch, field, low, high, message):
    from app.core.domain.routing.heuristic_routing_policy import HeuristicRoutingPolicy
    from app.core.domain.provider import ProviderInput
    from app.services.routing_signals import build_routing_context_builder
    monkeypatch.setattr(settings, 'routing_policy', 'heuristic')
    monkeypatch.setattr(settings, 'routing_message_length_cheap_max', 0)
    monkeypatch.setattr(settings, 'routing_estimated_tokens_smart_min', 100)
    cache = ChatResponseCache()
    messages = [ChatMessage(role='user', content=message)]
    monkeypatch.setattr(settings, 'provider', 'stub')
    context = build_routing_context_builder(settings)(provider_input=ProviderInput(request_id=uuid.uuid4(), messages=messages), stream=False)
    def identity(value):
        monkeypatch.setattr(settings, field, value)
        policy = HeuristicRoutingPolicy(primary_provider='stub', primary_model='a', fallback_provider='openai', fallback_model='b', message_length_cheap_max=settings.routing_message_length_cheap_max, estimated_tokens_smart_min=settings.routing_estimated_tokens_smart_min)
        return policy.decide(context), cache._cache_key(messages=messages, tenant_id='a'), execution_configuration_id(settings)
    first, second = identity(low), identity(high)
    assert first[0].rationale != second[0].rationale
    if field == 'routing_estimated_tokens_smart_min':
        assert (first[0].provider, second[0].provider) == ('openai', 'stub')
    else:
        # The cheap boundary changes the tier and rationale, not the provider.
        assert first[0].provider == second[0].provider == 'stub'
    assert first[1] != second[1] and first[2] != second[2]


@pytest.mark.parametrize(('field', 'before', 'after'), [
    ('openai_api_key', None, 'test-credential'),
    ('bedrock_region', 'us-east-1', 'us-west-2'),
])
@pytest.mark.asyncio
async def test_routing_input_change_separates_cache_and_discards_stale_hit(monkeypatch, field, before, after):
    monkeypatch.setattr(settings, 'provider', 'openai' if field == 'openai_api_key' else 'bedrock')
    monkeypatch.setattr(settings, 'routing_policy', 'heuristic')
    monkeypatch.setattr(settings, field, before)
    cache = ChatResponseCache()
    messages = [ChatMessage(role='user', content='hello')]
    first_key = cache._cache_key(messages=messages, tenant_id='a')
    first_binding = execution_configuration_id(settings)
    service = FakeChatService(content='fresh')
    fake = FakeCache(hit_result=_chat_service_result(request_id=uuid.uuid4(), content='stale'))
    get = fake.get
    async def change_during_read(**kwargs):
        result = await get(**kwargs)
        monkeypatch.setattr(settings, field, after)
        return result
    fake.get = change_during_read
    monkeypatch.setattr(route, 'get_chat_response_cache', lambda: fake)
    response = await route.chat(ChatRequest(message='hello'), db=FakeAsyncSession(), chat_service=service)
    assert response.assistant_content == 'fresh' and service.run_calls == 1 and fake.writes == 0
    assert cache._cache_key(messages=messages, tenant_id='a') != first_key
    assert execution_configuration_id(settings) != first_binding


def test_credential_material_and_identity_are_not_in_cache_configuration(monkeypatch):
    from app.services.chat_cache_policy import cache_configuration
    monkeypatch.setattr(settings, 'provider', 'openai')
    monkeypatch.setattr(settings, 'openai_api_key', 'first-secret')
    first = cache_configuration(settings)
    monkeypatch.setattr(settings, 'openai_api_key', 'second-secret')
    assert cache_configuration(settings) == first
    assert 'first-secret' not in json.dumps(first)


@pytest.mark.parametrize(('field', 'before', 'after'), [
    ('provider', 'stub', 'openai'),
    ('fallback_provider', None, 'bedrock'),
    ('openai_model', 'model-a', 'model-b'),
    ('bedrock_model', 'model-a', 'model-b'),
    ('bedrock_prompt_version', 'v1', 'v2'),
    ('bedrock_region', 'us-east-1', 'us-west-2'),
    ('stub_provider_mode', 'ok', 'error'),
    ('routing_policy', 'static', 'heuristic'),
    ('routing_message_length_cheap_max', 80, 81),
    ('routing_estimated_tokens_smart_min', 120, 121),
])
def test_each_configured_cache_identity_field_separates_keys_and_bindings(
    monkeypatch, field, before, after,
):
    cache = ChatResponseCache()
    messages = [ChatMessage(role='user', content='same request')]
    # Keep derived availability true for both stub and OpenAI when testing provider.
    if field == 'provider':
        monkeypatch.setattr(settings, 'openai_api_key', 'test-credential')
    monkeypatch.setattr(settings, field, before)
    before_key = cache._cache_key(messages=messages, tenant_id='tenant-a')
    before_binding = execution_configuration_id(settings)
    monkeypatch.setattr(settings, field, after)
    assert cache._cache_key(messages=messages, tenant_id='tenant-a') != before_key
    assert execution_configuration_id(settings) != before_binding


def test_cache_identity_separates_tenants_and_messages():
    cache = ChatResponseCache()
    first = [ChatMessage(role='user', content='first')]
    second = [ChatMessage(role='user', content='second')]
    baseline = cache._cache_key(messages=first, tenant_id='tenant-a')
    assert cache._cache_key(messages=first, tenant_id='tenant-b') != baseline
    assert cache._cache_key(messages=second, tenant_id='tenant-a') != baseline
