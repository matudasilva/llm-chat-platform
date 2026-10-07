"""Hermetic retrieval gates exercise the pooled boundary and real packing."""
from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from app.core.domain.provider_prompt import render_memory_events_block
from experiments.conversational_semantic_memory import events, paths, run_t3
from experiments.conversational_semantic_memory.build_dataset import build_dataset
from experiments.conversational_semantic_memory.coverage import isolation_counts
from experiments.conversational_semantic_memory.dataset import load_dataset, load_pool
from experiments.conversational_semantic_memory.embedding_client import EmbeddingClient, OfflineCacheMiss
from experiments.conversational_semantic_memory.retrieval import (
    Item, PooledStore, RetrievalConfig, pack_delivery, rank_dense, retrieve,
)


@pytest.fixture
def dataset_path(tmp_path):
    return build_dataset(seed=39, output=tmp_path / 'dev.json')


@pytest.fixture
def data(dataset_path):
    return load_dataset(dataset_path), load_pool(paths.DEV_POOL)


def test_prefilter_before_similarity(data, monkeypatch):
    dataset, _ = data
    case = dataset.cases[0]
    step = next(s for s in case.steps if s.semantic)
    good = Item(case.tenant_id, case.conversation_id, '1', 1, 'good', ('source',))
    bad = [replace(good, tenant_id='foreign', content='highest'),
           replace(good, conversation_id='sibling', content='highest'),
           replace(good, source_sequence=step.after_sequence + 1, content='highest'),
           replace(good, status='superseded', content='highest'),
           replace(good, effective_from=step.after_sequence + 1, content='highest')]
    embedded, scored = [], []

    def embed(request):
        embedded.append(request.text)
        return (1.0, 0.0) if request.text != 'good' else (0.5, 0.5)

    from experiments.conversational_semantic_memory import retrieval
    original = retrieval.cosine

    def score(left, right):
        scored.append(right)
        return original(left, right)

    monkeypatch.setattr(retrieval, 'cosine', score)
    assert rank_dense([*bad, good], case=case, step=step, embed=embed,
                      config=RetrievalConfig()) == (good,)
    assert 'highest' not in embedded
    assert scored == [(0.5, 0.5)]


def test_real_dataset_pooled_isolation(data):
    dataset, pool = data
    store = PooledStore.from_dataset(dataset, pool)
    assert len({i.tenant_id for i in store.items}) > 1
    assert len({i.conversation_id for i in store.items}) > len(dataset.cases)
    for case in dataset.cases:
        for step in case.steps:
            if step.semantic:
                for delivery in retrieve(store, case, step, lambda _: (1.0, 0.0)):
                    assert isolation_counts(case, delivery) == {'cross_tenant': 0, 'cross_conversation': 0}
                    assert sum(len(m.content) for m in delivery.window) + len(delivery.rendered_evidence) <= 12000


@pytest.mark.parametrize('arm', ['C', 'C-ORACLE'])
@pytest.mark.parametrize('retained_count', [1, 2, 3])
def test_episodic_dropped_before_facts_newest_selected_first(arm, retained_count):
    turn = Item('tenant', 'conversation', '1', 2, 'episodic evidence', ('u', 'a'))
    fact = replace(turn, item_id='fact', kind='fact', content='derived fact', value='value')
    turns = (turn, replace(turn, item_id='3', source_sequence=4))
    facts = (fact, replace(fact, item_id='other-fact', source_sequence=4))
    # Derive boundaries from the actual envelope, including provenance overhead.
    full = pack_delivery(arm, (), (), turns, facts, question='q', max_chars=12000)
    from app.core.domain.chat_memory import RetrievedMemoryEvent
    selected = facts + turns
    rendered = [RetrievedMemoryEvent(
        int(item.item_id) if item.kind == 'turn' else 4 + index,
        item.content if item.kind == 'turn' else events.canonical_bytes({
            'statement': item.content, 'value': item.value,
            'source_message_ids': item.source_message_ids, 'status': item.status,
        }).decode('utf-8')).provider_dict() for index, item in enumerate(selected)]
    cap = len(render_memory_events_block(rendered[:retained_count]))
    assert len(full.rendered_evidence) > cap
    delivery = pack_delivery(arm, (), (), turns, facts, question='q', max_chars=cap)
    assert delivery.items == selected[:retained_count]
    assert delivery.budget_binding
    assert delivery.facts_dropped == max(0, 2 - retained_count)
    assert len(delivery.rendered_evidence) == cap


def test_oracle_retains_a_fact_when_one_fits_under_binding_cap():
    turn = Item('tenant', 'conversation', '1', 2, 'episodic evidence' * 100, ('u', 'a'))
    fact = replace(turn, item_id='fact', kind='fact', content='color: blue', value='blue')
    delivery = pack_delivery('C-ORACLE', (), (), (turn,), (fact,), question='q', max_chars=1000)
    assert delivery.budget_binding
    assert delivery.items == (fact,)
    assert delivery.facts_dropped == 0
    assert len(delivery.rendered_evidence) <= 1000


@pytest.mark.parametrize('arm', ['A', 'B'])
@pytest.mark.parametrize('cap', [0, 1, 8, 500, 1000, 12000])
def test_fact_free_arms_match_previous_packing_bytes(arm, cap):
    from app.core.domain.added_context_budget import enforce_added_context_cap
    from app.core.domain.chat_memory import ChatMemoryContext, RetrievedMemoryEvent
    from app.core.domain.rag_generation import RagGenerationContext
    from app.core.domain.types import ChatMessage

    window = tuple(ChatMessage(role=role, content=role * 20)
                   for role in ('user', 'assistant', 'user', 'assistant'))
    turns = tuple(Item('t', 'c', str(n), n + 1, 'evidence' * 40, (str(n),))
                  for n in (1, 3, 5))
    # With no facts, the previous path passed selection order straight to the cap.
    memory = ChatMemoryContext(messages=window, retrieved_events=tuple(
        RetrievedMemoryEvent(int(item.item_id), item.content) for item in turns))
    expected, _, _ = enforce_added_context_cap(
        memory_context=memory, rag_context=RagGenerationContext(), current_message='q', max_chars=cap)
    actual = pack_delivery(arm, window, (), turns, (), question='q', max_chars=cap)
    rendered = (render_memory_events_block([e.provider_dict() for e in expected.retrieved_events])
                if expected.retrieved_events else '')
    assert actual.rendered_evidence.encode('utf-8') == rendered.encode('utf-8')
    assert actual.window == expected.messages
    assert actual.items == turns[:len(expected.retrieved_events)]
    assert actual.facts_dropped == 0
    assert actual.budget_binding == (sum(len(m.content) for m in window)
        + len(render_memory_events_block([e.provider_dict() for e in memory.retrieved_events])) > cap)


def test_arm_a_matches_runtime_selection(data):
    from app.core.domain import bm25_ranking
    from app.core.domain.added_context_budget import enforce_added_context_cap
    from app.core.domain.chat_memory import ChatMemoryContext, RetrievedMemoryEvent
    from app.core.domain.rag_generation import RagGenerationContext
    from app.core.domain.retrieval_corpus import RetrievalCorpus
    from experiments.conversational_semantic_memory.retrieval import _partition
    from experiments.conversational_semantic_memory.validate_pressure import declared_limits
    import asyncio

    dataset, pool = data
    case = dataset.cases[0]
    step = next(s for s in case.steps if s.semantic)
    store = PooledStore.from_dataset(dataset, pool)
    limits = declared_limits()
    partition = asyncio.run(_partition([i for i in store.scoped(case, step) if i.kind == 'turn'], case, limits))
    from app.core.domain.context_packer import pack_recent_window

    memory = ChatMemoryContext.from_partition(partition, truncated=False)
    memory = replace(memory, messages=pack_recent_window(
        memory.messages, max_chars=limits['chat_prompt_max_added_context_chars']).messages)
    selected, _ = bm25_ranking.pack_selected_events(
        bm25_ranking.rank_events(RetrievalCorpus.from_partition(partition).events,
                                 bm25_ranking.query_tokens(step.question)),
        max_chars=limits['chat_prompt_max_added_context_chars'] - sum(len(m.content) for m in memory.messages))
    memory = replace(memory, retrieved_events=tuple(
        RetrievedMemoryEvent(e.event_id, e.document_text) for e in selected))
    expected, _, _ = enforce_added_context_cap(memory_context=memory, rag_context=RagGenerationContext(),
        current_message=step.question, max_chars=limits['chat_prompt_max_added_context_chars'])
    actual = retrieve(store, case, step, lambda _: (1.0, 0.0))[0]
    assert actual.window == expected.messages
    assert actual.rendered_evidence == render_memory_events_block([e.provider_dict() for e in expected.retrieved_events])


@pytest.fixture
def cli_paths(tmp_path, monkeypatch, dataset_path):
    freeze = tmp_path / 'freeze.json'
    freeze.write_bytes(events.canonical_bytes({
        'schema_version': 'orq39-pre-t3-freeze-v1', 'h_D1': '0.10', 't3_sub_cap_usd': '0.25',
        'pricing_snapshot': {'embedding_model': 'text-embedding-3-small',
                             'usd_per_million_input_tokens': '0.02'}}))
    log = tmp_path / 'events.jsonl'
    events.append(log, 'pre_t3_freeze', {'freeze_sha256': events.file_sha256(freeze)})
    events.append(log, 'oow_check_dev', {'dataset_sha256': events.file_sha256(dataset_path), 'passed': True})
    original = run_t3.run
    monkeypatch.setattr(run_t3, 'run', lambda **kwargs: original(**kwargs, freeze_path=freeze, dataset_path=dataset_path))

    def forbidden(*args, **kwargs):
        raise AssertionError('offline mode must not load a key or construct a provider')

    monkeypatch.setattr(run_t3, 'load_api_key', forbidden)
    monkeypatch.setattr('experiments.conversational_semantic_memory.embedding_client.OpenAIEmbeddingProvider', forbidden)
    return ['--offline', '--events-log', str(log), '--ledger', str(tmp_path / 'ledger.jsonl'),
            '--cache-dir', str(tmp_path / 'cache'), '--checks-dir', str(tmp_path / 'checks'),
            '--env-file', str(tmp_path / 'must-not-open')]


def test_offline_cli_cache_miss_never_dispatches(cli_paths, tmp_path):
    with pytest.raises(OfflineCacheMiss):
        run_t3.main(cli_paths)
    assert not (tmp_path / 'ledger.jsonl').exists()
    assert not (tmp_path / 'checks/t3-retrieval.json').exists()


def test_offline_cli_preseeded_cache(data, cli_paths, tmp_path):
    dataset, pool = data
    client = EmbeddingClient(cache_dir=tmp_path / 'cache', guard=None, offline=True)

    def seed(request):
        client._cache_path(client._key(request)).parent.mkdir(parents=True, exist_ok=True)
        client._cache_path(client._key(request)).write_bytes(events.canonical_bytes({'vector': [1.0, 0.0]}))
        return (1.0, 0.0)

    store = PooledStore.from_dataset(dataset, pool)
    for case in dataset.cases:
        for step in case.steps:
            if step.semantic:
                retrieve(store, case, step, seed)
    assert run_t3.main(cli_paths) == 0
    output = tmp_path / 'checks/t3-retrieval.json'
    import json
    result = json.loads(output.read_text())
    assert result['embedding_calls'] == 0
    assert result['cache_hits'] > 0
    assert Decimal(result['spend_total_usd']) == 0
    assert all(not any(counts.values()) for counts in result['isolation_counts'].values())
    assert 'verdict' not in result
    assert events.verify(tmp_path / 'events.jsonl')[-1].payload['sha256'] == events.file_sha256(output)


def test_dense_threshold_top_n_and_stable_ties(data):
    dataset, _ = data
    case = dataset.cases[0]
    step = next(s for s in case.steps if s.semantic)
    items = [Item(case.tenant_id, case.conversation_id, str(n), n, text, (str(n),))
             for n, text in [(1, 'negative'), (2, 'best'), (3, 'best'), (4, 'orthogonal')]]
    vectors = {'negative': (-1.0, 0.0), 'best': (1.0, 0.0), 'orthogonal': (0.0, 1.0)}
    embed = lambda request: vectors.get(request.text, (1.0, 0.0))
    assert rank_dense(items, case=case, step=step, embed=embed,
                      config=RetrievalConfig(final_top_n=1)) == (items[1],)
    assert rank_dense(items, case=case, step=step, embed=embed,
                      config=RetrievalConfig(similarity_threshold=0.5)) == tuple(items[1:3])


def test_oracle_snapshots_do_not_backdate_or_retain_replaced_facts(data):
    from experiments.conversational_semantic_memory.dataset import Dataset
    dataset, pool = data
    case = dataset.cases[0]
    step = next(s for s in case.steps if s.semantic)
    first = replace(step, step_id='first', after_sequence=2,
                    gold_source_message_ids=(case.turns[0].message_id,))
    second = replace(first, step_id='second', after_sequence=4, gold_values=(case.value_set[1],))
    case = replace(case, steps=(first, second))
    store = PooledStore.from_dataset(Dataset(39, '', (case,)), pool)
    assert not [i for i in store.scoped(case, replace(first, after_sequence=1)) if i.kind == 'fact']
    initial = [i for i in store.scoped(case, first) if i.kind == 'fact']
    final = [i for i in store.scoped(case, second) if i.kind == 'fact']
    assert len(initial) == len(final) == 1
    assert initial[0].value != final[0].value


def test_truncated_window_does_not_receive_full_source_credit():
    from app.core.domain.types import ChatMessage
    from experiments.conversational_semantic_memory.dataset import Message
    messages = (Message('u', 1, 'user', 'long user message'),
                Message('a', 2, 'assistant', 'long assistant reply'))
    item = Item('t', 'c', '1', 2, 'unused', ('u', 'a'), messages=messages)
    result = pack_delivery('A', tuple(ChatMessage(role=m.role, content=m.content) for m in messages),
                           (item,), (), (), question='q', max_chars=8)
    assert result.items == ()
    assert sum(len(m.content) for m in result.window) <= 8


@pytest.fixture
def ranking_fixture(monkeypatch):
    """Keep rankings opposed and all evidence local to expose accidental unions."""
    from experiments.conversational_semantic_memory import retrieval, run_t4
    from experiments.conversational_semantic_memory.dataset import Case, Message, Step

    messages = tuple(message for n in range(1, 17, 2) for message in (
        Message(f'u{n}', n, 'user', 'needle' if n == 1 else f'topic {n}'),
        Message(f'a{n}', n + 1, 'assistant', 'noted')))
    step = Step('step', 'stable_fact', 16, 'needle', ('blue',), (), ('u1',),
                True, False, False, 'answer', 'paraphrase')
    case = Case('case', 'en', 'tenant', '00000000-0000-0000-0000-000000000001',
                'stable_fact', 'color', ('blue',), 'template', (), messages, (step,), ())
    turns = tuple(Item(case.tenant_id, case.conversation_id, str(n), n + 1,
                       '\n'.join(m.content for m in messages[n - 1:n + 1]),
                       (f'u{n}', f'a{n}'), messages=messages[n - 1:n + 1])
                  for n in range(1, 17, 2))
    fact = Item(case.tenant_id, case.conversation_id, 'oracle', 2,
                'color: blue', ('u1',), kind='fact', value='blue')
    limits = {'conversation_history_max_messages': 2,
              'conversation_history_max_chars': 1000,
              'chat_prompt_max_added_context_chars': 12000}
    monkeypatch.setattr(retrieval, 'declared_limits', lambda: limits)
    monkeypatch.setattr(run_t4, 'declared_limits', lambda: limits)

    def embed(request):
        return (0.0, 1.0) if request.role == 'turn' and 'needle' in request.text else (1.0, 0.0)

    return PooledStore(turns + (fact,)), case, step, embed, limits


def test_other_arm_deliveries_match_pre_change_fixture(ranking_fixture):
    from experiments.conversational_semantic_memory.run_t4 import _deliveries

    store, case, step, embed, _ = ranking_fixture
    snapshot = {'facts': [{'tenant_id': case.tenant_id, 'conversation_id': case.conversation_id,
                          'fact_id': 'extracted', 'source_sequence': 2, 'statement': 'color: blue',
                          'source_message_ids': ['u1'], 'status': 'active', 'value': 'blue'}]}
    deliveries = _deliveries(store, case, step, snapshot, embed, RetrievalConfig())
    expected = {
        'A': ('15', '1', '3', '5', '7', '9'),
        'C': ('15', 'extracted', '1', '3', '5', '7', '9'),
        'C-ORACLE': ('15', 'oracle', '1', '3', '5', '7', '9'),
        'GOLD-CONTEXT': ('15', '1'),
    }
    assert {d.arm: tuple(i.item_id for i in d.items) for d in deliveries if d.arm != 'B'} == expected
    # Captured from the pre-change implementation, including rendered bytes,
    # window messages, complete items and budget metadata.
    fingerprints = {
        'A': 'cb1b167012fc9c547c4e2d53963f569a11e75530d3b6548cb4cca3242227236c',
        'C': 'e8d0683cdeac9098240d681085b245bf846a31e6e6f128a8a05364f805d2415d',
        'C-ORACLE': '91ca32d782f19bb1a787f7a8c6947c98e0f69be7d018d4d91b7a4c0a0a4000bd',
        'GOLD-CONTEXT': 'a945ea12fba8a6667c31710d730954a9d849777e112fb5f3d1ce21f487f250fd',
    }
    assert {d.arm: events.sha256_hex(events.canonical_bytes(asdict(d)))
            for d in deliveries if d.arm != 'B'} == fingerprints


def test_b_delivers_dense_ranking_instead_of_a(ranking_fixture):
    store, case, step, embed, _ = ranking_fixture
    a, b, _ = retrieve(store, case, step, embed)
    assert tuple(i.item_id for i in a.items) == ('15', '1', '3', '5', '7', '9')
    assert tuple(i.item_id for i in b.items) == ('15', '3', '5', '7', '9', '11')
    assert set(a.items) != set(b.items)


@pytest.mark.parametrize('includes_first', [False, True])
def test_b_only_admits_a_first_choice_when_dense_selects_it(ranking_fixture, includes_first):
    store, case, step, _, _ = ranking_fixture

    def embed(request):
        if request.role == 'turn' and 'needle' in request.text:
            return (1.0, 0.0) if includes_first else (-1.0, 0.0)
        return (1.0, 0.0)

    a, b, _ = retrieve(store, case, step, embed)
    assert a.items[1].item_id == '1'
    assert ('1' in {i.item_id for i in b.items}) is includes_first


@pytest.mark.parametrize('cap', [0, 250, 500, 12000])
def test_b_uses_a_count_and_character_bounds(ranking_fixture, cap):
    from app.core.domain.bm25_ranking import BM25_TOP_K

    store, case, step, embed, limits = ranking_fixture
    a, b, _ = retrieve(store, case, step, embed, RetrievalConfig(final_top_n=7),
                       limits={**limits, 'chat_prompt_max_added_context_chars': cap})
    for delivery in (a, b):
        assert len([i for i in delivery.items if i.item_id != '15']) <= BM25_TOP_K
        assert sum(len(m.content) for m in delivery.window) + len(delivery.rendered_evidence) <= cap
    if cap == 12000:
        assert len(b.items) == BM25_TOP_K + 1
