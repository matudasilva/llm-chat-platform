"""Stub completions exercise the full extraction boundary without dispatch."""
from dataclasses import replace
import json

import pytest

from experiments.conversational_semantic_memory.dataset import Case, Message
from experiments.conversational_semantic_memory.extraction import (
    EXTRACTOR_VERSION, EXTRACTION_PROMPT, extract_turn, extraction_request,
)
from experiments.conversational_semantic_memory.extraction_metrics import (
    GoldFact, LifecycleExpectation, aggregate_metrics, score_extraction,
)
from experiments.conversational_semantic_memory.facts import FactStore
from experiments.conversational_semantic_memory.generation_client import GenerationResult, OfflineCacheMiss


def fixture_case():
    turns = tuple(Message(f'm{i}', i, 'user', text) for i, text in enumerate(
        ('I prefer blue.', 'I prefer BLUE.', 'I prefer red.', 'Forget my color.',
         'Forget my color again.'), 1))
    return Case('case', 'en', 'tenant', 'conversation', 'update', 'color', (), '', (), turns, (), ())


def operation(turn, value='blue', op='assert', kind='preference'):
    return dict(op=op, slot_key='color', value=value, kind=kind,
                source_message_ids=[turn.message_id])


def complete_payload(payload):
    return lambda request: GenerationResult(json.dumps(payload), None, True, 'stub')


def store():
    return FactStore('tenant', 'conversation', EXTRACTOR_VERSION)


@pytest.mark.parametrize('text', ['not JSON', '```json\n{}\n```', '{"facts":[],"facts":[]}',
                                  '{"facts": NaN}', '[]', '{"facts":{}}'])
def test_nonconforming_is_counted_never_repaired(text):
    calls = []
    def complete(request):
        calls.append(request)
        return GenerationResult(text, None, True, 'stub')
    case = fixture_case()
    result = extract_turn(store(), case, case.turns[0], complete)
    assert len(calls) == 1
    assert result.non_conforming_count == result.rejected_count == 1
    assert result.store.facts == ()
    assert result.store.last_sequence == 1
    assert calls[0].response_format == {'type': 'json_object'}
    assert calls[0].messages[0]['content'] == EXTRACTION_PROMPT


@pytest.mark.parametrize('change', [
    {'source_message_ids': ['m2']}, {'source_message_ids': []},
    {'source_message_ids': ['m1', 'm1']}, {'slot_key': 'Color'},
    {'kind': 'stable_fact'}, {'kind': []}, {'op': []}, {'value': None},
    {'op': 'retract', 'value': 'blue'}, {'extra': True},
])
def test_invalid_operation_is_rejected(change):
    case = fixture_case()
    payload = operation(case.turns[0]) | change
    result = extract_turn(store(), case, case.turns[0], complete_payload({'facts': [payload]}))
    assert result.rejected_count == result.non_conforming_count == 1
    assert not result.store.facts


def test_lifecycle_and_metrics():
    case = fixture_case()
    current = store()
    runs = []
    for turn, value, op in zip(case.turns, ('blue', ' BLUE ', 'red', None, None),
                               ('assert', 'assert', 'assert', 'retract', 'retract')):
        result = extract_turn(current, case, turn,
                              complete_payload({'facts': [operation(turn, value, op)]}))
        runs.append(result)
        current = result.store
    assert len(runs[1].store.facts) == 1
    assert runs[1].store.facts[0].source_message_ids == ('m1', 'm2')
    old, new = current.facts
    assert old.status == 'superseded' and old.superseded_by == new.fact_id
    assert new.supersedes == old.fact_id and new.status == 'retracted'
    assert current.audit[0].reason == 'retract_without_active_fact'
    metrics = score_extraction(current.facts, (
        GoldFact('color', 'blue', eligible=False, source_message_ids=('m1', 'm2')),
        GoldFact('color', 'red', eligible=False, source_message_ids=('m3',))), tenant_id='tenant', conversation_id='conversation',
        user_message_ids=('m1', 'm2', 'm3', 'm4', 'm5'), runs=runs,
        lifecycle=(LifecycleExpectation('color', 'blue', 'superseded', 'red'),
                   LifecycleExpectation('color', 'red', 'retracted')))
    assert metrics['supersession_correctness'] == metrics['retraction_correctness'] == 1
    assert metrics['precision'] is None
    metrics = score_extraction(runs[1].store.facts, (GoldFact('COLOR', 'blue', source_message_ids=('m1', 'm2')),),
        tenant_id='tenant', conversation_id='conversation', user_message_ids=('m1', 'm2'))
    assert metrics['precision'] == metrics['recall'] == metrics['f1'] == 1
    assert metrics['duplicate_rate'] == 0 and metrics['provenance_completeness'] == 1


def test_causal_scope_and_slots_only():
    case = fixture_case()
    result = extract_turn(store(), case, case.turns[0],
                          complete_payload({'facts': [operation(case.turns[0])]}))
    request = extraction_request(result.store, case, case.turns[1])
    assert json.loads(request.messages[1]['content']) == {
        'active_slots': {'color': 'blue'},
        'turn': {'message_id': 'm2', 'content': 'I prefer BLUE.'}}
    for field in ('tenant_id', 'conversation_id'):
        with pytest.raises(ValueError, match='scope'):
            extraction_request(replace(result.store, **{field: 'foreign'}), case, case.turns[1])
        foreign = replace(result.store.facts[0], **{field: 'foreign'})
        with pytest.raises(ValueError, match='foreign'):
            extraction_request(replace(result.store, facts=(foreign,)), case, case.turns[1])
    with pytest.raises(ValueError, match='skip'):
        extraction_request(store(), case, case.turns[1])
    with pytest.raises(ValueError):
        extraction_request(result.store, case, case.turns[0])
    with pytest.raises(ValueError):
        extraction_request(store(), case, replace(case.turns[0], role='assistant'))


def test_prohibited_and_partial_rejections_are_audited():
    case = fixture_case()
    result = extract_turn(store(), case, case.turns[0], complete_payload({'facts': [
        operation(case.turns[0], kind='prohibited'), {}, operation(case.turns[0])]}))
    assert result.rejected_count == 2
    assert [entry.reason for entry in result.store.audit] == ['validation_rejection'] * 2
    assert [entry.op_index_within_extraction for entry in result.store.audit] == [0, 1]
    assert result.store.audit[0].detail == 'unknown kind'
    assert len(result.store.facts) == 1
    metrics = score_extraction(result.store.facts, (GoldFact('color', 'blue', prohibited=True),),
        tenant_id='tenant', conversation_id='conversation', user_message_ids=('m1',), runs=(result,))
    assert metrics['prohibited_extraction_count'] == 1
    assert metrics['non_conforming_count'] == 1
    assert metrics['false_positive'] == 1


def test_cache_miss_propagates_without_retry():
    case = fixture_case()
    calls = []
    def miss(request):
        calls.append(request)
        raise OfflineCacheMiss('fixture cache miss')
    with pytest.raises(OfflineCacheMiss):
        extract_turn(store(), case, case.turns[0], miss)
    assert len(calls) == 1


def test_prompt_version_is_frozen():
    from experiments.conversational_semantic_memory.extraction import EXTRACTION_PROMPT_SHA256

    assert EXTRACTOR_VERSION == 'orq39-extraction-v2'
    assert EXTRACTION_PROMPT_SHA256 == '94bf25f2a2fb74737f58c0d710548f5693daffc16b67e138ce36fbbb55e14ec5'


def test_metrics_missing_gold_duplicates_and_incomplete_provenance():
    case = fixture_case()
    run = extract_turn(store(), case, case.turns[0],
                       complete_payload({'facts': [operation(case.turns[0])]}))
    fact = run.store.facts[0]
    duplicate = replace(fact, fact_id='duplicate', source_message_ids=('m1', 'assistant'))
    metrics = score_extraction((fact, duplicate),
        (GoldFact('color', 'blue', source_message_ids=('m1',)),
         GoldFact('size', 'large', source_message_ids=('m2',))),
        tenant_id='tenant', conversation_id='conversation', user_message_ids=('m1',),
        lifecycle=(LifecycleExpectation('color', 'blue', 'retracted'),))
    assert metrics['true_positive'] == metrics['false_negative'] == 1
    assert metrics['false_positive'] == 0
    assert metrics['precision'] == 1 and metrics['recall'] == 0.5
    assert metrics['f1'] == pytest.approx(2 / 3)
    assert metrics['duplicate_rate'] == metrics['provenance_completeness'] == 0.5
    assert metrics['retraction_correctness'] == 0
    assert metrics['supersession_correctness'] is None


def test_future_provenance_is_rejected_before_completion():
    case = fixture_case()
    run = extract_turn(store(), case, case.turns[0],
                       complete_payload({'facts': [operation(case.turns[0])]}))
    fact = replace(run.store.facts[0], source_message_ids=('m3',))
    with pytest.raises(ValueError, match='provenance'):
        extraction_request(replace(run.store, facts=(fact,)), case, case.turns[1])


@pytest.mark.parametrize('word', ['contradiction_trap', 'isolation_canary', 'distractor',
                                  'no_memory', 'historical', 'duplicate', 'stable_fact',
                                  'prohibited'])
def test_prompt_does_not_leak_case_families(word):
    assert word not in EXTRACTION_PROMPT.casefold()


@pytest.mark.parametrize('kind', ['fact', 'preference', 'constraint', 'decision', 'goal'])
@pytest.mark.parametrize('include_runs', [False, True])
def test_prohibited_metrics_match_normalized_gold_value_without_kind_or_slot(kind, include_runs):
    case = fixture_case()
    run = extract_turn(store(), case, case.turns[0], complete_payload({'facts': [
        operation(case.turns[0], value='  SYNTHETIC-PROHIBITED-ABC-1234abcd  ', kind=kind)]}))
    metrics = score_extraction(run.store.facts,
        (GoldFact('different_slot', 'synthetic-prohibited-abc-1234ABCD', prohibited=True),),
        tenant_id='tenant', conversation_id='conversation', user_message_ids=('m1',),
        runs=(run,) if include_runs else ())
    assert metrics['prohibited_extraction_count'] == 1
    assert run.rejected_count == 0


def extracted_fact():
    case = fixture_case()
    return extract_turn(store(), case, case.turns[0],
        complete_payload({'facts': [operation(case.turns[0])]})).store.facts[0]


def score(facts, gold, **kwargs):
    return score_extraction(facts, gold, tenant_id='tenant', conversation_id='conversation',
                            user_message_ids=('m1', 'm2', 'm3'), **kwargs)


def test_golden_alias_provenance_matching_and_key_drift():
    fact = extracted_fact()
    gold = (GoldFact('color', 'blue', source_message_ids=('m1',), aliases=('blue', 'azure')),
            GoldFact('region', 'coast', source_message_ids=('m2',)),
            GoldFact('size', 'large', source_message_ids=('m3',)))
    facts = (replace(fact, slot_key='shade', value='ＡＺＵＲＥ'),
             replace(fact, fact_id='region', slot_key='region', value='coast',
                     source_message_ids=('m2',)),
             replace(fact, fact_id='wrong', value='red'))
    result = score(facts, gold)
    assert (result['true_positive'], result['false_positive'], result['false_negative']) == (2, 1, 1)
    assert result['precision'] == result['recall'] == result['f1'] == pytest.approx(2 / 3)
    assert result['slot_key_drift_rate'] == 0.5
    assert result['slot_key_collision_count'] == result['duplicate_rate'] == 0
    assert aggregate_metrics([result, result])['slot_key_drift_rate'] == 0.5
    assert aggregate_metrics([result, result])['true_positive'] == 4


@pytest.mark.parametrize('change', [dict(value='red'), dict(source_message_ids=('m2',)),
                                   dict(source_message_ids=()), dict(tenant_id='foreign'),
                                   dict(conversation_id='foreign')])
def test_same_key_without_value_and_provenance_match_is_false_positive(change):
    result = score((replace(extracted_fact(), **change),),
                   (GoldFact('color', 'blue', source_message_ids=('m1',)),))
    assert result['true_positive'] == 0
    assert result['false_positive'] == result['false_negative'] == 1
    assert result['slot_key_drift_rate'] is None


def test_paraphrased_duplicate_under_different_key():
    fact = extracted_fact()
    result = score((fact, replace(fact, fact_id='duplicate', slot_key='shade', value='azure')),
        (GoldFact('color', 'blue', source_message_ids=('m1',), aliases=('blue', 'azure')),))
    assert result['true_positive'] == 1 and result['false_positive'] == 0
    assert result['duplicate_rate'] == result['slot_key_drift_rate'] == 0.5
    assert result['slot_key_collision_count'] == 1


def test_one_extracted_key_covering_two_gold_slots_is_collision():
    fact = extracted_fact()
    result = score((fact, replace(fact, fact_id='region', value='coast', source_message_ids=('m2',))),
        (GoldFact('color', 'blue', source_message_ids=('m1',)),
         GoldFact('region', 'coast', source_message_ids=('m2',))))
    assert result['true_positive'] == 2
    assert result['slot_key_collision_count'] == 1
    assert result['duplicate_rate'] == 0


def test_drifted_lifecycle_requires_provenance_status_and_reciprocal_links():
    fact = extracted_fact()
    prior = replace(fact, slot_key='shade', status='superseded', superseded_by='successor')
    successor = replace(fact, fact_id='successor', slot_key='hue', value='scarlet',
                        source_sequence=3, source_message_ids=('m3',), supersedes=fact.fact_id)
    gold = (GoldFact('color', 'blue', eligible=False, source_message_ids=('m1',)),
            GoldFact('color', 'red', source_message_ids=('m3',), aliases=('red', 'scarlet')))
    lifecycle = (LifecycleExpectation('color', 'blue', 'superseded', 'red'),)
    assert score((prior, successor), gold, lifecycle=lifecycle)['supersession_correctness'] == 1
    for broken in (replace(successor, supersedes=None),
                   replace(successor, source_message_ids=('m2',))):
        assert score((prior, broken), gold, lifecycle=lifecycle)['supersession_correctness'] == 0
    assert score((replace(prior, status='active'), successor), gold,
                 lifecycle=lifecycle)['supersession_correctness'] == 0
    retracted = replace(prior, status='retracted', superseded_by=None)
    expectation = (LifecycleExpectation('color', 'blue', 'retracted'),)
    assert score((retracted,), gold, lifecycle=expectation)['retraction_correctness'] == 1
    assert score((replace(retracted, source_message_ids=('m2',)),), gold,
                 lifecycle=expectation)['retraction_correctness'] == 0


def test_snapshot_preserves_aliases_and_lifecycle_provenance():
    from experiments.conversational_semantic_memory.dataset import Step
    from experiments.conversational_semantic_memory.extraction_metrics import gold_snapshot, lifecycle_gold

    case = fixture_case()
    step = Step('step', 'update', 3, 'Which color?', ('new',), ('old',), ('m3',),
                True, False, True, 'answer', 'lexical_anchor')
    case = replace(case, steps=(step,))
    aliases = {'old': ('blue', 'azure'), 'new': ('red', 'scarlet')}
    current, = gold_snapshot(case, step, aliases)
    prior, = lifecycle_gold(case, step, aliases)
    assert current.aliases == ('red', 'scarlet')
    assert current.source_message_ids == ('m3',)
    assert prior.source_message_ids == ('m1',) and not prior.eligible
    assert prior.aliases == ('blue', 'azure')
    missing = replace(case, turns=(replace(case.turns[0], content='No assertion.'),) + case.turns[1:])
    assert lifecycle_gold(missing, step, aliases)[0].source_message_ids == ()


def test_empty_aggregate_keeps_undefined_rates():
    result = aggregate_metrics([])
    assert result['true_positive'] == result['slot_key_collision_count'] == 0
    assert result['precision'] is result['slot_key_drift_rate'] is result['duplicate_rate'] is None
