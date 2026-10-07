"""Cache-only dev stages; paid dispatch remains the orchestrator's responsibility."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from statistics import mean

from . import events, paths, validate_prompts
from .arms import answer_request
from .classification import ValueEntry, ValueUniverse, classify
from .dataset import Case, Dataset, Step, load_dataset, load_pool, read_json
from .embedding_client import EmbeddingClient, load_api_key
from .estimands import Observation, case_values
from .extraction import EXTRACTOR_VERSION, Complete, extract_turn
from .extraction_metrics import (
    GoldFact, LifecycleExpectation, aggregate_metrics, gold_snapshot, lifecycle_gold, score_extraction,
)
from .facts import FactStore
from .heldout_access import assert_not_heldout_path
from .generation_client import GenerationClient, GenerationRequest, GenerationResult
from .retrieval import Embed, Item, PooledStore, RetrievalConfig, pack_delivery, retrieve
from .spend_guard import Pricing, SpendGuard, validate_ledger
from .validate_pressure import declared_limits

FREEZE_PATH = paths.EVIDENCE_DIR / 'pre-dev-freeze.json'
MODEL = 'gpt-4o-mini-2024-07-18'


def select_candidate(candidates: list[dict]) -> dict:
    """The frozen ordering has no dependence on grid enumeration order."""
    if not candidates or any(c['score'] is None for c in candidates):
        raise ValueError('semantic observations required for every candidate')
    return min(candidates, key=lambda c: (-c['score'], c['top_n'], -c['threshold']))


def _ledger_check(guard: SpendGuard) -> dict:
    # The shared validator checks caps; the guard additionally rejects duplicate
    # reservations and unmatched results. Neither may be bypassed on cache replay.
    guard.spent_usd()
    result = validate_ledger(guard.ledger_path, ceiling_usd=guard.ceiling_usd,
                             sub_cap_usd=guard.sub_cap_usd)
    if not result['passed']:
        raise ValueError('existing ledger exceeds frozen caps')
    return result


def prerequisites(freeze_path: Path, events_log: Path, ledger: Path,
                  cache_dir: Path, checks_dir: Path) -> tuple[dict, SpendGuard]:
    """Check content and chain order before constructing either client."""
    assert_not_heldout_path(freeze_path)
    freeze = read_json(freeze_path)
    digest = events.file_sha256(freeze_path)
    chain = events.verify(events_log)
    frozen = [e for e in chain if e.type == 'pre_dev_freeze']
    if len(frozen) != 1 or frozen[0].payload.get('freeze_sha256') != digest:
        raise ValueError('exactly one matching pre_dev_freeze event is required')
    if not events.precedes(chain, lambda e: e == frozen[0],
                           lambda e: e.type.startswith('t4_')):
        raise ValueError('pre_dev_freeze must precede T4')
    grid = freeze['tuning_grid']
    if (Decimal(freeze['t4_sub_cap_usd']) != Decimal('2.50')
            or Decimal(freeze['delta_NI']) != Decimal('0.10')
            or Decimal(freeze['delta_stale']) != Decimal('0.05')
            or grid['parameter_1']['name'] != 'fact_similarity_threshold'
            or grid['parameter_2']['name'] != 'fact_top_n'
            or sorted(Decimal(v) for v in grid['parameter_1']['values']) !=
            [Decimal('.30'), Decimal('.45'), Decimal('.60')]
            or sorted(int(v) for v in grid['parameter_2']['values']) != [1, 3, 5]
            or grid['points'] != 9 or grid['nothing_else_is_tuned'] is not True
            or not freeze.get('settlement_requirement')):
        raise ValueError('unexpected T4 frozen contract')
    # The freeze predates the generation-pricing snapshot and is hashed into
    # its own event, so it is never edited. The snapshot lives in its own
    # artifact, and is trusted only when the chain carries its digest.
    price = freeze.get('pricing_snapshot', {})
    if 'generation_model' not in price:
        pricing_path = paths.EVIDENCE_DIR / 'generation-pricing.json'
        digest = events.file_sha256(pricing_path)
        recorded = [e for e in events.verify(events_log)
                    if e.type == 'generation_pricing_recorded'
                    and e.payload.get('pricing_sha256') == digest]
        if len(recorded) != 1:
            raise ValueError('exactly one matching generation_pricing_recorded event is required')
        snapshot = read_json(pricing_path)
        price = {'generation_model': snapshot['model'],
                 'usd_per_million_input_tokens': snapshot['usd_per_million_input_tokens'],
                 'usd_per_million_output_tokens': snapshot['usd_per_million_output_tokens']}
    try:
        pricing = Pricing(price['generation_model'],
                          Decimal(price['usd_per_million_input_tokens']),
                          Decimal(price['usd_per_million_output_tokens']))
    except (KeyError, ArithmeticError, TypeError) as exc:
        raise ValueError('orchestrator must record a generation pricing snapshot') from exc
    if (pricing.model != MODEL or pricing.input_usd_per_million != Decimal('.15')
            or pricing.output_usd_per_million != Decimal('.60')):
        raise ValueError('unexpected frozen generation pricing')
    if not validate_prompts.run_check(cache_dir=cache_dir / 'generation',
                                     checks_dir=checks_dir, events_log=events_log)['passed']:
        raise ValueError('prompt check failed')
    guard = SpendGuard(ledger, stage='T4', ceiling_usd=Decimal('10'),
                       sub_cap_usd=Decimal(freeze['t4_sub_cap_usd']), pricing=pricing)
    _ledger_check(guard)
    return freeze, guard


def _write(checks_dir: Path, name: str, result: dict, events_log: Path,
           freeze_digest: str) -> None:
    checks_dir.mkdir(parents=True, exist_ok=True)
    output = checks_dir / f't4-{name}.json'
    output.write_bytes(events.canonical_bytes(result) + b'\n')
    events.append(events_log, f't4_{name}_complete', {
        'result_sha256': events.file_sha256(output), 'freeze_sha256': freeze_digest})


def _extraction(dataset: Dataset, pool: dict, complete: Complete) -> dict:
    stores, snapshots, metrics = [], {}, []
    non_conforming = rejected = 0
    for case in dataset.cases:
        aliases = {v['id']: v['aliases'][case.language] for v in pool['values']}
        store = FactStore(case.tenant_id, case.conversation_id, EXTRACTOR_VERSION)
        runs = []
        # Snapshot after the last user turn preceding each query; process every
        # user turn exactly once, including any following the final query.
        states = [(0, store, ())]
        for turn in sorted(case.turns, key=lambda m: m.sequence):
            if turn.role == 'user':
                run = extract_turn(store, case, turn, complete)
                runs.append(run)
                non_conforming += run.non_conforming_count
                rejected += run.rejected_count
                store = run.store
                states.append((turn.sequence, store, tuple(runs)))
        stores.append(asdict(store))
        for step in sorted(case.steps, key=lambda s: s.after_sequence):
            _, snapshot, step_runs = max((s for s in states if s[0] <= step.after_sequence),
                                         key=lambda s: s[0])
            snapshots[step.step_id] = asdict(snapshot)
            if not step.semantic:
                continue
            gold = list(gold_snapshot(case, step, aliases))
            gold.extend(lifecycle_gold(case, step, aliases))
            gold.extend(GoldFact(case.slot, value, eligible=False, prohibited=True)
                        for value in pool['prohibited_fixtures'])
            lifecycle = []
            # Authored stale/current snapshots define disposition; no inference
            # from model operations is allowed to become the gold standard.
            for value in step.stale_values:
                if step.gold_values:
                    lifecycle.append(LifecycleExpectation(case.slot, aliases[value][0],
                                     'superseded', aliases[step.gold_values[0]][0]))
                else:
                    lifecycle.append(LifecycleExpectation(case.slot, aliases[value][0], 'retracted'))
            metrics.append({'conceptual_case_id': case.conceptual_case_id,
                            'language': case.language, 'step_id': step.step_id,
                            **score_extraction(snapshot.facts, gold,
                                tenant_id=case.tenant_id, conversation_id=case.conversation_id,
                                user_message_ids=[m.message_id for m in case.turns
                                                  if m.role == 'user' and m.sequence <= step.after_sequence],
                                runs=step_runs, lifecycle=lifecycle)})
        # Counts over all turns are distinct from repeated snapshot metrics.
    return {'fact_stores': stores, 'snapshots': snapshots, 'metrics': metrics,
            'aggregate_metrics': aggregate_metrics(metrics),
            'user_turn_count': sum(m.role == 'user' for c in dataset.cases for m in c.turns),
            'non_conforming_count': non_conforming, 'rejected_count': rejected,
            'metric_unit': 'semantic query snapshot; cumulative failures per snapshot'}


def _fact_items(snapshot: dict) -> tuple[Item, ...]:
    return tuple(Item(f['tenant_id'], f['conversation_id'], f['fact_id'],
                      f['source_sequence'], f['statement'], tuple(f['source_message_ids']),
                      kind='fact', status=f['status'], value=f['value'])
                 for f in snapshot['facts'])


def _deliveries(store: PooledStore, case: Case, step: Step, snapshot: dict,
                embed: Embed, config: RetrievalConfig, *, only_c: bool = False) -> tuple:
    extracted = PooledStore(tuple(i for i in store.items if i.kind == 'turn') + _fact_items(snapshot))
    c = replace(retrieve(extracted, case, step, embed, config)[2], arm='C')
    if only_c:
        return (c,)
    a, b, oracle = retrieve(store, case, step, embed)
    scoped_turns = [i for i in store.scoped(case, step) if i.kind == 'turn']
    gold = [i for i in scoped_turns if set(i.source_message_ids) & set(step.gold_source_message_ids)]
    # GOLD-CONTEXT retains the recent window and bypasses retrieval, giving
    # authored evidence directly through the same renderer and shared cap.
    # Window identity comes from its causal suffix, never equal-text matching.
    window_messages = tuple(m for i in scoped_turns for m in i.messages)
    suffix = window_messages[-len(a.window):] if a.window else ()
    complete_ids = {m.message_id for m, w in zip(suffix, a.window)
                    if m.role == w.role and m.content == w.content}
    window_items = [i for i in scoped_turns if set(i.source_message_ids) <= complete_ids]
    diagnostic = pack_delivery('GOLD-CONTEXT', a.window, window_items, gold, (),
                               question=step.question,
                               max_chars=declared_limits()['chat_prompt_max_added_context_chars'])
    return a, b, c, oracle, diagnostic


def _observations(dataset: Dataset, pool: dict, snapshots: dict, embed: Embed,
                  complete: Complete, config: RetrievalConfig, *, only_c: bool = False) -> list[Observation]:
    store = PooledStore.from_dataset(dataset, pool)
    rows = []
    for case in dataset.cases:
        aliases = {v['id']: v['aliases'][case.language] for v in pool['values']}
        for step in case.steps:
            if only_c and not step.semantic:
                continue
            entries = []
            for value in case.value_set:
                roles = set()
                if value in step.gold_values:
                    roles.add('gold')
                if value in step.stale_values:
                    roles.add('stale')
                if value in {c.value_id for c in case.canaries}:
                    roles.add('canary')
                entries.append(ValueEntry(value, frozenset(aliases[value]), frozenset(roles or {'other'})))
            universe = ValueUniverse(tuple(entries))
            for delivery in _deliveries(store, case, step, snapshots[step.step_id],
                                        embed, config, only_c=only_c):
                request = answer_request(delivery, tenant_id=case.tenant_id,
                                         conversation_id=case.conversation_id,
                                         question=step.question, label=f'{step.step_id}:{delivery.arm}')
                result = complete(request)
                rows.append(Observation(case.conceptual_case_id, case.language, step.step_id,
                                        delivery.arm, classify(result.text, universe),
                                        step.semantic, step.h3, step.stale_eligible))
    return rows


def run(*, events_log: Path, ledger: Path, cache_dir: Path, checks_dir: Path,
        offline: bool, env_file: Path, stage: str = 'all',
        embedding_cache_dir: Path = paths.EVIDENCE_DIR / 'embedding-cache',
        dataset_path: Path = paths.DEV_DATASET, pool_path: Path = paths.DEV_POOL,
        freeze_path: Path = FREEZE_PATH, complete: Complete | None = None,
        embed: Embed | None = None) -> dict:
    """Injected completions are for hermetic tests; the CLI has no live path."""
    # Live dispatch is deliberately explicit: `--offline` replays from cache,
    # and only `live=True` (orchestrator-driven, operator-authorised stage)
    # loads the key. The guard is in the loop either way.
    if stage not in ('extraction', 'arms', 'tuning', 'all'):
        raise ValueError('unknown stage')
    for path in (dataset_path, pool_path, freeze_path, cache_dir, checks_dir, events_log, ledger):
        assert_not_heldout_path(path)
    freeze, guard = prerequisites(freeze_path, events_log, ledger, cache_dir, checks_dir)
    digests = {str(p): events.file_sha256(p) for p in (dataset_path, pool_path, freeze_path)}
    dataset, pool = load_dataset(dataset_path), load_pool(pool_path)
    if pool['pool'] != 'dev' or dataset.pool_sha256 != digests[str(pool_path)]:
        raise ValueError('matching dev dataset and pool required')
    api_key = None if offline else load_api_key(env_file)
    if not offline and not api_key:
        raise ValueError('live dispatch requested but no API key was found')
    generation = GenerationClient(cache_dir=cache_dir / 'generation', guard=guard,
                                  model=MODEL, offline=offline, api_key=api_key)
    # One embedding cache across stages: Task 3 paid for the turn and gold-fact
    # vectors, and re-embedding identical text would be waste, not evidence.
    # Arm C is the reason this is not cache-only -- its facts are EXTRACTED, so
    # their statements did not exist at Task 3 and must be embedded now, under
    # this stage's own guard and sub-cap.
    embeddings = EmbeddingClient(
        cache_dir=embedding_cache_dir,
        guard=None if offline else guard,
        offline=offline,
        api_key=api_key,
    )
    supplied_complete = complete or generation.complete

    def checked_complete(request: GenerationRequest) -> GenerationResult:
        rendered = events.canonical_bytes(list(request.messages)).decode('utf-8')
        if validate_prompts.findings(rendered):
            raise ValueError('rendered prompt check failed')
        result = supplied_complete(request)
        if result.model != MODEL:
            raise ValueError('generation model substitution')
        usage = result.usage
        if (not usage or any(type(usage.get(k)) is not int or usage[k] < 0
                             for k in ('prompt_tokens', 'completion_tokens'))):
            raise ValueError('provider-reported settlement usage required')
        return result

    embedding = embed or embeddings.embed
    metadata = {'freeze_sha256': digests[str(freeze_path)],
                'dataset_sha256': digests[str(dataset_path)], 'pool_sha256': digests[str(pool_path)]}
    results = {}
    for current in (('extraction', 'arms', 'tuning') if stage == 'all' else (stage,)):
        if current == 'extraction':
            result = dict(_extraction(dataset, pool, checked_complete), **metadata)
        else:
            extraction_path = checks_dir / 't4-extraction.json'
            assert_not_heldout_path(extraction_path)
            extraction_digest = events.file_sha256(extraction_path)
            if not any(e.type == 't4_extraction_complete'
                       and e.payload.get('result_sha256') == extraction_digest
                       and e.payload.get('freeze_sha256') == metadata['freeze_sha256']
                       for e in events.verify(events_log)):
                raise ValueError('extraction artifact lacks matching completion evidence')
            extraction = results.get('extraction') or read_json(extraction_path)
            if any(extraction.get(k) != v for k, v in metadata.items()):
                raise ValueError('extraction artifact does not match frozen inputs')
            if current == 'arms':
                rows = _observations(dataset, pool, extraction['snapshots'], embedding,
                                     checked_complete, RetrievalConfig())
                result = dict(metadata, observations=[r.record() for r in rows],
                              config=asdict(RetrievalConfig()))
            else:
                candidates = []
                for threshold in freeze['tuning_grid']['parameter_1']['values']:
                    for top_n in freeze['tuning_grid']['parameter_2']['values']:
                        config = RetrievalConfig(similarity_threshold=float(threshold), final_top_n=int(top_n))
                        rows = _observations(dataset, pool, extraction['snapshots'], embedding,
                                             checked_complete, config, only_c=True)
                        values = case_values(rows, 'semantic', 'C')
                        candidates.append({'threshold': float(threshold), 'top_n': int(top_n),
                                           'score': mean(values.values()) if values else None,
                                           'case_values': values, 'observations': [r.record() for r in rows]})
                selected = select_candidate(candidates)
                result = dict(metadata, candidates=candidates,
                              selected={k: selected[k] for k in ('threshold', 'top_n', 'score')},
                              selection_order=['score descending', 'top_n ascending', 'threshold descending'])
        _ledger_check(guard)
        if any(events.file_sha256(Path(p)) != digest for p, digest in digests.items()):
            raise ValueError('frozen inputs changed during T4')
        _write(checks_dir, 'observations' if current == 'arms' else current,
               result, events_log, metadata['freeze_sha256'])
        results[current] = result
    _ledger_check(guard)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events-log', type=Path, default=paths.EVENTS_LOG)
    parser.add_argument('--ledger', type=Path, default=paths.EVIDENCE_DIR / 't4-ledger.jsonl')
    parser.add_argument('--cache-dir', type=Path, default=paths.EVIDENCE_DIR / 't4-cache')
    parser.add_argument('--embedding-cache-dir', type=Path,
                        default=paths.EVIDENCE_DIR / 'embedding-cache',
                        help="shared with Task 3: identical text is embedded once")
    parser.add_argument('--checks-dir', type=Path, default=paths.CHECKS_DIR)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--live', action='store_true',
                        help='dispatch for real under the frozen sub-cap (orchestrator only)')
    parser.add_argument('--env-file', type=Path, default=paths.REPO_ROOT / '.env')
    parser.add_argument('--stage', choices=('extraction', 'arms', 'tuning', 'all'), default='all')
    args = vars(parser.parse_args(argv))
    live = args.pop('live')
    if live and args['offline']:
        parser.error('--live and --offline are mutually exclusive')
    if not live and not args['offline']:
        parser.error('choose one: --offline (replay from cache) or --live (dispatch)')
    args['offline'] = not live
    run(**args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
