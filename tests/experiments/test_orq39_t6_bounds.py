"""Synthetic extremes verify the byte proofs against the unchanged extractor."""
from dataclasses import replace
import json

import httpx
import pytest

from experiments.conversational_semantic_memory.dataset import Case, Message
from experiments.conversational_semantic_memory.events import canonical_bytes
from experiments.conversational_semantic_memory.extraction import extraction_request
from experiments.conversational_semantic_memory.generation_client import GenerationResult
from experiments.conversational_semantic_memory.t6_bounds import (
    T6_EXTRACTION_RESPONSE_BYTES as R, T6ExtractionStopped, T6Extractor,
    accept_response, active_slots_json_bytes, extraction_payload_bytes,
    full_request_bytes, response_bounds,
)
from experiments.conversational_semantic_memory.cost_bound import CostBoundUnavailable


def case_fixture():
    turns = tuple(Message(f'm{i}', i, 'user', 'Preference: café.\n\x01')
                  for i in range(1, 5))
    return Case('case', 'es', 'tenant', 'conversation', 'update', 'color',
                (), '', (), turns, (), ())


def operation(turn, key='color', value='blue', op='assert'):
    return {'op': op, 'slot_key': key, 'value': value, 'kind': 'fact',
            'source_message_ids': [turn.message_id]}


def completion(text, cached=True):
    return GenerationResult(text, None, cached, 'stub')


@pytest.mark.parametrize('cached', [True, False])
@pytest.mark.parametrize('character', ['x', 'é', '😀'])
def test_boundary_counts_utf8_bytes_without_mutation(cached, character):
    text = character * (R // len(character.encode('utf-8')))
    result = completion(text, cached)
    assert accept_response(result) is result
    with pytest.raises(T6ExtractionStopped):
        accept_response(replace(result, text=text + 'x'))


@pytest.mark.parametrize('text', ['x' * (R + 1), '\ud800'])
@pytest.mark.parametrize('cached', [True, False])
def test_failure_latches_before_parser_or_store_advance(text, cached):
    case = case_fixture()
    calls = []
    def complete(request):
        calls.append(request)
        return completion(text, cached)
    extractor = T6Extractor(case, complete)
    before = extractor.store
    for _ in range(2):
        with pytest.raises(T6ExtractionStopped):
            extractor.extract(case.turns[0])
    assert extractor.store is before
    assert len(calls) == 1
    assert calls[0].max_output_tokens == 1024


def test_invalid_short_json_retains_existing_parser_behavior():
    extractor = T6Extractor(case_fixture(), lambda request: completion('not JSON'))
    result = extractor.extract(extractor.case.turns[0])
    assert result.non_conforming_count == 1
    assert result.store.last_sequence == 1
    assert not extractor.stopped


@pytest.mark.parametrize('p', [1, 2, 36])
def test_individual_bounds_follow_minimal_json_not_uuid_assumption(p):
    turn = Message('m' * p, 1, 'user', 'Synthetic preference.')
    raw = {'facts': [operation(turn, 'a', 'b')]}
    minimum = len(canonical_bytes(raw))
    bounds = response_bounds(p)
    assert minimum == 94 + p
    for field in ('slot_key', 'value'):
        raw['facts'][0][field] = 'a' * (R - minimum + 1)
        assert len(canonical_bytes(raw)) == R
        assert len(raw['facts'][0][field]) == bounds.key_bytes == bounds.value_bytes
        raw['facts'][0][field] = 'a'
    assert 11 + bounds.operations * (83 + p) <= R
    assert 11 + (bounds.operations + 1) * (83 + p) > R


@pytest.mark.parametrize('value', ['x', '\x00\n"\\', 'é😀', 'e\u0301'])
@pytest.mark.parametrize('ensure_ascii', [True, False])
def test_aggregate_charge_survives_lifecycle_and_nested_serialization(value, ensure_ascii):
    case = case_fixture()
    payloads = [
        {'facts': [operation(case.turns[0], f'slot_{i}', value) for i in range(30)]},
        {'facts': [operation(case.turns[1], 'slot_0', value)]},
        {'facts': [operation(case.turns[2], 'slot_0', value + 'new')]},
        {'facts': [operation(case.turns[3], 'slot_1', None, 'retract')]},
    ]
    texts = [json.dumps(p, ensure_ascii=ensure_ascii) for p in payloads]
    iterator = iter(texts)
    extractor = T6Extractor(case, lambda request: completion(next(iterator)))
    actual_charge = 0
    for j, (turn, text) in enumerate(zip(case.turns, texts)):
        request = extraction_request(extractor.store, case, turn)
        inner = extraction_payload_bytes(j, len(turn.content.encode()), turn.message_id)
        assert len(request.messages[1]['content'].encode()) <= inner
        bound = full_request_bytes(request, 'stub', {1: inner})
        body = {'model': 'stub', 'messages': list(request.messages),
                'temperature': 0, 'max_tokens': 1024,
                'response_format': {'type': 'json_object'}}
        assert len(canonical_bytes(body)) <= bound
        assert len(httpx.Request('POST', 'https://offline.invalid', json=body).content) <= bound
        extractor.extract(turn)
        actual_charge += len(text.encode())
        active = {f.slot_key: f.value for f in extractor.store.facts if f.status == 'active'}
        assert len(canonical_bytes(active)) <= 2 + actual_charge
        assert len(canonical_bytes(active)) <= active_slots_json_bytes(j + 1)


def test_near_limit_response_charges_total_once():
    case = case_fixture()
    turn = case.turns[0]
    payload = {'facts': [operation(turn, 'a', 'b')]}
    payload['facts'][0]['value'] = 'v' * (R - len(canonical_bytes(payload)) + 1)
    text = canonical_bytes(payload).decode()
    assert len(text) == R
    extractor = T6Extractor(case, lambda request: completion(text))
    result = extractor.extract(turn)
    active = {f.slot_key: f.value for f in result.store.facts}
    assert len(canonical_bytes(active)) <= 2 + R
    assert active_slots_json_bytes(2) - active_slots_json_bytes(1) == R


@pytest.mark.parametrize('bad', [None, True, -1, 1.5])
def test_missing_counts_fail_closed(bad):
    with pytest.raises(CostBoundUnavailable):
        active_slots_json_bytes(bad)
    with pytest.raises(CostBoundUnavailable):
        extraction_payload_bytes(0, bad, 'm1')
