"""Synthetic pools exercise the output boundary without opening real held-out."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from experiments.conversational_semantic_memory import events, heldout_access
from experiments.conversational_semantic_memory import extract_cost_metadata as metadata


def bilingual(text: str) -> dict[str, str]:
    return {'en': text, 'es': text}


@pytest.fixture
def synthetic_pool() -> dict:
    """Use recognizable markers so a leaked surface cannot pass unnoticed."""
    return {
        'schema_version': 'orq39-pool-v1', 'pool': 'heldout',
        'values': [{'id': f'v{i}', 'aliases': bilingual([f'PRIVATE_VALUE_{i} é"\\'])}
                   for i in range(4)],
        'slots': [{'id': 'dimension', 'kind': 'fact', 'labels': bilingual('PRIVATE_LABEL'),
                   'value_ids': ['v0', 'v1', 'v2', 'v3'], 'families': ['stable_fact', 'historical'],
                   'key_terms': bilingual(['PRIVATE_KEY']),
                   'assertions': bilingual(['I use {value}.', 'Still {value}.', 'Now {value}.']),
                   'retractions': bilingual('No longer {value}.')}],
        'question_templates': [{'id': 'PRIVATE_TEMPLATE', 'slot': 'dimension',
                                'text': bilingual('Which {value}?'),
                                'paraphrase': bilingual('Tell me {value} and {value}.'),
                                'variants': {k: bilingual('Earlier {value}?') for k in
                                             ('historical', 'no_memory', 'distractor', 'prohibited')}}],
        'filler_topics': [{'id': 'PRIVATE_FILLER', 'text': bilingual('first\n\né"\\')}],
        'prohibited_fixtures': ['SYNTHETIC-PROHIBITED-TEST-12345678'],
    }


def test_component_byte_bounds_without_rendering_items(synthetic_pool):
    result = metadata.extract_aggregates(events.canonical_bytes(synthetic_pool))
    assert result.keys() == metadata.AGGREGATE_KEYS
    assert result['capacity'] == 2
    assert result['max_filler_body_paragraph_count'] == 1
    assert result['max_followup_paragraph_count'] == 1
    assert result['max_filler_paragraph_bytes'] == 5
    for language in ('en', 'es'):
        for value in synthetic_pool['values']:
            alias = value['aliases'][language][0]
            for question in synthetic_pool['question_templates']:
                templates = [question['text'][language], question['paraphrase'][language]]
                templates += [v[language] for v in question['variants'].values()]
                for template in templates:
                    assert len(template.format(value=alias).encode()) <= result['max_question_template_bytes']
            for template in synthetic_pool['slots'][0]['assertions'][language]:
                assert len(template.format(value=alias).encode()) <= result['max_assertion_template_bytes']
    encoded = events.canonical_bytes(result)
    assert b'PRIVATE_' not in encoded
    assert all(type(value) is int for value in result.values())


@pytest.mark.parametrize('template', ['{value.__class__}', '{value!r}', '{value:100}', '{secret}', '{'])
def test_unapproved_format_grammar_fails_closed(template):
    with pytest.raises((metadata.MetadataError, ValueError)):
        metadata.template_bytes(template, 10)


def test_errors_hide_pool_values(synthetic_pool, capsys):
    synthetic_pool['slots'][0]['kind'] = 'PRIVATE_INVALID_KIND'
    with pytest.raises(metadata.MetadataError) as caught:
        metadata.extract_aggregates(events.canonical_bytes(synthetic_pool))
    assert str(caught.value) == 'metadata_extraction_failed'
    assert caught.value.__suppress_context__
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('mutation', ['extra_key', 'string', 'boolean', 'negative', 'missing'])
def test_output_allowlist_rejects_nonaggregate_data(synthetic_pool, mutation):
    result = metadata.extract_aggregates(events.canonical_bytes(synthetic_pool))
    if mutation == 'extra_key':
        result['PRIVATE_SLOT_ID'] = 1
    elif mutation == 'missing':
        del result['capacity']
    else:
        result['capacity'] = {'string': 'PRIVATE_TEXT', 'boolean': True, 'negative': -1}[mutation]
    with pytest.raises(metadata.MetadataError, match='^metadata_extraction_failed$'):
        metadata.numeric_only(result)


def test_isolated_read_audits_seal_and_does_not_instantiate(synthetic_pool, tmp_path):
    pool, log = tmp_path / 'sealed.json', tmp_path / 'events.jsonl'
    pool.write_bytes(events.canonical_bytes(synthetic_pool))
    original = pool.read_bytes()
    heldout_access.seal(pool, events_log=log)
    result = metadata.isolated_aggregates(pool, log)
    assert result == metadata.extract_aggregates(original)
    assert pool.read_bytes() == original
    assert {p.name for p in tmp_path.iterdir()} == {'sealed.json', 'events.jsonl'}
    chain = events.verify(log)
    assert [e.type for e in chain] == ['heldout_pool_sealed', 'heldout_pool_access']
    assert chain[-1].payload['purpose'] == 'metadata'
    assert chain[-1].payload['matches_seal'] is True
    assert 'PRIVATE_' not in log.read_text()


def test_changed_seal_does_not_expose_raw_text(synthetic_pool, tmp_path):
    pool, log = tmp_path / 'sealed.json', tmp_path / 'events.jsonl'
    pool.write_bytes(events.canonical_bytes(synthetic_pool))
    heldout_access.seal(pool, events_log=log)
    pool.write_bytes(b'PRIVATE_TAMPERED_DATA')
    with pytest.raises(metadata.MetadataError, match='^metadata_extraction_failed$'):
        metadata.isolated_aggregates(pool, log)
    assert events.verify(log)[-1].payload['matches_seal'] is False


def test_child_failure_is_not_relayed(monkeypatch):
    monkeypatch.setattr(metadata.subprocess, 'run', lambda *a, **k:
                        subprocess.CompletedProcess([], 1, b'PRIVATE_STDOUT', b'PRIVATE_STDERR'))
    with pytest.raises(metadata.MetadataError, match='^metadata_extraction_failed$'):
        metadata.isolated_aggregates(Path('unused'), Path('unused-log'))


def test_pool_counts_cannot_authorize_a_t6_cost_bound(synthetic_pool):
    report = metadata.cost_status(metadata.extract_aggregates(events.canonical_bytes(synthetic_pool)))
    assert report['reason'] == 'cost_bound_unavailable'
    assert report['pool_metadata']['capacity'] == 2
    assert len(report['missing_fields']) == 8
    assert report['n_max'] is report['n_cap'] is None
    assert not any('PRIVATE_' in text for text in report['blockers'])
