"""Expose numeric pool aggregates without treating dev grammar as a T6 plan."""
from __future__ import annotations

import argparse
import json
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from string import Formatter

from . import events, heldout_access, paths
from .cost_bound import CostBoundUnavailable, PoolMetadata, compute_cost_bound
from .dataset import LANGUAGES, decode_json, parse_pool, pool_structures
from .spend_guard import validate_ledger

AGGREGATE_KEYS = frozenset({
    'capacity', 'max_question_template_bytes', 'max_assertion_template_bytes',
    'max_retraction_template_bytes', 'max_value_alias_bytes', 'max_slot_label_bytes',
    'max_filler_paragraph_bytes', 'max_filler_body_paragraph_count',
    'max_followup_paragraph_count', 'max_prohibited_fixture_bytes',
})


class MetadataError(ValueError):
    """A fixed error prevents parser details from exposing sealed text."""


def template_bytes(template: str, value_bytes: int) -> int:
    """Measure substitutions without rendering an assertion or question."""
    total = 0
    for literal, field, format_spec, conversion in Formatter().parse(template):
        total += len(literal.encode('utf-8'))
        if field is not None:
            if field != 'value' or format_spec or conversion:
                raise MetadataError('metadata_extraction_failed')
            total += value_bytes
    return total


def numeric_only(value: object) -> dict[str, int]:
    """Only fixed keys and nonnegative integers may cross the process boundary."""
    if (not isinstance(value, dict) or set(value) != AGGREGATE_KEYS
            or any(type(v) is not int or v < 0 for v in value.values())):
        raise MetadataError('metadata_extraction_failed')
    return value


def extract_aggregates(raw: bytes) -> dict[str, int]:
    """Aggregate authored components, never instantiate cases or emit identities."""
    try:
        pool = parse_pool(decode_json(raw))
        if pool['pool'] != 'heldout':
            raise MetadataError('metadata_extraction_failed')
        result = dict.fromkeys(AGGREGATE_KEYS, 0)
        structures = pool_structures(pool)
        result['capacity'] = len(set(structures))
        if len(structures) != result['capacity']:
            raise MetadataError('metadata_extraction_failed')
        values = {v['id']: v for v in pool['values']}
        slots = {s['id']: s for s in pool['slots']}
        for language in LANGUAGES:
            for slot in pool['slots']:
                value_size = max(len(alias.encode('utf-8'))
                                 for key in slot['value_ids']
                                 for alias in values[key]['aliases'][language])
                result['max_value_alias_bytes'] = max(result['max_value_alias_bytes'], value_size)
                result['max_slot_label_bytes'] = max(result['max_slot_label_bytes'],
                                                      len(slot['labels'][language].encode('utf-8')))
                for template in slot['assertions'][language]:
                    result['max_assertion_template_bytes'] = max(
                        result['max_assertion_template_bytes'], template_bytes(template, value_size))
                result['max_retraction_template_bytes'] = max(
                    result['max_retraction_template_bytes'],
                    template_bytes(slot['retractions'][language], value_size))
            for question in pool['question_templates']:
                value_size = max(len(alias.encode('utf-8'))
                                 for key in slots[question['slot']]['value_ids']
                                 for alias in values[key]['aliases'][language])
                templates = [question['text'][language], question['paraphrase'][language]]
                templates.extend(v[language] for v in question['variants'].values())
                result['max_question_template_bytes'] = max(
                    result['max_question_template_bytes'],
                    *(template_bytes(t, value_size) for t in templates))
            paragraphs = [f['text'][language].split('\n\n') for f in pool['filler_topics']]
            result['max_filler_paragraph_bytes'] = max(
                result['max_filler_paragraph_bytes'],
                *(len(p.encode('utf-8')) for group in paragraphs for p in group))
            result['max_filler_body_paragraph_count'] = max(
                result['max_filler_body_paragraph_count'], sum(len(p) - 1 for p in paragraphs))
            result['max_followup_paragraph_count'] = max(
                result['max_followup_paragraph_count'], min(10, len(paragraphs)))
        result['max_prohibited_fixture_bytes'] = max(
            len(v.encode('utf-8')) for v in pool['prohibited_fixtures'])
        return numeric_only(result)
    except Exception:
        raise MetadataError('metadata_extraction_failed') from None


def worker(pool: Path, log: Path) -> int:
    """The accessor owns the sole pool read and logs its verified seal digest."""
    try:
        result = heldout_access.read_metadata(extract_aggregates, pool, events_log=log)
        print(events.canonical_bytes(numeric_only(result)).decode('utf-8'))
        return 0
    except Exception:
        print('metadata_extraction_failed', file=sys.stderr)
        return 1


def isolated_aggregates(pool: Path, log: Path) -> dict[str, int]:
    """Never relay child diagnostics, including unexpected tracebacks, to callers."""
    try:
        result = subprocess.run(
            [sys.executable, '-B', '-m', 'experiments.conversational_semantic_memory.extract_cost_metadata', '--worker', '--pool', str(pool),
             '--events-log', str(log)], cwd=paths.REPO_ROOT, capture_output=True,
            timeout=60, check=False)
        if result.returncode or len(result.stdout) > 8192:
            raise MetadataError('metadata_extraction_failed')
        return numeric_only(json.loads(result.stdout))
    except Exception:
        raise MetadataError('metadata_extraction_failed') from None


def cost_status(aggregates: dict[str, int]) -> dict:
    """Missing T6 construction/output bounds cannot be filled with pool maxima."""
    numeric_only(aggregates)
    metadata = {f.name: None for f in fields(PoolMetadata)}
    metadata['capacity'] = aggregates['capacity']
    try:
        compute_cost_bound(metadata=PoolMetadata(**metadata))
    except CostBoundUnavailable:
        return {
            'status': 'blocked', 'reason': 'cost_bound_unavailable',
            'pool_metadata': metadata, 'n_max': None, 'n_cap': None,
            'missing_fields': [k for k, v in metadata.items() if v is None],
            'blockers': [
                'No complete T6 construction plan defines per-case steps and user turns, including both H3 steps required for every conceptual case.',
                'No complete T6 request plan bounds embedding requests independently of cache reuse.',
                'Question/assertion component lengths do not certify complete constructed message or TurnUnit bounds.',
                'Authored slots/aliases do not bound generated slot keys, values, or accumulated active slots.',
                'Complete serialized request bounds must include JSON escaping and framing; raw text maxima alone are insufficient.',
            ],
            'interpretation': 'Preparation status only, not an executed terminal decision or power result.',
        }
    raise MetadataError('metadata_extraction_failed')


def run() -> dict:
    """Write a new evidence directory; preserve frozen inputs and old results."""
    output = paths.CHECKS_DIR / 'heldout-cost-metadata-2026-09-30'
    if output.exists():
        raise MetadataError('metadata_output_exists')
    checkpoint_path = paths.ORQ_DIR / 'plan-checkpoint.json'
    # The existing helper has pure local checks; its CLI would query origin.
    import runpy
    helper = runpy.run_path(str(paths.REPO_ROOT / '.framework/local-tools/fw_check_orq_checkpoint.py'))
    _, contract = helper['spec_digest'](paths.ORQ_DIR / 'spec.md')
    helper['load_checkpoint'](checkpoint_path, paths.ORQ_DIR.name, 'hybrid', contract)
    old_chain = events.verify(paths.EVENTS_LOG)
    expected_seal = heldout_access._sealed_digest(paths.HELDOUT_POOL, paths.EVENTS_LOG)
    source_paths = [Path(__file__), paths.PACKAGE_DIR / 'dataset.py',
                    paths.PACKAGE_DIR / 'heldout_access.py', paths.PACKAGE_DIR / 'cost_bound.py',
                    paths.PACKAGE_DIR / 'build_dataset.py', paths.PACKAGE_DIR / 'facts.py',
                    paths.PACKAGE_DIR / 'extraction.py', paths.ORQ_DIR / 'spec.md', checkpoint_path,
                    paths.EVIDENCE_DIR / 'pre-dev-freeze.json',
                    paths.CHECKS_DIR / 'pool-capacity.json']
    hashes = {str(p.relative_to(paths.REPO_ROOT)): events.file_sha256(p) for p in source_paths}
    authorization = events.append(paths.EVENTS_LOG, 'heldout_metadata_only_authorized', {
        'scope': 'Operator approved numeric aggregates only; no instantiation, evaluation, model calls, power analysis or registration.',
        'spec_contract_sha256': contract, 'pool_seal_sha256': expected_seal,
        'extractor_sha256': events.file_sha256(Path(__file__)),
    })
    aggregates = isolated_aggregates(paths.HELDOUT_POOL, paths.EVENTS_LOG)
    access = events.verify(paths.EVENTS_LOG)[-1]
    if (access.type != 'heldout_pool_access' or access.payload.get('purpose') != 'metadata'
            or access.payload.get('matches_seal') is not True
            or access.payload.get('sha256') != expected_seal):
        raise MetadataError('metadata_access_not_verified')
    ledgers = {}
    for name, cap in [('t3-ledger.jsonl', '.25'), ('t4-ledger.jsonl', '2.50')]:
        ledger = paths.EVIDENCE_DIR / name
        result = validate_ledger(ledger, ceiling_usd=Decimal(10), sub_cap_usd=Decimal(cap))
        if not result['passed']:
            raise MetadataError('ledger_check_failed')
        ledgers[name] = {k: v for k, v in result.items() if k != 'rows'}
        hashes[str(ledger.relative_to(paths.REPO_ROOT))] = events.file_sha256(ledger)
    remaining = Decimal(10) - sum(Decimal(v['total_usd']) for v in ledgers.values())
    report = {
        'schema_version': 'orq39-cost-metadata-v1', 'spec_contract_sha256': contract,
        'pool_sha256': expected_seal, 'pool_access_event_hash': access.hash,
        'authorization_event_hash': authorization.hash, 'source_sha256': hashes,
        'aggregates': aggregates, 'cost_bound': cost_status(aggregates),
        'measurement_scope': 'Pool component maxima only; no questions, turns or cases were instantiated. Template substitutions were measured as byte counts without rendering.',
        'followup_count_scope': 'Current dev builder uses at most ten last paragraphs; this count is not a certified T6 turn bound.',
        'task6_sub_cap_usd': '9.00', 'remaining_global_usd': str(remaining),
        'effective_budget_usd': str(min(Decimal(9), remaining)), 'ledgers': ledgers,
        'generation_calls': 0, 'embedding_calls': 0, 'incremental_spend_usd': '0',
    }
    for relative, digest in hashes.items():
        if events.file_sha256(paths.REPO_ROOT / relative) != digest:
            raise MetadataError('source_changed')
    output.mkdir()
    target = output / 'cost-metadata.json'
    target.write_bytes(events.canonical_bytes(report) + b'\n')
    events.append(paths.EVENTS_LOG, 'heldout_cost_metadata_recorded', {
        'path': str(target.relative_to(paths.REPO_ROOT)), 'sha256': events.file_sha256(target),
        'pool_sha256': expected_seal, 'pool_access_event_hash': access.hash,
        'cost_bound_status': 'cost_bound_unavailable', 'incremental_spend_usd': '0',
    })
    if events.verify(paths.EVENTS_LOG)[:len(old_chain)] != old_chain:
        raise MetadataError('event_prefix_changed')
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--pool', type=Path, default=paths.HELDOUT_POOL, help=argparse.SUPPRESS)
    parser.add_argument('--events-log', type=Path, default=paths.EVENTS_LOG, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.pool, args.events_log)
    try:
        result = run()
        print(events.canonical_bytes({
            'aggregates': result['aggregates'], 'cost_bound': result['cost_bound'],
            'remaining_global_usd': result['remaining_global_usd'],
        }).decode('utf-8'))
        return 0
    except Exception:
        print('metadata_extraction_failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
