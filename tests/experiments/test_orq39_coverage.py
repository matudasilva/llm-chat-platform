"""Hand-computed coverage distinguishes provenance, lifecycle and case weights."""
from dataclasses import replace

import pytest

from experiments.conversational_semantic_memory.coverage import (
    Observation, coverage, delta_cov, isolation_counts, summarize,
)
from experiments.conversational_semantic_memory.dataset import Case, Message, Step
from experiments.conversational_semantic_memory.retrieval import Delivery, Item


def fixture():
    messages = (Message('u', 1, 'user', 'blue'), Message('a', 2, 'assistant', 'noted'),
                Message('u2', 3, 'user', 'blue again'), Message('a2', 4, 'assistant', 'noted'))
    step = Step('step', 'duplicate', 4, 'color?', ('blue',), ('red',), ('u', 'u2'),
                True, False, True, 'answer', 'paraphrase')
    case = Case('case', 'en', 'tenant', 'conversation', 'duplicate', 'color', ('blue', 'red'),
                'template', (), messages, (step,), ())
    turn = Item('tenant', 'conversation', '1', 2, 'blue\nnoted', ('u', 'a'))
    return case, step, turn


def delivery(arm, *items):
    return Delivery(arm, items, (), '', False, 0)


@pytest.mark.parametrize('arm', ['A', 'B'])
def test_turn_coverage_requires_every_complete_gold_source_turn(arm):
    case, step, turn = fixture()
    other = replace(turn, item_id='3', source_sequence=4, source_message_ids=('u2', 'a2'))
    assert coverage(case, step, delivery(arm, turn), {}) == 0
    assert coverage(case, step, delivery(arm, turn, other), {}) == 1
    assert coverage(case, step, delivery('A', replace(turn, source_message_ids=('u',)), other), {}) == 0
    stale = replace(turn, item_id='stale', content='red')
    assert coverage(case, step, delivery('A', turn, other, stale), {}) == 1


def test_fact_coverage_requires_active_matching_value_and_provenance():
    case, step, turn = fixture()
    fact = replace(turn, kind='fact', value='BLUE', source_message_ids=('u', 'u2'))
    aliases = {'blue': ('blue', 'azure')}
    assert coverage(case, step, delivery('C-ORACLE', fact), aliases) == 1
    for bad in (replace(fact, status='superseded'), replace(fact, value='red'),
                replace(fact, source_message_ids=('u',)), replace(fact, tenant_id='foreign'),
                replace(fact, source_sequence=5), replace(fact, effective_until=4)):
        assert coverage(case, step, delivery('C-ORACLE', bad), aliases) == 0
    assert coverage(case, step, delivery('C-ORACLE', fact, replace(fact, value='red')), aliases) == 1
    assert coverage(case, step, delivery('C-ORACLE', turn), aliases) == 0


def test_isolation_counts_are_independent():
    case, _, turn = fixture()
    assert isolation_counts(case, delivery('A', replace(turn, tenant_id='foreign'),
        replace(turn, conversation_id='sibling'))) == {'cross_tenant': 1, 'cross_conversation': 1}


def test_delta_cov_case_weighted_paired_fixture():
    rows = []
    # First case: four paired steps, differences [1, 1, 0, 0] => 0.5.
    # Second case: two paired steps, differences [-1, -1] => -1.
    # Mean of cases = -0.25, unlike the pooled-step mean of zero.
    for case, language, step, a, c, stratum in (
        ('one', 'en', '1', 0, 1, 'paraphrase'), ('one', 'es', '2', 0, 1, 'paraphrase'),
        ('one', 'en', '3', 1, 1, 'lexical_anchor'), ('one', 'es', '4', 1, 1, 'lexical_anchor'),
        ('two', 'en', '5', 1, 0, 'paraphrase'), ('two', 'es', '6', 1, 0, 'paraphrase')):
        rows.extend(Observation(case, language, stratum, step, arm, value)
                    for arm, value in [('A', a), ('C-ORACLE', c)])
    assert delta_cov(rows) == -0.25
    result = summarize(rows)
    assert result['delta_cov_per_language'] == {'en': -0.25, 'es': -0.25}
    assert result['delta_cov_per_stratum'] == {'lexical_anchor': 0, 'paraphrase': 0}
    with pytest.raises(ValueError, match='missing paired'):
        delta_cov(rows[:-1])


def test_empty_gold_retraction_has_no_fact_coverage():
    case, step, turn = fixture()
    step = replace(step, gold_values=(), gold_decision='abstain')
    assert coverage(case, step, delivery('C-ORACLE'), {}) == 0
    # Coverage measures the source, not whether generation would abstain.
    step = replace(step, gold_source_message_ids=('u',))
    assert coverage(case, step, delivery('A', turn), {}) == 1
