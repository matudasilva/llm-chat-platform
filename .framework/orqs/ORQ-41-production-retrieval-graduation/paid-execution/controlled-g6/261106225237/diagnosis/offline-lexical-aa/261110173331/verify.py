"""Separate retained-data cross-check; no application imports or service access."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys


out = Path(__file__).resolve().parent
analysis = json.loads((out / 'analysis.json').read_text())
run = Path(analysis['run'])
checks = 0


def require(value):
    global checks
    if not value:
        raise ValueError('Offline diagnostic verification failed')
    checks += 1


require('sitecustomize' in sys.modules)
require(not any(line.split()[0] != 'lo' for line in Path('/proc/net/route').read_text().splitlines()[1:] if line.strip()))
require(os.environ.get('AWS_EC2_METADATA_DISABLED') == 'true')
require(analysis['status'] == 'OFFLINE_DIAGNOSTIC_COMPLETE_CAUSE_NOT_IDENTIFIED')
require(analysis['request_count'] == 1440 and analysis['measured'] == 800)
expected = {'EN-json': (14642350, 14444318), 'EN-sse': (15134931, 14790465),
            'ES-json': (16155431, 14904832), 'ES-sse': (14462488, 16463800)}
for cell in analysis['cells']:
    raw = {}
    for arm in ('c0', 'c1'):
        raw[arm] = [r for b in range(4) for r in json.loads(
            (run / f'{arm}-{cell["cell"]}-b{b}.json').read_text())['samples'] if not r['warmup']]
        require(len(raw[arm]) == 100)
        values = sorted({r['preparation_ns'] for r in raw[arm]})
        # The first duration with at least 95 samples at/below it is the p95.
        quantile = next(v for v in values if sum(r['preparation_ns'] <= v for r in raw[arm]) >= 95)
        actual = cell['arms'][arm]
        require(quantile == actual['distribution']['p95_ns'] == expected[cell['cell']][int(arm[-1])])
        tail = [r for r in raw[arm] if r['preparation_ns'] >= quantile]
        require(len(tail) == 6)
        require(dict(Counter(str(r['block']) for r in tail)) == actual['tail_six_by_block'])
        require(dict(Counter(r['category'] for r in tail)) == actual['tail_six_by_category'])
        require(set(actual['categories']) == {'document', 'history', 'combined', 'empty'})
        require(all(v['n'] == 25 for v in actual['categories'].values()))
        require(all(v['n'] == 5 for v in actual['cases'].values()))
    a, b = expected[cell['cell']]
    require((100 * a <= 105 * b and 100 * b <= 105 * a) == (cell['frozen_status'] == 'PASS'))
require(sum(c['frozen_status'] == 'FAIL' for c in analysis['cells']) == 2)
require(next(c for c in analysis['cells'] if c['cell'] == 'ES-json')['arms']['c0']['tail_six_by_block'] == {'1': 5, '3': 1})
require(next(c for c in analysis['cells'] if c['cell'] == 'ES-sse')['arms']['c1']['tail_six_by_block'] == {'0': 6})
require(all(w['api_cpu_delta']['nr_throttled'] == w['pg_cpu_delta']['nr_throttled'] == 0 for w in analysis['workers']))
require(all(v['blks_read'] == 0 for w in analysis['workers'] for v in w['database_delta'].values()))
require(sum(len(w['maintenance_changes']) for w in analysis['workers']) == 2)
original = json.loads((run / 'execution-review/completion.json').read_text())
for name, digest in original['artifacts_sha256'].items():
    require(hashlib.sha256((run / name).read_bytes()).hexdigest() == digest)
for name, digest in json.loads((run / 'execution-review/scope-before.json').read_text()).items():
    require(hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest)
audit = Path(os.environ['P2_NET_AUDIT_LOG'])
require(not audit.exists() or audit.stat().st_size == 0)
result = dict(status='OFFLINE_REPLAY_CROSS_CHECK_PASS', checks=checks,
              analysis_sha256=hashlib.sha256((out / 'analysis.json').read_bytes()).hexdigest(),
              new_requests=0, network_attempts=0, external_provider_calls=0,
              distinct_reviewer_claimed=False)
(out / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, sort_keys=True))
