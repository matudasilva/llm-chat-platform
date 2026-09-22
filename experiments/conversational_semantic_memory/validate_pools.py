"""Static pool checks count declared structures without instantiating held-out items."""
from __future__ import annotations

import argparse
from collections import Counter
from statistics import median
from itertools import combinations
from pathlib import Path
from typing import Any

from . import paths, heldout_access
from .dataset import (Dataset, fingerprint, load_dataset, load_pool, normalize,
                      pool_structures, require, validate_pairing, parse_pool, decode_json, structure_strata,
                      lexical_measure, PARAPHRASE_MAX_OVERLAP, STRATA)
from .events import canonical_bytes, file_sha256, sha256_hex

CHECK_FILES = {
    'overlap_regime': 'overlap-regime.json',
    'disjointness': 'disjointness.json',
    'fingerprint_uniqueness': 'item-uniqueness-pools.json',
    'capacity': 'pool-capacity.json',
    'en_es_pairing': 'en-es-pairing.json',
    'alias_uniqueness': 'alias-uniqueness.json',
}


def alias_uniqueness(pool: dict[str, Any]) -> None:
    owners: dict[str, str] = {}
    for value in pool['values']:
        for aliases in value['aliases'].values():
            for alias in aliases:
                owner = owners.setdefault(normalize(alias), value['id'])
                require(owner == value['id'], f'alias collision: {alias}')


def disjointness(dev: dict[str, Any], heldout: dict[str, Any]) -> None:
    for field in ('slots', 'values', 'question_templates'):
        require(not {v['id'] for v in dev[field]} & {v['id'] for v in heldout[field]},
                f'overlapping {field} ids')
    def surfaces(pool: dict[str, Any], field: str) -> set[str]:
        if field == 'values':
            return {normalize(a) for v in pool[field] for aliases in v['aliases'].values() for a in aliases}
        if field == 'question_templates':
            return {normalize(text) for template in pool[field]
                    for surface in [template['text'], template['paraphrase'], *template['variants'].values()]
                    for text in surface.values()}
        key = 'labels'
        return {normalize(text) for v in pool[field] for text in v[key].values()}
    for field in ('slots', 'values', 'question_templates'):
        require(not surfaces(dev, field) & surfaces(heldout, field), f'overlapping {field} surfaces')


def unique_capacity(pool: dict[str, Any]) -> int:
    return len({fingerprint(*structure) for structure in pool_structures(pool)})


def variation(pool: dict[str, Any]) -> dict[str, int]:
    return {field: len(pool[field]) for field in ('slots', 'values', 'question_templates', 'filler_topics')}


def check_dataset_pool(dataset: Dataset, pool: dict[str, Any], digest: str) -> None:
    require(dataset.pool_sha256 == digest, 'dataset pool digest mismatch')
    allowed = {fingerprint(*s) for s in pool_structures(pool)}
    require({c.structural_fingerprint for c in dataset.cases} == allowed, 'dataset structures do not cover dev pool')
    validate_pairing(dataset.cases)


def overlap_regime(dataset: Dataset, pool: dict[str, Any]) -> dict[str, Any]:
    """Measure all gold turns together; no text or assignment is repaired here."""
    slots = {slot['id']: slot for slot in pool['slots']}
    rows = []
    for case in dataset.cases:
        for step in case.steps:
            if not step.semantic:
                continue
            evidence = ' '.join(m.content for m in case.turns
                                if m.message_id in step.gold_source_message_ids)
            overlap, shared_keys = lexical_measure(step.question, evidence, slots[case.slot], case.language)
            valid = bool(shared_keys) if step.lexical_stratum == 'lexical_anchor' else (
                not shared_keys and overlap <= PARAPHRASE_MAX_OVERLAP)
            rows.append({'language': case.language, 'family': step.family,
                         'case_family': case.family, 'stratum': step.lexical_stratum,
                         'overlap': overlap, 'passed': valid, 'step_id': step.step_id})
    report = overlap_report(rows)
    require(all(r['passed'] for r in rows), 'step violates declared lexical regime: ' +
            str([r for r in rows if not r['passed']]))
    return report


def overlap_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    distributions = []
    for language in ('en', 'es'):
        language_rows = [r for r in rows if r['language'] == language]
        counts = Counter(r['stratum'] for r in language_rows)
        require(counts['lexical_anchor'] == counts['paraphrase'] > 0,
                'strata must be exactly balanced per language')
        for family in sorted({r['family'] for r in language_rows}):
            counts = Counter(r['stratum'] for r in language_rows if r['family'] == family)
            require(abs(counts['lexical_anchor'] - counts['paraphrase']) <= 1,
                    'semantic family strata are not balanced')
        for family in [None, *sorted({r['family'] for r in language_rows})]:
            for stratum in STRATA:
                values = [r['overlap'] for r in language_rows if r['stratum'] == stratum
                          and (family is None or r['family'] == family)]
                distributions.append({'language': language, 'family': family, 'stratum': stratum,
                                      'count': len(values), 'min': min(values) if values else None,
                                      'median': median(values) if values else None,
                                      'max': max(values) if values else None})
    case_distributions = []
    for language in ('en', 'es'):
        for family in sorted({r['case_family'] for r in rows}):
            counts = Counter(r['stratum'] for r in rows
                             if r['language'] == language and r['case_family'] == family)
            require(abs(counts['lexical_anchor'] - counts['paraphrase']) <= 1,
                    'case family strata are not balanced')
            for stratum in STRATA:
                values = [r['overlap'] for r in rows if r['language'] == language
                          and r['case_family'] == family and r['stratum'] == stratum]
                case_distributions.append({'language': language, 'family': family, 'stratum': stratum,
                                           'count': len(values), 'min': min(values) if values else None,
                                           'median': median(values) if values else None,
                                           'max': max(values) if values else None})
    return {'ceiling': PARAPHRASE_MAX_OVERLAP, 'distributions': distributions,
            'case_family_distributions': case_distributions, 'steps': rows}


def pool_overlap_regime(pool: dict[str, Any]) -> dict[str, Any]:
    """Check authored surfaces without creating held-out conversations or items.

    Each structure contributes one conservative maximum across its possible
    evidence phrasings and values. This is a pool diagnostic, not an item result.
    """
    slots = {s['id']: s for s in pool['slots']}
    templates = {t['id']: t for t in pool['question_templates']}
    values = {v['id']: v for v in pool['values']}
    rows = []
    for (family, slot_id, template_id), stratum in structure_strata(pool).items():
        slot, template = slots[slot_id], templates[template_id]
        for language in ('en', 'es'):
            question = template['text' if stratum == 'lexical_anchor' else 'paraphrase'][language]
            measures = []
            surfaces = slot['assertions'][language] + (
                [slot['retractions'][language]] if family == 'update' else [])
            if family == 'duplicate':
                surfaces = [*surfaces, *(' '.join(pair) for pair in combinations(surfaces, 2))]
            for surface in surfaces:
                for value in slot['value_ids'][:2]:
                    evidence = surface.format(value=values[value]['aliases'][language][0])
                    overlap, shared = lexical_measure(question, evidence, slot, language)
                    require(bool(shared) if stratum == 'lexical_anchor' else
                            not shared and overlap <= PARAPHRASE_MAX_OVERLAP,
                            f'pool lexical regime violation: {slot_id}/{language}/{stratum}: {overlap}')
                    measures.append(overlap)
            semantic_family = family if family in ('stable_fact', 'duplicate', 'update',
                                                   'contradiction_trap', 'isolation_canary') else 'stable_fact'
            rows.append({'language': language, 'family': semantic_family, 'case_family': family,
                         'stratum': stratum, 'overlap': max(measures), 'passed': True})
    return overlap_report(rows)


def run_checks(*, check: str = 'all', dev_pool: Path = paths.DEV_POOL,
               heldout_pool: Path = paths.HELDOUT_POOL, dataset_path: Path = paths.DEV_DATASET,
               checks_dir: Path = paths.CHECKS_DIR,
               events_log: Path = paths.EVENTS_LOG) -> dict[str, Any]:
    selected = list(CHECK_FILES) if check == 'all' else [check]
    require(all(name in CHECK_FILES for name in selected), 'unknown check')
    checks_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {'passed': True, 'checks': {}, 'input_sha256': {}}
    try:
        dev = load_pool(dev_pool)
        heldout_bytes = heldout_access.read_for_scan(heldout_pool, events_log=events_log)
        heldout = parse_pool(decode_json(heldout_bytes))
        dataset = load_dataset(dataset_path)
        summary['input_sha256'] = {name: file_sha256(path) for name, path in
                                   [('dev_pool', dev_pool), ('dev_dataset', dataset_path)]}
        summary['input_sha256']['heldout_pool'] = sha256_hex(heldout_bytes)
        check_dataset_pool(dataset, dev, summary['input_sha256']['dev_pool'])
        input_error = None
    except (ValueError, OSError, KeyError, TypeError, heldout_access.HeldoutSealError) as exc:
        input_error = str(exc)
    for name in selected:
        result: dict[str, Any] = {'check': name, 'passed': False,
                                  'input_sha256': summary['input_sha256']}
        try:
            require(input_error is None, input_error or '')
            if name == 'overlap_regime':
                result['dev'] = overlap_regime(dataset, dev)
                result['pools'] = {p['pool']: pool_overlap_regime(p) for p in (dev, heldout)}
            elif name == 'disjointness':
                disjointness(dev, heldout)
            elif name == 'alias_uniqueness':
                alias_uniqueness(dev)
                alias_uniqueness(heldout)
            elif name == 'fingerprint_uniqueness':
                for pool in (dev, heldout):
                    require(unique_capacity(pool) == len(pool_structures(pool)), 'duplicate pool structure')
                validate_pairing(dataset.cases)
            elif name == 'en_es_pairing':
                # load_pool requires exactly EN and ES on every surface; dataset
                # pairing also checks provenance positions and step membership.
                validate_pairing(dataset.cases)
                result['conceptual_cases'] = len(dataset.cases) // 2
            elif name == 'capacity':
                result['unique_capacity'] = {p['pool']: unique_capacity(p) for p in (dev, heldout)}
                require(unique_capacity(heldout) >= 150, 'held-out capacity below 150')
            result['variation'] = {p['pool']: variation(p) for p in (dev, heldout)}
            result['passed'] = True
        except (ValueError, KeyError, TypeError) as exc:
            result['error'] = str(exc)
        output = checks_dir / CHECK_FILES[name]
        output.write_bytes(canonical_bytes(result) + b'\n')
        summary['checks'][name] = {'passed': result['passed'], 'file': output.name,
                                   'sha256': file_sha256(output)}
        summary['passed'] = summary['passed'] and result['passed']
    summary_path = checks_dir / 'pool-validation.json'
    summary_path.write_bytes(canonical_bytes(summary) + b'\n')
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', choices=[*CHECK_FILES, 'all'], default='all')
    parser.add_argument('--events-log', type=Path, default=paths.EVENTS_LOG)
    args = parser.parse_args()
    summary = run_checks(check=args.check, events_log=args.events_log)
    if not summary['passed']:
        print('Pool checks failed; see ' + str(paths.CHECKS_DIR / 'pool-validation.json'))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
