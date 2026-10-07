from __future__ import annotations

import dataclasses
import json
from decimal import Decimal

import httpx
import pytest

from experiments.conversational_semantic_memory import events, generation_client
from experiments.conversational_semantic_memory.generation_client import (
    GenerationClient,
    GenerationError,
    GenerationRequest,
    OfflineCacheMiss,
)
from experiments.conversational_semantic_memory.spend_guard import (
    Pricing,
    SpendGuard,
    SpendGuardError,
)

PRICING = Pricing(
    model="gpt-4o-mini-2024-07-18",
    input_usd_per_million=Decimal("0.15"),
    output_usd_per_million=Decimal("0.60"),
)


def make_guard(tmp_path, sub_cap="2.50"):
    return SpendGuard(
        tmp_path / "ledger.jsonl",
        stage="t4",
        ceiling_usd=Decimal("10"),
        sub_cap_usd=Decimal(sub_cap),
        pricing=PRICING,
    )


def request(text="what did I say my region was?", kind="generation"):
    return GenerationRequest(
        messages=({"role": "user", "content": text},),
        tenant_id="t1",
        conversation_id="c1",
        kind=kind,
        label="step-1",
        max_output_tokens=200,
    )


def client(tmp_path, guard=None, **kwargs):
    return GenerationClient(
        cache_dir=tmp_path / "cache",
        guard=guard,
        model="gpt-4o-mini-2024-07-18",
        **kwargs,
    )


def fake_response(monkeypatch, *, status=200, usage=None, text="ok", fail_times=0):
    calls = {"n": 0}

    class FakeClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            calls["n"] += 1
            if calls["n"] <= fail_times:
                return httpx.Response(503, json={})
            return httpx.Response(
                status,
                json={
                    "choices": [{"message": {"content": text}}],
                    "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 100},
                },
            )

    monkeypatch.setattr(generation_client.httpx, "Client", FakeClient)
    return calls


def test_cache_hit_costs_nothing(tmp_path, monkeypatch) -> None:
    guard = make_guard(tmp_path)
    c = client(tmp_path, guard, api_key="sk-test")
    fake_response(monkeypatch)
    first = c.complete(request())
    spent_after_first = guard.spent_usd()
    second = c.complete(request())
    assert (first.cached, second.cached) == (False, True)
    assert second.text == first.text
    assert guard.spent_usd() == spent_after_first
    assert c.calls == 1 and c.cache_hits == 1


def test_call_settles_at_reported_usage_not_the_reservation(tmp_path, monkeypatch) -> None:
    """Without this, byte-based reservations would exhaust the sub-cap."""
    guard = make_guard(tmp_path)
    c = client(tmp_path, guard, api_key="sk-test")
    fake_response(monkeypatch, usage={"prompt_tokens": 1000, "completion_tokens": 100})
    c.complete(request())
    expected = PRICING.cost(input_tokens=1000, output_tokens=100)
    assert guard.spent_usd() == expected
    # The reservation was strictly larger: bytes over-bound the token count.
    chain = events.verify(guard.ledger_path)
    reserved = Decimal(chain[0].payload["usd"])
    assert reserved > expected


def test_only_one_reservation_is_open_at_a_time(tmp_path, monkeypatch) -> None:
    guard = make_guard(tmp_path)
    c = client(tmp_path, guard, api_key="sk-test")
    fake_response(monkeypatch)
    for index in range(3):
        c.complete(request(text=f"question {index}"))
    chain = events.verify(guard.ledger_path)
    open_now = len([e for e in chain if e.type == "reservation"]) - len(
        [e for e in chain if e.type == "call_result"]
    )
    assert open_now == 0


def test_payload_failing_the_privacy_scan_is_never_dispatched(tmp_path, monkeypatch) -> None:
    guard = make_guard(tmp_path)
    c = client(tmp_path, guard, api_key="sk-test")
    calls = fake_response(monkeypatch)
    with pytest.raises(ValueError, match="payload scan failed"):
        c.complete(request(text="email me at jane.doe@example.com"))
    assert calls["n"] == 0
    assert events.verify(guard.ledger_path) == ()


def test_sub_cap_refusal_prevents_the_call(tmp_path, monkeypatch) -> None:
    guard = make_guard(tmp_path, sub_cap="0.0000001")
    c = client(tmp_path, guard, api_key="sk-test")
    calls = fake_response(monkeypatch)
    with pytest.raises(SpendGuardError):
        c.complete(request())
    assert calls["n"] == 0


def test_one_retry_then_failure_is_charged_and_raised(tmp_path, monkeypatch) -> None:
    guard = make_guard(tmp_path)
    c = client(tmp_path, guard, api_key="sk-test")
    calls = fake_response(monkeypatch, fail_times=5)
    with pytest.raises(GenerationError):
        c.complete(request())
    assert calls["n"] == generation_client.MAX_ATTEMPTS
    # A failed call keeps its reservation charged: unknown usage is never zero.
    assert guard.spent_usd() > 0


def test_retryable_status_succeeds_on_the_second_attempt(tmp_path, monkeypatch) -> None:
    guard = make_guard(tmp_path)
    c = client(tmp_path, guard, api_key="sk-test")
    calls = fake_response(monkeypatch, fail_times=1)
    assert c.complete(request()).text == "ok"
    assert calls["n"] == 2


def test_offline_miss_raises_instead_of_dispatching(tmp_path) -> None:
    c = client(tmp_path, None, offline=True)
    with pytest.raises(OfflineCacheMiss):
        c.complete(request())


def test_cache_key_separates_tenants_kinds_and_bodies(tmp_path) -> None:
    c = client(tmp_path, None, offline=True)
    base = request()
    other_tenant = dataclasses.replace(base, tenant_id="t2")
    other_kind = dataclasses.replace(base, kind="extraction")
    other_text = request(text="different question")
    keys = {c._key(base), c._key(other_tenant), c._key(other_kind), c._key(other_text)}
    assert len(keys) == 4


def test_live_dispatch_requires_guard_and_key(tmp_path) -> None:
    with pytest.raises(SpendGuardError, match="spend guard"):
        client(tmp_path, None, api_key="sk-test").complete(request())
    with pytest.raises(SpendGuardError, match="no API key"):
        client(tmp_path, make_guard(tmp_path)).complete(request())


def test_cached_payload_records_the_scanned_digest(tmp_path, monkeypatch) -> None:
    guard = make_guard(tmp_path)
    c = client(tmp_path, guard, api_key="sk-test")
    fake_response(monkeypatch)
    c.complete(request())
    cached = json.loads(next(iter((tmp_path / "cache").glob("*.json"))).read_text())
    ledger_sha = events.verify(guard.ledger_path)[0].payload["payload_sha256"]
    assert cached["payload_sha256"] == ledger_sha
