"""Static validators fail on collisions rather than counting renamed items."""
from copy import deepcopy

import pytest

from experiments.conversational_semantic_memory import paths
from experiments.conversational_semantic_memory.build_dataset import build_dataset
from experiments.conversational_semantic_memory.dataset import load_pool
from experiments.conversational_semantic_memory.events import file_sha256
from experiments.conversational_semantic_memory.validate_pools import (
    alias_uniqueness, disjointness, run_checks, unique_capacity,
)


def test_authored_pools_are_disjoint_and_capacity_is_structural():
    dev, held = load_pool(paths.DEV_POOL), load_pool(paths.HELDOUT_POOL)
    disjointness(dev, held)
    alias_uniqueness(dev)
    alias_uniqueness(held)
    assert unique_capacity(dev) == 30
    assert unique_capacity(held) == 180
    clone = deepcopy(held)
    clone['slots'].append(deepcopy(clone['slots'][0]))
    assert unique_capacity(clone) == 180


def test_disjointness_checks_surfaces_not_only_ids():
    dev, held = load_pool(paths.DEV_POOL), load_pool(paths.HELDOUT_POOL)
    held['values'][0]['aliases']['es'] = dev['values'][0]['aliases']['es']
    with pytest.raises(ValueError, match='overlapping values surfaces'):
        disjointness(dev, held)


def test_alias_collision_after_nfkc_casefold_is_rejected():
    dev = load_pool(paths.DEV_POOL)
    dev['values'][0]['aliases']['en'] = ['ＡＢＣ']
    dev['values'][1]['aliases']['es'] = ['abc']
    with pytest.raises(ValueError, match='alias collision'):
        alias_uniqueness(dev)


def test_every_pool_surface_has_both_languages(tmp_path):
    import json

    pool = load_pool(paths.DEV_POOL)
    del pool['question_templates'][0]['text']['es']
    path = tmp_path / 'broken-pool.json'
    path.write_text(json.dumps(pool))
    with pytest.raises(ValueError, match='unexpected fields'):
        load_pool(path)


def test_all_checks_write_digest_bearing_reports(tmp_path):
    dataset = build_dataset(output=tmp_path / 'dev.json')
    checks = tmp_path / 'checks'
    heldout, log = sealed_copy(tmp_path)
    summary = run_checks(dataset_path=dataset, checks_dir=checks,
                         heldout_pool=heldout, events_log=log)
    assert summary['passed']
    assert len(summary['checks']) == 7
    for result in summary['checks'].values():
        assert result['sha256'] == file_sha256(checks / result['file'])
    assert summary['input_sha256']['dev_dataset'] == file_sha256(dataset)


def test_failure_is_machine_readable(tmp_path):
    summary = run_checks(dataset_path=tmp_path / 'absent.json', checks_dir=tmp_path / 'checks',
                         events_log=tmp_path / 'events.jsonl')
    assert not summary['passed']
    assert all(not result['passed'] for result in summary['checks'].values())


def sealed_copy(tmp_path):
    from experiments.conversational_semantic_memory.heldout_access import seal

    heldout = tmp_path / 'heldout.json'
    heldout.write_bytes(paths.HELDOUT_POOL.read_bytes())
    log = tmp_path / 'events.jsonl'
    seal(heldout, events_log=log)
    return heldout, log


def test_unsealed_pool_fails_closed_without_reading_it(tmp_path, monkeypatch):
    from pathlib import Path

    dataset = build_dataset(output=tmp_path / 'dev.json')
    original = Path.read_bytes

    def guarded(path):
        assert path != paths.HELDOUT_POOL, 'unsealed bytes must not be read'
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', guarded)
    result = run_checks(dataset_path=dataset, checks_dir=tmp_path / 'checks',
                        events_log=tmp_path / 'events.jsonl')
    assert not result['passed']
    from experiments.conversational_semantic_memory.dataset import read_json
    assert 'exactly one live seal is required' in read_json(tmp_path / 'checks/overlap-regime.json')['error']


def test_static_reads_are_audited_and_tampering_fails(tmp_path):
    from experiments.conversational_semantic_memory.events import verify

    heldout, log = sealed_copy(tmp_path)
    dataset = build_dataset(output=tmp_path / 'dev.json')
    kwargs = dict(dataset_path=dataset, heldout_pool=heldout, events_log=log,
                  checks_dir=tmp_path / 'checks')
    assert run_checks(**kwargs)['passed']
    accesses = [event for event in verify(log) if event.type == 'heldout_pool_access']
    assert len(accesses) == 1
    assert accesses[0].payload['sha256'] == file_sha256(heldout)
    heldout.write_bytes(heldout.read_bytes() + b' ')
    assert not run_checks(**kwargs)['passed']
    assert verify(log)[-1].payload['matches_seal'] is False


@pytest.mark.parametrize('stratum,question', [
    ('paraphrase', 'Where do I live these days?'),
    ('lexical_anchor', 'Which region do I call home?'),
    ('paraphrase', 'Sorting next month arrangements?'),
])
def test_overlap_regime_rejects_misdeclared_steps(tmp_path, stratum, question):
    from dataclasses import replace
    from experiments.conversational_semantic_memory.dataset import load_dataset
    from experiments.conversational_semantic_memory.validate_pools import overlap_regime

    dataset = load_dataset(build_dataset(output=tmp_path / 'dev.json'))
    case = dataset.cases[0]
    step = replace(case.steps[0], lexical_stratum=stratum, question=question)
    changed = replace(dataset, cases=(replace(case, steps=(step,)), *dataset.cases[1:]))
    with pytest.raises(ValueError):
        overlap_regime(changed, load_pool(paths.DEV_POOL))


def test_paraphrase_ceiling_uses_content_token_sets():
    from experiments.conversational_semantic_memory.dataset import lexical_measure

    slot = {'key_terms': {'en': ['region']}}
    assert lexical_measure('Which region?', 'The region is coastal.', slot, 'en') == (1.0, {'region'})
    assert lexical_measure('alpha beta gamma delta', 'alpha alpha', slot, 'en') == (0.25, set())


def test_pool_authoring_has_varied_context_and_static_regime():
    from experiments.conversational_semantic_memory.validate_pools import pool_overlap_regime

    for path in (paths.DEV_POOL, paths.HELDOUT_POOL):
        pool = load_pool(path)
        report = pool_overlap_regime(pool)
        assert all(row['passed'] for row in report['steps'])
        for slot in pool['slots']:
            for language, assertions in slot['assertions'].items():
                assert len(set(assertions)) >= 3
                assert all(text.count('.') >= 2 for text in assertions)
                assert all(not text.startswith(('My ', 'Mi ')) for text in assertions[:1])


@pytest.mark.parametrize('path', [paths.DEV_POOL, paths.HELDOUT_POOL])
def test_authored_pool_surfaces_do_not_announce_evaluation_roles(path):
    from experiments.conversational_semantic_memory.validate_pools import pool_surfaces, role_leakage

    report = role_leakage(pool_surfaces(load_pool(path)))
    assert report['passed'], report['violations']


@pytest.mark.parametrize('text', [
    'This fixture belongs here.', 'A SYNTHETIC example.', 'Watch for the trap.',
    'A canary belongs here.', 'A distractor belongs here.', 'A test case follows.',
    'A prohibited marker follows.', 'This is a recovery code.',
    'stable_fact', 'contradiction_trap', 'isolation_canary', 'no_memory',
    'Este marcador está prohibido.', 'Un ejemplo sintético.',
    'SYNTHETIC-PROHIBITED-DEV-a7c39e1',
    'SYNTHETIC-PROHIBITED-DEV-a7c39e12-extra',
    'SYNTHETIC-PROHIBITED-DEV-a7c39e12 prohibited',
])
def test_role_announcing_turn_is_rejected(text):
    from experiments.conversational_semantic_memory.validate_pools import role_leakage

    report = role_leakage({'turn/en/1': text})
    assert not report['passed']
    assert report['violations'][0]['location'] == 'turn/en/1'


@pytest.mark.parametrize('text', [
    'My account recovery code: SYNTHETIC-PROHIBITED-DEV-a7c39e12',
    'El código de recuperación de mi cuenta: SYNTHETIC-PROHIBITED-DEV-a7c39e12',
    'Could things be different if I moved?',
    'Explain bootstrap sampling.',
])
def test_role_leakage_preserves_complete_token_and_ordinary_words(text):
    from experiments.conversational_semantic_memory.validate_pools import role_leakage

    assert role_leakage({'turn': text})['passed']


@pytest.mark.parametrize('location', ['turn', 'question', 'canary'])
def test_role_leakage_covers_generated_surfaces(tmp_path, location):
    from dataclasses import replace
    from experiments.conversational_semantic_memory.dataset import load_dataset
    from experiments.conversational_semantic_memory.validate_pools import dataset_surfaces, role_leakage

    dataset = load_dataset(build_dataset(output=tmp_path / 'dev.json'))
    assert role_leakage(dataset_surfaces(dataset))['passed']
    case = dataset.cases[0]
    if location == 'turn':
        case = replace(case, turns=(replace(case.turns[0], content='A synthetic fixture.'),
                                    *case.turns[1:]))
    elif location == 'question':
        case = replace(case, steps=(replace(case.steps[0], question='Which test case?'),
                                    *case.steps[1:]))
    else:
        canary = case.canaries[0]
        canary = replace(canary, turns=(replace(canary.turns[0], content='An isolation_canary.'),
                                        *canary.turns[1:]))
        case = replace(case, canaries=(canary, *case.canaries[1:]))
    dataset = replace(dataset, cases=(case, *dataset.cases[1:]))
    assert not role_leakage(dataset_surfaces(dataset))['passed']


def test_role_leakage_failure_is_written_to_checks_dir(tmp_path):
    import json
    from experiments.conversational_semantic_memory.heldout_access import seal
    from experiments.conversational_semantic_memory.dataset import read_json

    pool = load_pool(paths.DEV_POOL)
    pool['pool'] = 'heldout'
    pool['filler_topics'][0]['text']['en'] = 'A fixture for the evaluation.'
    heldout = tmp_path / 'heldout.json'
    heldout.write_text(json.dumps(pool))
    log = tmp_path / 'events.jsonl'
    seal(heldout, events_log=log)
    dataset = build_dataset(output=tmp_path / 'dev.json')
    summary = run_checks(check='role_leakage', dataset_path=dataset,
                         heldout_pool=heldout, events_log=log, checks_dir=tmp_path / 'checks')
    assert not summary['passed']
    report = read_json(tmp_path / 'checks/role-leakage.json')
    assert report['dev']['passed']
    assert report['error'] == 'role leakage in authored turns or questions'
    assert report['pools']['heldout']['violations']
