"""Retained-data replay only; no application, provider or database execution."""
from collections import Counter
import json
from pathlib import Path
import statistics
from experiments.production_graduation.gate_validation import stage_latency as d

out = Path(__file__).resolve().parent
run = out.parent
plan = d.read(run / 'plan.json')
d.validate_plan(plan, d.read(run / 'fixtures.json'), prepared=True)
d.hashes_match(plan)
arms = {'c0': [], 'c1': []}
files, groups, workers = {}, [], []
for entry in plan['arm_cell_order']:
    key = f'{entry["arm"]}-{entry["cell"]}-b0'
    path = run / (key + '.json')
    worker = d.read(path)
    d.validate_worker(worker, plan, entry)
    files[path.name] = d.sha_file(path)
    arms[entry['arm']].extend(worker['samples'])
    for row in worker['samples']:
        d.require(row['start_counters']['loop_native_id'] == row['primary_counters']['loop_native_id'], 'Thread identity drift')
    workers.append(dict(entry=entry, api_cpu_delta=worker['cpu_stat_delta'],
                        request_count=len(worker['samples'])))
    if entry['arm'] == 'c1':
        measured = [r for r in worker['samples'] if not r['warmup']]
        for category in ('document', 'history', 'combined', 'empty'):
            rows = [r for r in measured if r['category'] == category]
            groups.append(dict(cell=entry['cell'], category=category, n=len(rows),
                preparation_median_ns=statistics.median(r['preparation_ns'] for r in rows),
                process_cpu_median_ns=statistics.median(r['primary_counters']['process_cpu_ns'] - r['start_counters']['process_cpu_ns'] for r in rows),
                uncovered_median_ns=statistics.median(r['stage_summary']['uncovered_preparation_ns'] for r in rows),
                stage_wall_medians_ns={label: statistics.median(r['stage_summary']['labels'][label]['preparation_union_ns'] for r in rows)
                                       for label in rows[0]['stage_summary']['labels']}))
result = d.summarize(arms)
published = d.read(run / 'result.json')
d.require(all(result[k] == published[k] for k in result), 'Published replay differs')
d.require(published['worker_receipts'] == files, 'Worker hash mismatch')
d.require(len({(arm, r['request_id']) for arm, rows in arms.items() for r in rows}) == 360, 'Duplicate admission')
d.require(sum(not r['warmup'] for rows in arms.values() for r in rows) == 200, 'Measurement count mismatch')
final = d.read(out / 'final-databases-verification.json')
d.require(final['status'] == 'STAGE_DIAGNOSTIC_FINAL_DATABASES_READONLY_VERIFIER_PASS', 'Final persistence proof missing')
receipt = dict(status='PARENT_RETAINED_REPLAY_PASS', published_result_sha256=d.sha_file(run / 'result.json'),
    cells=result['cells'], groups=groups, workers=workers, requests=360, measured=200, warmups=160,
    c1_contexts=360, unique_admissions=360, final_db_receipt_sha256=d.sha_file(out / 'final-databases-verification.json'),
    causal_explanation_proven=False, official_g6_status='CONTROLLED_G6_FAIL', external_calls=0, spend_usd='0',
    limitations=['Exploratory instrumented stage envelopes; no exclusive SQL-server or scheduler attribution.',
                 'Nested wall intervals and independent medians must not be added.',
                 'ON/OFF differences include observation and time/order noise; no latency correction.',
                 'Process CPU is all-thread; async thread CPU includes other loop work.'])
d.exclusive(out / 'analysis.json', receipt)
print(receipt['status'])
