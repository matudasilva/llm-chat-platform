"""All dispatch seams use local fixtures or caches, never credentials."""
from dataclasses import replace

import pytest

from experiments.conversational_semantic_memory import events, run_t4
from experiments.conversational_semantic_memory.dataset import Case, Dataset, Message, Step
from experiments.conversational_semantic_memory.generation_client import GenerationClient, GenerationResult
from experiments.conversational_semantic_memory.embedding_client import EmbeddingClient


@pytest.fixture
def setup(tmp_path, monkeypatch):
    freeze = {
        't4_sub_cap_usd': '2.50', 'delta_NI': '0.10', 'delta_stale': '0.05',
        'settlement_requirement': 'provider reported usage',
        'pricing_snapshot': {'generation_model': run_t4.MODEL,
                             'usd_per_million_input_tokens': '0.15',
                             'usd_per_million_output_tokens': '0.60'},
        'tuning_grid': {'parameter_1': {'name': 'fact_similarity_threshold', 'values': ['0.30', '0.45', '0.60']},
                        'parameter_2': {'name': 'fact_top_n', 'values': ['1', '3', '5']},
                        'points': 9, 'nothing_else_is_tuned': True}}
    freeze_path = tmp_path / 'freeze.json'
    freeze_path.write_bytes(events.canonical_bytes(freeze))
    pool_path, dataset_path = tmp_path / 'pool.json', tmp_path / 'dataset.json'
    pool_path.write_text('{}')
    dataset_path.write_text('{}')
    cases = []
    for index, language in enumerate(('en', 'es')):
        turns = (Message(f'user-{language}', 1, 'user', 'My color is blue.'),
                 Message(f'assistant-{language}', 2, 'assistant', 'Understood.'))
        step = Step(f's-{language}', 'stable_fact', 2, 'Which color?', ('blue',), (),
                    (turns[0].message_id,), True, False, False, 'answer', 'lexical_anchor')
        cases.append(Case('case', language, 'tenant', f'00000000-0000-0000-0000-{index:012d}',
                          'stable_fact', 'color', ('blue',), 'question', (), turns, (step,), ()))
    dataset = Dataset(39, events.file_sha256(pool_path), tuple(cases))
    pool = {'pool': 'dev', 'values': [{'id': 'blue', 'aliases': {'en': ['blue'], 'es': ['blue']}}],
            'slots': [{'id': 'color', 'labels': {'en': 'color', 'es': 'color'}}],
            'prohibited_fixtures': ['SYNTHETIC-PROHIBITED-TEST-12345678']}
    monkeypatch.setattr(run_t4, 'load_dataset', lambda _: dataset)
    monkeypatch.setattr(run_t4, 'load_pool', lambda _: pool)
    log = tmp_path / 'events.jsonl'
    events.append(log, 'pre_dev_freeze', {'freeze_sha256': events.file_sha256(freeze_path)})
    return dict(events_log=log, ledger=tmp_path / 'ledger.jsonl', cache_dir=tmp_path / 'cache',
                checks_dir=tmp_path / 'checks', offline=True, env_file=tmp_path / 'MUST_NOT_READ',
                freeze_path=freeze_path, pool_path=pool_path, dataset_path=dataset_path)


def completion(request):
    text = '{"facts":[]}' if request.kind == 'extraction' else '{"decision":"answer","values":["blue"]}'
    return GenerationResult(text, {'prompt_tokens': 20, 'completion_tokens': 5}, True, run_t4.MODEL)


def test_tuning_selection_both_tie_breaks():
    candidates = [{'score': .5, 'top_n': n, 'threshold': t} for n in (5, 3, 1) for t in (.3, .45, .6)]
    assert run_t4.select_candidate(candidates) == {'score': .5, 'top_n': 1, 'threshold': .6}
    candidates.append({'score': .6, 'top_n': 5, 'threshold': .3})
    assert run_t4.select_candidate(candidates)['score'] == .6


@pytest.mark.parametrize('failure', ['missing', 'mismatch', 'pricing', 'prompt', 'cap'])
def test_fail_closed_before_client(setup, monkeypatch, failure):
    if failure in ('missing', 'mismatch'):
        setup['events_log'].unlink()
        if failure == 'mismatch':
            events.append(setup['events_log'], 'pre_dev_freeze', {'freeze_sha256': '0' * 64})
    elif failure == 'pricing':
        from experiments.conversational_semantic_memory.dataset import read_json
        freeze = read_json(setup['freeze_path'])
        del freeze['pricing_snapshot']
        setup['freeze_path'].write_bytes(events.canonical_bytes(freeze))
        setup['events_log'].unlink()
        events.append(setup['events_log'], 'pre_dev_freeze', {'freeze_sha256': events.file_sha256(setup['freeze_path'])})
    elif failure == 'prompt':
        monkeypatch.setattr(run_t4.validate_prompts, 'run_check', lambda **_: {'passed': False})
    else:
        events.append(setup['ledger'], 'reservation', {'call_id': 'bad', 'usd': '2.51'})
    def forbidden(**kwargs):
        pytest.fail('client built before prerequisite failure')
    monkeypatch.setattr(run_t4, 'GenerationClient', forbidden)
    with pytest.raises(ValueError):
        run_t4.run(**setup, stage='extraction')


def test_all_stages_and_cache_replay_without_dispatch(setup, monkeypatch):
    generation = GenerationClient(cache_dir=setup['cache_dir'] / 'generation', guard=None,
                                  model=run_t4.MODEL, offline=True)
    embeddings = EmbeddingClient(cache_dir=setup['cache_dir'] / 'embedding', guard=None, offline=True)
    calls = []
    def cached_completion(request):
        calls.append(request.kind)
        result = completion(request)
        (generation.cache_dir / f'{generation._key(request)}.json').write_bytes(events.canonical_bytes({
            'text': result.text, 'usage': result.usage, 'model': result.model}))
        return result
    def cached_embedding(request):
        (embeddings.cache_dir / f'{embeddings._key(request)}.json').write_text('{"vector":[1,0]}')
        return (1, 0)
    results = run_t4.run(**setup, embedding_cache_dir=embeddings.cache_dir,
                         complete=cached_completion, embed=cached_embedding)
    assert calls.count('extraction') == 2
    assert len(results['arms']['observations']) == 10
    assert len(results['tuning']['candidates']) == 9
    assert results['tuning']['selected'] == {'threshold': .6, 'top_n': 1, 'score': 1}
    files = [setup['checks_dir'] / f't4-{s}.json' for s in ('extraction', 'observations', 'tuning')]
    before = [f.read_bytes() for f in files]
    def forbidden(*args, **kwargs):
        pytest.fail('offline replay dispatched')
    monkeypatch.setattr(GenerationClient, '_dispatch', forbidden)
    import socket
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    actual_run = run_t4.run
    def cli_run(**kwargs):
        return actual_run(**dict(setup, **kwargs))
    monkeypatch.setattr(run_t4, 'run', cli_run)
    argv = ['--offline', '--stage', 'all',
            '--embedding-cache-dir', str(embeddings.cache_dir)]
    for name in ('events_log', 'ledger', 'cache_dir', 'checks_dir', 'env_file'):
        argv.extend(['--' + name.replace('_', '-'), str(setup[name])])
    assert run_t4.main(argv) == 0
    assert [f.read_bytes() for f in files] == before
    assert len([e for e in events.verify(setup['events_log']) if e.type.endswith('_complete')]) == 6


def test_live_mode_without_a_key_refuses_to_run(setup, tmp_path):
    """Live dispatch is explicit and still fails closed without a credential."""
    setup['offline'] = False
    setup['env_file'] = tmp_path / 'absent.env'
    with pytest.raises(ValueError, match='no API key'):
        run_t4.run(**setup)


def test_offline_never_reads_the_env_file(setup, tmp_path, monkeypatch):
    read = []
    original = run_t4.load_api_key
    monkeypatch.setattr(run_t4, 'load_api_key', lambda path: read.append(path) or original(path))
    setup['offline'] = True
    setup['env_file'] = tmp_path / 'never-read.env'
    setup['env_file'].write_text('OPENAI_API_KEY=sk-should-not-be-read\n')
    try:
        run_t4.run(**setup, stage='extraction', complete=lambda request: completion(request))
    except Exception:
        pass
    assert read == []


def test_cli_requires_choosing_offline_or_live():
    with pytest.raises(SystemExit):
        run_t4.main(['--offline', '--live'])
    with pytest.raises(SystemExit):
        run_t4.main([])


def test_model_and_usage_fail_closed(setup):
    for result in (GenerationResult('{"facts":[]}', None, True, run_t4.MODEL),
                   replace(completion(type('Request', (), {'kind': 'extraction'})()), model='other')):
        with pytest.raises(ValueError, match='usage|substitution'):
            run_t4.run(**setup, stage='extraction', complete=lambda _: result)


def test_freeze_must_precede_stages(setup):
    setup['events_log'].unlink()
    events.append(setup['events_log'], 't4_extraction_complete', {})
    events.append(setup['events_log'], 'pre_dev_freeze',
                  {'freeze_sha256': events.file_sha256(setup['freeze_path'])})
    with pytest.raises(ValueError, match='precede'):
        run_t4.run(**setup, stage='extraction')


def test_tampered_extraction_evidence_is_rejected(setup):
    run_t4.run(**setup, stage='extraction', complete=completion)
    path = setup['checks_dir'] / 't4-extraction.json'
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='completion evidence'):
        run_t4.run(**setup, stage='arms', complete=completion, embed=lambda _: (1, 0))


def test_extraction_snapshots_are_causal(setup):
    dataset = run_t4.load_dataset(setup['dataset_path'])
    case = dataset.cases[0]
    later = Message('later', 3, 'user', 'My color is red.')
    case = replace(case, turns=case.turns + (later,))
    seen = []
    def extract(request):
        import json
        turn = json.loads(request.messages[1]['content'])['turn']
        seen.append(turn['message_id'])
        value = 'red' if turn['message_id'] == 'later' else 'blue'
        text = json.dumps({'facts': [{'op': 'assert', 'slot_key': 'color', 'value': value,
                                     'kind': 'fact', 'source_message_ids': [turn['message_id']]}]})
        return replace(completion(request), text=text)
    result = run_t4._extraction(replace(dataset, cases=(case,)),
                                run_t4.load_pool(setup['pool_path']), extract)
    assert seen == ['user-en', 'later']
    snapshot = result['snapshots']['s-en']
    assert [f['value'] for f in snapshot['facts'] if f['status'] == 'active'] == ['blue']
    assert [f['value'] for f in result['fact_stores'][0]['facts'] if f['status'] == 'active'] == ['red']


def test_rendered_prompt_validation_precedes_completion(setup):
    dataset = run_t4.load_dataset(setup['dataset_path'])
    case = dataset.cases[0]
    case = replace(case, turns=(replace(case.turns[0], content='isolation_canary'),) + case.turns[1:])
    # Exercise the run wrapper with the altered in-memory fixture.
    from unittest.mock import patch
    with patch.object(run_t4, 'load_dataset', return_value=replace(dataset, cases=(case,))):
        with pytest.raises(ValueError, match='rendered prompt'):
            run_t4.run(**setup, stage='extraction',
                       complete=lambda _: pytest.fail('invalid prompt reached completion'))
