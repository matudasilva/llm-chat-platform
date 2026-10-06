"""Pressure is tested through the real grouping, bounding and packing path."""
import asyncio
from dataclasses import replace

from experiments.conversational_semantic_memory.build_dataset import build_dataset
from experiments.conversational_semantic_memory.dataset import load_dataset
from experiments.conversational_semantic_memory.events import file_sha256, verify
from experiments.conversational_semantic_memory.validate_pressure import check_step, run_check

LIMITS = {'conversation_history_max_messages': 20,
          'conversation_history_max_chars': 12000,
          'chat_prompt_max_added_context_chars': 12000}


def test_all_semantic_sources_are_outside_real_window_and_event_binds_inputs(tmp_path):
    dataset = build_dataset(output=tmp_path / 'dev.json')
    log = tmp_path / 'events.jsonl'
    checks = tmp_path / 'checks'
    result = run_check(dataset_path=dataset, checks_dir=checks, event_log=log)
    assert result['passed']
    assert result['semantic_steps'] == 60
    event, = verify(log)
    assert event.type == 'oow_check_dev'
    assert event.payload['dataset_sha256'] == file_sha256(dataset)
    assert event.payload['result_sha256'] == file_sha256(checks / 'out-of-window-check-dev.json')
    assert event.payload['passed'] is True


def test_gold_turn_inside_window_fails(tmp_path):
    case = load_dataset(build_dataset(output=tmp_path / 'dev.json')).cases[0]
    step = replace(case.steps[0], after_sequence=2)
    result = asyncio.run(check_step(case, step, **LIMITS))
    assert not result['passed']
    assert result['overlap_sequences'] == [1, 2]
    assert result['delivered_source_sequences'] == [1]


def test_later_copy_of_excluded_source_fails_delivery_check(tmp_path):
    case = load_dataset(build_dataset(output=tmp_path / 'dev.json')).cases[0]
    turns = list(case.turns)
    turns[-2] = replace(turns[-2], content=turns[0].content)
    case = replace(case, turns=tuple(turns))
    result = asyncio.run(check_step(case, case.steps[0], **LIMITS))
    assert not result['passed']
    assert result['overlap_sequences'] == []
    assert result['delivered_source_sequences'] == [1]


def test_failed_pressure_report_records_failure(tmp_path):
    from experiments.conversational_semantic_memory.dataset import read_json
    from experiments.conversational_semantic_memory.events import canonical_bytes

    path = build_dataset(output=tmp_path / 'dev.json')
    raw = read_json(path)
    for case in raw['cases'][:2]:
        case['steps'][0]['after_sequence'] = 2
    path.write_bytes(canonical_bytes(raw))
    log = tmp_path / 'events.jsonl'
    result = run_check(dataset_path=path, checks_dir=tmp_path / 'checks', event_log=log)
    assert not result['passed']
    assert sum(not step['passed'] for step in result['steps']) == 2
    event, = verify(log)
    assert event.payload['passed'] is False
    assert event.payload['dataset_sha256'] == file_sha256(path)


def test_declared_defaults_ignore_environment(tmp_path, monkeypatch):
    from app.core.settings import Settings
    from experiments.conversational_semantic_memory.validate_pressure import declared_limits

    expected = {name: Settings.model_fields[name].default for name in LIMITS}
    for name in LIMITS:
        monkeypatch.setenv(name.upper(), '1')
        monkeypatch.setenv(name, '2')
    assert declared_limits() == expected
    result = run_check(dataset_path=build_dataset(output=tmp_path / 'dev.json'),
                       checks_dir=tmp_path / 'checks', event_log=tmp_path / 'events.jsonl')
    assert result['limits'] == expected
    assert result['passed']


def test_budget_binding_uses_real_cap_and_binds_report_digest(tmp_path, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError('pressure checks must remain offline')

    monkeypatch.setattr(socket, 'create_connection', no_network)
    path = build_dataset(output=tmp_path / 'dev.json')
    log = tmp_path / 'events.jsonl'
    checks = tmp_path / 'checks'
    result = run_check(dataset_path=path, checks_dir=checks, event_log=log,
                       check='budget_binding')
    assert result['passed']
    assert result['semantic_steps'] == 60
    for row in result['steps']:
        assert 2 * row['cap'] <= row['corpus_chars'] <= 3 * row['cap']
        assert row['window_chars'] < row['cap']
        assert row['pre_cap_chars'] > row['cap']
        assert 0 < row['delivered_units'] < row['corpus_units']
    event, = verify(log)
    assert event.type == 'budget_binding_dev'
    assert event.payload == {'dataset_sha256': file_sha256(path), 'passed': True,
                             'result_sha256': file_sha256(checks / 'budget-binding-dev.json')}


def test_small_corpus_does_not_pass_budget_binding_vacuously(tmp_path):
    case = load_dataset(build_dataset(output=tmp_path / 'dev.json')).cases[0]
    # Keep a real, nonempty excluded corpus, but shrink its neutral turns.
    case = replace(case, turns=tuple(replace(m, content='A brief science question.'
                                            if m.role == 'user' else 'Noted.')
                                    for m in case.turns))
    row = asyncio.run(check_step(case, case.steps[0], check='budget_binding', **LIMITS))
    assert row['corpus_units'] > row['delivered_units'] > 0
    assert row['pre_cap_chars'] < row['cap']
    assert not row['passed']
    empty = asyncio.run(check_step(case, replace(case.steps[0], after_sequence=2),
                                  check='budget_binding', **LIMITS))
    assert empty['corpus_units'] == 0
    assert not empty['passed']


def test_zero_delivered_evidence_fails_even_when_budget_binds(tmp_path):
    case = load_dataset(build_dataset(output=tmp_path / 'dev.json')).cases[0]
    # Leave room for a short raw fact, but not its rendered evidence envelope.
    turns = case.turns[:-20] + tuple(
        replace(m, content='x' * 1184 if m.role == 'user' else 'Noted.')
        for m in case.turns[-20:])
    case = replace(case, turns=turns)
    row = asyncio.run(check_step(case, case.steps[0], check='budget_binding', **LIMITS))
    assert row['window_chars'] == 11900
    assert row['pre_cap_chars'] > row['cap']
    assert row['corpus_units'] > 0
    assert row['delivered_units'] == 0
    assert row['conditions'] == {'budget_binds': True, 'selection_is_real': True,
                                 'evidence_is_not_starved': False}
    assert not row['passed']
