"""Independent retained-row replay. No API, SQL, Docker or provider operation."""
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from experiments.production_graduation.gate_validation.validate_g123 import check_p2
    check_p2()
    root = Path.cwd()
    run = Path(__file__).resolve().parent.parent
    plan = json.loads((run/'plan.json').read_text())
    actual = json.loads((run/'result.json').read_text())
    approval = json.loads((run/'independent-review.json').read_text())
    assert actual['plan_sha256'] == approval['plan_sha256'] == sha(run/'plan.json')
    assert approval['status'] == 'CONTROLLED_G6_HARNESS_INDEPENDENT_REVIEW_PASS'
    assert plan['n_per_cell_arm'] == 100 and plan['warmups_per_cell_arm'] == 5
    assert plan['sample_attempts'] == 1 and plan['relative_p95_limit_percent'] == 5
    assert plan['request_deadline_s'] == 300
    for name, digest in {**plan['harness_sha256'], **plan['support_files_sha256']}.items():
        assert sha(root/name) == digest
    assert set(actual['worker_receipts']) == {f'{arm}-{lang}-{protocol}.json'
        for arm in ('c0', 'c1') for lang in ('EN', 'ES') for protocol in ('json', 'sse')}
    population = {}
    instances = set()
    previous_end = -1
    total = measured = warmups = 0
    for cell in plan['arm_cell_order']:
        arm, label = cell['arm'], cell['cell']
        name = f'{arm}-{label}.json'
        path = run/name
        assert sha(path) == actual['worker_receipts'][name]
        worker = json.loads(path.read_text())
        assert worker['arm'] == arm and worker['config_identity'] == plan['config_sha256'][arm]
        assert worker['external_calls'] == worker['provider_calls'] == 0
        expected = [s for s in plan['samples'] if s['language']+'-'+s['protocol'] == label]
        rows = worker['samples']
        assert len(rows) == len(expected) == 105
        assert rows[0]['start_ns'] > previous_end
        ids = set()
        for row, sample in zip(rows, expected):
            assert all(row[k] == sample[k] for k in
                       ('sample_id', 'language', 'protocol', 'warmup', 'category', 'request_id', 'conversation_id'))
            assert row['sample_id'] not in ids
            ids.add(row['sample_id'])
            namespace = UUID(plan['namespace'])
            assert sample['request_id'] == str(uuid5(namespace, 'request/'+sample['sample_id']))
            assert sample['conversation_id'] == str(uuid5(namespace, sample['sample_id']))
            assert row['status'] == 'PASS' and row['error'] is None
            start, end = row['start_ns'], row['primary_dispatch_ns']
            assert type(start) is type(end) is int and end >= start > previous_end
            assert type(row['preparation_ns']) is int and row['preparation_ns'] == end-start
            previous_end = end
            assert [x['purpose'] for x in row['dispatches']] == ['rewrite', 'primary']
            assert all(len(x['sha256']) == 64 and all(c in '0123456789abcdef' for c in x['sha256'])
                       for x in row['dispatches'])
            instance = row['accounting_instance_id']
            if arm == 'c1':
                assert str(UUID(instance)) == instance and instance not in instances
                instances.add(instance)
            else:
                assert instance is None
            total += 1
            warmups += int(row['warmup'])
            measured += int(not row['warmup'])
        assert sum(row['warmup'] for row in rows) == 5
        assert Counter(row['category'] for row in rows if not row['warmup']) == Counter(
            {'document': 25, 'history': 25, 'combined': 25, 'empty': 25})
        population[arm, label] = rows
    assert (total, measured, warmups, len(instances)) == (840, 800, 40, 420)
    cells = []
    for language in ('EN', 'ES'):
        for protocol in ('json', 'sse'):
            label = language+'-'+protocol
            baseline, candidate = population['c0', label], population['c1', label]
            assert all(a['sample_id'] == b['sample_id'] and a['dispatches'] == b['dispatches']
                       for a, b in zip(baseline, candidate))
            a = sorted(row['preparation_ns'] for row in baseline if not row['warmup'])
            b = sorted(row['preparation_ns'] for row in candidate if not row['warmup'])
            assert len(a) == len(b) == 100
            # For N=100, nearest-rank p95 is the 95th observation, index94.
            passed = b[94]*100 <= a[94]*105
            found = next(c for c in actual['cells'] if c['language'] == language and c['protocol'] == protocol)
            for prefix, values in [('baseline', a), ('candidate', b)]:
                assert found[prefix+'_p50_ns'] == values[49]
                assert found[prefix+'_p95_ns'] == values[94]
                assert found[prefix+'_p99_ns'] == values[98]
                assert found[prefix+'_max_ns'] == values[-1]
            assert found['status'] == ('PASS' if passed else 'FAIL')
            assert found['n_per_arm'] == 100 and found['limit_percent'] == 5
            assert found['payload_and_call_parity'] is True
            cells.append({'language': language, 'protocol': protocol,
                          'baseline_p95_ns': a[94], 'candidate_p95_ns': b[94],
                          'overhead_percent': str((Decimal(b[94])/Decimal(a[94])-1)*100),
                          'status': found['status']})
    assert len(actual['cells']) == 4 and all(c['status'] == 'FAIL' for c in cells)
    assert actual['status'] == 'CONTROLLED_G6_FAIL'
    assert actual['external_calls'] == 0 and actual['spend_usd'] == '0'
    assert actual['live_absolute_bounds_claimed'] is False
    audit = run/'network-audit.log'
    assert not audit.exists() or not audit.read_text()
    result = {'status': 'CONTROLLED_G6_EXECUTION_REPLAY_VERIFIED_FAIL',
              'verifier_origin': '261106130053-rev2 independent retained-row verifier', 'executor': 'parent', 'current_independent_review': 'RETAINED_INDEPENDENT_RECEIPT_PRESENT', 'plan_sha256': sha(run/'plan.json'),
              'result_sha256': sha(run/'result.json'), 'verifier_sha256': sha(Path(__file__)),
              'worker_receipts': actual['worker_receipts'], 'total_requests': total,
              'measured_requests': measured, 'warmups': warmups, 'functional_failures': 0,
              'candidate_unique_accounting_instances': len(instances), 'cells': cells,
              'payload_and_call_parity': True, 'network_guard_attempts_observed': 0,
              'request_resends_by_reviewer': 0, 'reviewer_api_calls': 0,
              'reviewer_database_writes': 0, 'external_calls': 0, 'spend_usd': '0',
              'driver_exit_zero_is_gate_pass': False, 'live_absolute_bounds_claimed': False}
    out = Path(__file__).with_name('parent-replay-receipt.json')
    assert not out.exists()
    out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
