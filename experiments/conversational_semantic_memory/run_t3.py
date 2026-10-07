"""Run embedding-only dev retrieval and record evidence without a D1 verdict."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from . import events, paths
from .coverage import Observation, coverage, isolation_counts, summarize
from .dataset import load_dataset, load_pool, read_json
from .embedding_client import EmbeddingClient, load_api_key
from .heldout_access import assert_not_heldout_path
from .retrieval import PooledStore, RetrievalConfig, retrieve
from .spend_guard import Pricing, SpendGuard, validate_ledger

FREEZE_PATH = paths.EVIDENCE_DIR / 'pre-t3-freeze.json'


def run(*, events_log: Path, ledger: Path, cache_dir: Path, checks_dir: Path,
        offline: bool, env_file: Path, dataset_path: Path = paths.DEV_DATASET,
        pool_path: Path = paths.DEV_POOL, freeze_path: Path = FREEZE_PATH) -> dict:
    """Validate frozen prerequisites before the client can dispatch anything."""
    for path in (dataset_path, pool_path, freeze_path):
        assert_not_heldout_path(path)
    freeze = read_json(freeze_path)
    digest = events.file_sha256(freeze_path)
    chain = events.verify(events_log)
    frozen = [e for e in chain if e.type == 'pre_t3_freeze' and e.payload.get('freeze_sha256') == digest]
    if len(frozen) != 1:
        raise ValueError('exactly one matching pre_t3_freeze event is required')
    if (freeze['schema_version'] != 'orq39-pre-t3-freeze-v1'
            or Decimal(freeze['h_D1']) != Decimal('0.10')
            or Decimal(freeze['t3_sub_cap_usd']) != Decimal('0.25')):
        raise ValueError('unexpected T3 frozen contract')
    price = freeze['pricing_snapshot']
    pricing = Pricing(price['embedding_model'], Decimal(price['usd_per_million_input_tokens']))
    if not pricing.input_usd_per_million.is_finite() or pricing.input_usd_per_million <= 0:
        raise ValueError('invalid frozen embedding price')
    guard = SpendGuard(ledger, stage='T3', ceiling_usd=Decimal('10'),
                       sub_cap_usd=Decimal(freeze['t3_sub_cap_usd']), pricing=pricing)
    initial_ledger = validate_ledger(ledger, ceiling_usd=guard.ceiling_usd,
                                    sub_cap_usd=guard.sub_cap_usd)
    if not initial_ledger['passed']:
        raise ValueError('existing ledger exceeds frozen caps')
    dataset_digest = events.file_sha256(dataset_path)
    pool_digest = events.file_sha256(pool_path)
    dataset, pool = load_dataset(dataset_path), load_pool(pool_path)
    if dataset.pool_sha256 != pool_digest:
        raise ValueError('dev dataset does not match its pool')
    if pool['pool'] != 'dev':
        raise ValueError('T3 accepts only the dev pool')
    checks = [e for e in chain if e.type == 'oow_check_dev'
              and e.payload.get('dataset_sha256') == dataset_digest and e.payload.get('passed') is True]
    if not checks:
        raise ValueError('a passing dev out-of-window check is required before T3')
    config = RetrievalConfig()
    store = PooledStore.from_dataset(dataset, pool)
    client = EmbeddingClient(cache_dir=cache_dir, guard=guard, model=pricing.model,
                             offline=offline, api_key=None if offline else load_api_key(env_file))
    # This link places every subsequent ledger reservation after the freeze
    # in the main chain without changing the shared client's ledger format.
    events.append(events_log, 't3_retrieval_started', {
        'freeze_sha256': digest, 'ledger_sha256_before': events.file_sha256(ledger) if ledger.exists() else None,
        'dataset_sha256': dataset_digest, 'config': asdict(config), 'offline': offline})
    observations = []
    deliveries = []
    for case in dataset.cases:
        aliases = {v['id']: v['aliases'][case.language] for v in pool['values']}
        for step in case.steps:
            if not step.semantic:
                continue
            for delivery in retrieve(store, case, step, client.embed, config):
                counts = isolation_counts(case, delivery)
                row = Observation(case.conceptual_case_id, case.language, step.lexical_stratum,
                                  step.step_id, delivery.arm, coverage(case, step, delivery, aliases), **counts)
                observations.append(row)
                deliveries.append({'step_id': step.step_id, 'arm': delivery.arm,
                                   'items': [asdict(i) for i in delivery.items],
                                   'budget_binding': delivery.budget_binding,
                                   'facts_dropped': delivery.facts_dropped})
    ledger_check = validate_ledger(ledger, ceiling_usd=guard.ceiling_usd, sub_cap_usd=guard.sub_cap_usd)
    if (events.file_sha256(dataset_path) != dataset_digest
            or events.file_sha256(pool_path) != pool_digest
            or events.file_sha256(freeze_path) != digest):
        raise ValueError('inputs changed during retrieval')
    result = {'schema_version': 'orq39-t3-retrieval-v1', **summarize(observations),
              'config': asdict(config), 'freeze_sha256': digest, 'dataset_sha256': dataset_digest,
              'pool_sha256': pool_digest, 'embedding_calls': client.calls,
              'cache_hits': client.cache_hits, 'spend_total_usd': str(guard.spent_usd()),
              'ledger_check': ledger_check, 'observations': [asdict(r) for r in observations],
              'deliveries': deliveries}
    checks_dir.mkdir(parents=True, exist_ok=True)
    output = checks_dir / 't3-retrieval.json'
    output.write_bytes(events.canonical_bytes(result) + b'\n')
    events.append(events_log, 't3_retrieval_complete', {'sha256': events.file_sha256(output),
                  'result_sha256': events.file_sha256(output), 'freeze_sha256': digest})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events-log', type=Path, default=paths.EVENTS_LOG)
    parser.add_argument('--ledger', type=Path, default=paths.EVIDENCE_DIR / 't3-ledger.jsonl')
    parser.add_argument('--cache-dir', type=Path, default=paths.EVIDENCE_DIR / 'embedding-cache')
    parser.add_argument('--checks-dir', type=Path, default=paths.CHECKS_DIR)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--env-file', type=Path, default=paths.REPO_ROOT / '.env')
    run(**vars(parser.parse_args(argv)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
