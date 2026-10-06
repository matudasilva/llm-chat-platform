from __future__ import annotations

import json
from decimal import Decimal

import pytest

from experiments.conversational_semantic_memory import events
from experiments.conversational_semantic_memory.embedding_client import (
    EmbeddingClient,
    EmbeddingRequest,
    OfflineCacheMiss,
    cosine,
    load_api_key,
)
from experiments.conversational_semantic_memory.spend_guard import (
    Pricing,
    SpendGuard,
    SpendGuardError,
)

PRICING = Pricing(model="text-embedding-3-small", input_usd_per_million=Decimal("0.02"))


def make_guard(tmp_path):
    return SpendGuard(
        tmp_path / "ledger.jsonl",
        stage="t3",
        ceiling_usd=Decimal("10"),
        sub_cap_usd=Decimal("0.25"),
        pricing=PRICING,
    )


def request(text="my flight leaves at dawn", tenant="t1", conversation="c1", role="turn"):
    return EmbeddingRequest(
        text=text, tenant_id=tenant, conversation_id=conversation, role=role
    )


def seed_cache(client: EmbeddingClient, req: EmbeddingRequest, vector) -> None:
    key = client._key(req)  # deliberate: the cache key is part of the contract
    (client.cache_dir / f"{key}.json").write_text(json.dumps({"vector": list(vector)}))


def test_cache_hit_never_reaches_the_guard_or_the_network(tmp_path) -> None:
    client = EmbeddingClient(cache_dir=tmp_path / "cache", guard=None, offline=True)
    req = request()
    seed_cache(client, req, [0.1, 0.2, 0.3])
    assert client.embed(req) == (0.1, 0.2, 0.3)
    assert client.calls == 0 and client.cache_hits == 1


def test_offline_miss_raises_instead_of_dispatching(tmp_path) -> None:
    client = EmbeddingClient(cache_dir=tmp_path / "cache", guard=None, offline=True)
    with pytest.raises(OfflineCacheMiss):
        client.embed(request())


def test_identical_text_under_two_tenants_gets_two_cache_entries(tmp_path) -> None:
    """A cache hit must never cross a tenant or conversation boundary (F3)."""
    client = EmbeddingClient(cache_dir=tmp_path / "cache", guard=None, offline=True)
    one = request(tenant="tenant-a")
    two = request(tenant="tenant-b")
    three = request(conversation="c2")
    assert len({client._key(one), client._key(two), client._key(three)}) == 3
    seed_cache(client, one, [1.0])
    with pytest.raises(OfflineCacheMiss):
        client.embed(two)


def test_model_and_role_are_part_of_the_key(tmp_path) -> None:
    client = EmbeddingClient(cache_dir=tmp_path / "cache", guard=None, offline=True)
    other_model = EmbeddingClient(
        cache_dir=tmp_path / "cache", guard=None, offline=True, model="other-model"
    )
    assert client._key(request()) != other_model._key(request())
    assert client._key(request(role="turn")) != client._key(request(role="fact"))


def test_live_dispatch_without_a_key_is_refused(tmp_path) -> None:
    client = EmbeddingClient(
        cache_dir=tmp_path / "cache", guard=make_guard(tmp_path), api_key=None
    )
    with pytest.raises(SpendGuardError, match="no API key"):
        client.embed(request())


def test_live_dispatch_without_a_guard_is_refused(tmp_path) -> None:
    client = EmbeddingClient(cache_dir=tmp_path / "cache", guard=None, api_key="sk-test")
    with pytest.raises(SpendGuardError, match="spend guard"):
        client.embed(request())


def test_a_payload_that_fails_the_privacy_scan_is_never_dispatched(tmp_path) -> None:
    guard = make_guard(tmp_path)
    client = EmbeddingClient(
        cache_dir=tmp_path / "cache", guard=guard, api_key="sk-test-not-used"
    )
    with pytest.raises(ValueError, match="payload scan failed"):
        client.embed(request(text="write to jane.doe@example.com about it"))
    # The scan runs before the reservation, so the ledger stays empty.
    assert events.verify(guard.ledger_path) == ()


def test_cosine_matches_hand_computed_values() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 1.0], [2.0, 2.0]) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        cosine([0.0, 0.0], [1.0, 0.0])


def test_load_api_key_reads_a_local_env_file(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text('OTHER=1\nOPENAI_API_KEY="sk-example-value"\n')
    assert load_api_key(env) == "sk-example-value"
    assert load_api_key(tmp_path / "absent.env") is None
