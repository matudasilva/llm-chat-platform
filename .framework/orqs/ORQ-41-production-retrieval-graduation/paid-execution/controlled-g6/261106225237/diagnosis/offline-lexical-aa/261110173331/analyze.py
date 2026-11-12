"""Read retained A/A artifacts only. No application imports or service access."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
from collections import Counter


RUN = Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261110150634')
OUT = Path(__file__).resolve().parent
ARMS = ('c0', 'c1')
CELLS = ('EN-json', 'EN-sse', 'ES-json', 'ES-sse')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def distribution(rows):
    values = sorted(row['preparation_ns'] for row in rows)
    n = len(values)
    require(n > 0, 'Empty group')
    return dict(n=n, min_ns=values[0], p50_ns=values[(n * 50 + 99) // 100 - 1],
                p95_ns=values[(n * 95 + 99) // 100 - 1], max_ns=values[-1],
                mean_ns=statistics.mean(values))


def identify(row):
    return {key: row[key] for key in ('sample_id', 'case_id', 'category', 'block',
                                      'ordinal', 'request_id', 'preparation_ns')}


def main():
    require(not sys.flags.optimize, 'Optimized checks are not allowed')
    require('sitecustomize' in sys.modules, 'P2 socket guard missing')
    require(os.environ.get('AWS_EC2_METADATA_DISABLED') == 'true', 'Metadata discovery enabled')
    require(os.environ.get('APP_SETTINGS_ENV_FILE') == '', 'Settings dotenv not disabled')
    require(not any(key in os.environ for key in (
        'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
        'AWS_PROFILE', 'OPENAI_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS')), 'Credential environment present')
    routes = Path('/proc/net/route').read_text()
    require(all(line.split()[0] == 'lo' for line in routes.splitlines()[1:] if line.strip()),
            'Non-loopback IPv4 route present')
    ipv6 = Path('/proc/net/ipv6_route').read_text()
    require(all(line.split()[-1] == 'lo' for line in ipv6.splitlines() if line.strip()),
            'Non-loopback IPv6 route present')
    completion = read(RUN / 'execution-review/completion.json')
    require(completion['scientific_result'] == 'AA_CALIBRATION_FAIL', 'Unexpected retained status')
    hashes = dict(completion['artifacts_sha256'])
    hashes['execution-review/completion.json'] = sha(RUN / 'execution-review/completion.json')
    for name, digest in hashes.items():
        require(sha(RUN / name) == digest, 'Retained artifact drift: ' + name)
    protected = read(RUN / 'execution-review/scope-before.json')
    for name, digest in protected.items():
        require(sha(Path(name)) == digest, 'Protected source drift: ' + name)
    plan, result = read(RUN / 'plan.json'), read(RUN / 'result.json')
    require(sha(RUN / 'plan.json') == 'e3f6f8efae1de5858e3402ee131cead41a28a42050b7115ded5c08a26f53eb54', 'Plan changed')
    require(sha(RUN / 'result.json') == '592c5136dfbc4fa5106c5906c112fc6f056b764312af264615c25e9dd7005207', 'Result changed')
    workers, rows, observations = [], [], []
    schedule = plan['arm_cell_order']
    for sequence, entry in enumerate(schedule):
        arm, cell, block = entry['arm'], entry['cell'], entry['block']
        key = f'{arm}-{cell}-b{block}'
        worker, obs = read(RUN / (key + '.json')), read(RUN / (key + '-observations.json'))
        require(obs['entry'] == entry, 'Observation identity mismatch')
        samples = worker['samples']
        require(len(samples) == 45 and [r['warmup'] for r in samples] == [True] * 20 + [False] * 25,
                'Worker population mismatch')
        for row in samples:
            require(row['status'] == 'PASS' and row['error'] is None, 'Functional failure')
            require(row['preparation_ns'] == row['primary_dispatch_ns'] - row['start_ns'], 'Clock mismatch')
            rows.append(dict(row, arm=arm))
        measured = [r for r in samples if not r['warmup']]
        first = next(e['arm'] for e in schedule if e['cell'] == cell and e['block'] == block)
        maintenance = []
        for db in ARMS:
            before = {r['relname']: r for r in obs['db_before'][db]['maintenance']}
            after = {r['relname']: r for r in obs['db_after'][db]['maintenance']}
            require(before.keys() == after.keys(), 'Maintenance inventory mismatch')
            for table in before:
                if before[table] != after[table]:
                    maintenance.append(dict(database_arm=db, table=table, before=before[table], after=after[table]))
        workers.append(dict(**entry, sequence=sequence, first=arm == first,
            measured=distribution(measured), warmups=distribution(samples[:20]),
            measured_interval_sum_ns=sum(r['preparation_ns'] for r in measured),
            api_cpu_delta=worker['cpu_stat_delta'], pg_cpu_delta=obs['pg_delta'],
            database_delta=obs['db_delta'], maintenance_changes=maintenance,
            host_delta=obs['host_delta'], frequency_before_khz=obs['host_before']['reported_frequency_khz'],
            frequency_after_khz=obs['host_after']['reported_frequency_khz']))
        observations.append(obs)
    require(len(rows) == 1440 and len({(r['arm'], r['request_id']) for r in rows}) == 1440,
            'Admission population mismatch')
    require(len({r['accounting_instance_id'] for r in rows}) == 1440, 'C1 context reuse')
    cells = []
    for cell in CELLS:
        per_arm, by_id = {}, {}
        for arm in ARMS:
            measured = [r for r in rows if r['arm'] == arm and not r['warmup']
                        and r['language'] + '-' + r['protocol'] == cell]
            require(len(measured) == 100, 'Measured population mismatch')
            ordered = sorted(measured, key=lambda r: (r['preparation_ns'], r['sample_id']))
            tail = ordered[94:]
            per_arm[arm] = dict(distribution=distribution(measured),
                p95_determining_sample=identify(ordered[94]),
                ranks_90_through_100=[dict(rank=i + 1, **identify(ordered[i])) for i in range(89, 100)],
                tail_six_by_block=dict(Counter(str(r['block']) for r in tail)),
                tail_six_by_category=dict(Counter(r['category'] for r in tail)),
                categories={cat: distribution([r for r in measured if r['category'] == cat])
                            for cat in sorted({r['category'] for r in measured})},
                cases={case: distribution([r for r in measured if r['case_id'] == case])
                       for case in sorted({r['case_id'] for r in measured})},
                order={label: distribution([r for r in measured
                    if next(w['first'] for w in workers if w['arm'] == arm and w['cell'] == cell
                            and w['block'] == r['block']) == (label == 'first')])
                       for label in ('first', 'second')})
            by_id[arm] = {r['sample_id']: r for r in measured}
        require(by_id['c0'].keys() == by_id['c1'].keys(), 'Pairing mismatch')
        differences = []
        for key, a in by_id['c0'].items():
            b = by_id['c1'][key]
            for field in ('case_id', 'category', 'request_id', 'conversation_id', 'message', 'block', 'ordinal'):
                require(a[field] == b[field], 'Paired sample mismatch')
            differences.append(b['preparation_ns'] - a['preparation_ns'])
        a, b = (per_arm[arm]['distribution']['p95_ns'] for arm in ARMS)
        passed = a * 100 <= b * 105 and b * 100 <= a * 105
        original = next(r for r in result['cells'] if r['cell'] == cell)
        require((a, b, 'PASS' if passed else 'FAIL') ==
                (original['c0_p95_ns'], original['c1_p95_ns'], original['status']), 'Frozen replay mismatch')
        cells.append(dict(cell=cell, arms=per_arm, frozen_status=original['status'],
            symmetric_gap_percent=(max(a, b) / min(a, b) - 1) * 100,
            paired_descriptive=dict(n=len(differences), median_b_minus_a_ns=statistics.median(differences),
                mean_b_minus_a_ns=statistics.mean(differences), b_slower=sum(d > 0 for d in differences),
                b_faster=sum(d < 0 for d in differences), ties=sum(d == 0 for d in differences))))
    for name, digest in hashes.items():
        require(sha(RUN / name) == digest, 'Retained artifact changed during analysis')
    for name, digest in protected.items():
        require(sha(Path(name)) == digest, 'Protected source changed during analysis')
    audit = Path(os.environ['P2_NET_AUDIT_LOG'])
    require(not audit.exists() or audit.stat().st_size == 0, 'Unexpected network attempt')
    answer = dict(status='OFFLINE_DIAGNOSTIC_COMPLETE_CAUSE_NOT_IDENTIFIED', run=str(RUN),
        script_sha256=sha(Path(__file__)), retained_files_verified=len(hashes), protected_sources_verified=len(protected),
        historical_status='AA_CALIBRATION_FAIL', acceptance_rule_unchanged=True,
        request_count=1440, measured=800, warmups=640, cells=cells, workers=workers,
        p2=dict(network_namespace=os.readlink('/proc/self/ns/net'), ipv4_routes=routes,
                ipv6_routes=ipv6, credentials_absent=True, socket_guard_loaded=True,
                network_attempts=0, external_provider_calls=0, new_requests=0, spend_usd='0'),
        limitations=['Exploratory descriptive strata; none replaces or rescues the frozen pooled p95.',
            'Six highest observations include rank 95; the p95 is one fixed order statistic, not a mean of tails.',
            'CPU and PostgreSQL counters span complete workers, including warmups and untimed completion/cleanup.',
            'Host frequency snapshots are not effective frequencies during individual requests.',
            'Maintenance timestamps and database counters cannot localize causality within measured requests.',
            'No per-stage wall/CPU spans, per-request scheduling waits, or per-query plans are retained here.',
            'An A/A failure does not measure C1 overhead against C0, or disprove the separately reviewed SQL improvement.'])
    (OUT / 'analysis.json').write_text(json.dumps(answer, indent=2, sort_keys=True) + '\n')
    print(answer['status'])
    print(f"Verified {len(hashes)} retained files and {len(protected)} source/config files; no new requests.")
    for c in cells:
        print(c['cell'], c['frozen_status'], c['symmetric_gap_percent'])


if __name__ == '__main__':
    main()
