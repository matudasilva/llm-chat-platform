"""Dataset checks use temporary artifacts so clean clones need no run evidence."""
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from experiments.conversational_semantic_memory import paths
from experiments.conversational_semantic_memory.build_dataset import build_dataset
from experiments.conversational_semantic_memory.dataset import (
    FAMILIES, load_dataset, parse_case, read_json, validate_pairing,
)


def test_build_is_byte_identical_and_never_reads_heldout(tmp_path, monkeypatch):
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.resolve() == paths.HELDOUT_POOL.resolve():
            raise AssertionError('dev builder opened held-out pool')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guarded)
    first = build_dataset(seed=19, output=tmp_path / 'first.json')
    second = build_dataset(seed=19, output=tmp_path / 'second.json')
    assert first.read_bytes() == second.read_bytes()
    dataset = load_dataset(first)
    assert dataset.seed == 19
    assert len(dataset.cases) == 60
    for family in FAMILIES:
        assert sum(c.family == family for c in dataset.cases) == (12 if family == 'update' else 6)


def test_structural_duplicate_under_different_id_is_detected(tmp_path):
    dataset = load_dataset(build_dataset(output=tmp_path / 'dev.json'))
    clone = replace(dataset.cases[0], conceptual_case_id=str(UUID(int=999)))
    with pytest.raises(ValueError, match='structural duplicate'):
        validate_pairing(dataset.cases + (clone,))


def test_pairing_requires_exactly_one_of_each_language(tmp_path):
    dataset = load_dataset(build_dataset(output=tmp_path / 'dev.json'))
    with pytest.raises(ValueError, match='one-to-one'):
        validate_pairing(dataset.cases[:-1])
    changed = replace(dataset.cases[-1], language='en')
    with pytest.raises(ValueError, match='one-to-one'):
        validate_pairing(dataset.cases[:-1] + (changed,))


@pytest.mark.parametrize('mutation,reason', [
    ('role', 'invalid role'), ('sequence', 'noncontiguous'),
    ('source', 'unknown source'), ('scope', 'target scope'),
    ('gold', 'unknown value'), ('extra', 'unexpected fields'),
])
def test_strict_schema_rejects_invalid_records(tmp_path, mutation, reason):
    raw = read_json(build_dataset(output=tmp_path / 'dev.json'))['cases'][0]
    if mutation == 'role':
        raw['turns'][0]['role'] = 'system'
    elif mutation == 'sequence':
        raw['turns'][0]['sequence'] = 99
    elif mutation == 'source':
        raw['steps'][0]['gold_source_message_ids'] = [str(UUID(int=999))]
    elif mutation == 'scope':
        raw['canaries'][0]['conversation_id'] = raw['conversation_id']
    elif mutation == 'gold':
        raw['steps'][0]['gold_values'] = ['unknown']
    else:
        raw['surprise'] = True
    with pytest.raises(ValueError, match=reason):
        parse_case(raw)


def test_update_variants_and_canaries_are_explicit(tmp_path):
    dataset = load_dataset(build_dataset(output=tmp_path / 'dev.json'))
    updates = [c for c in dataset.cases if c.family == 'update' and c.language == 'en']
    assert len(updates) == 6
    assert sum(c.steps[0].gold_decision == 'abstain' for c in updates) == 2
    assert all(c.steps[0].stale_eligible for c in updates)
    for case in dataset.cases:
        assert sum(c.tenant_id == case.tenant_id for c in case.canaries) == 1
        assert all(c.conversation_id != case.conversation_id for c in case.canaries)


def test_every_case_has_semantic_step_and_h3_is_family_scoped(tmp_path):
    dataset = load_dataset(build_dataset(output=tmp_path / 'dev.json'))
    for case in dataset.cases:
        assert any(step.semantic for step in case.steps)
        for step in case.steps:
            assert step.h3 == (step.family in ('no_memory', 'historical'))
            assert not (step.h3 and step.semantic)


def test_translations_share_strata_and_each_family_is_balanced(tmp_path):
    from collections import Counter

    dataset = load_dataset(build_dataset(output=tmp_path / 'dev.json'))
    for language in ('en', 'es'):
        steps = [s for c in dataset.cases if c.language == language for s in c.steps if s.semantic]
        assert Counter(s.lexical_stratum for s in steps) == {'lexical_anchor': 15, 'paraphrase': 15}
        for family in FAMILIES:
            counts = Counter(s.lexical_stratum for c in dataset.cases
                             if c.language == language and c.family == family
                             for s in c.steps if s.semantic)
            assert abs(counts['lexical_anchor'] - counts['paraphrase']) <= 1
    case = dataset.cases[1]
    changed = replace(case, steps=(replace(case.steps[0], lexical_stratum='paraphrase'),))
    with pytest.raises(ValueError, match='paired step semantics'):
        validate_pairing((dataset.cases[0], changed))
