"""Prospective controlled C1/C0 timing contract; no provider or DB I/O."""
import math
from collections import Counter
from uuid import uuid5

WARMUPS = 5
SAMPLES = 100


def build_samples(cases, namespace):
    samples,fixtures,order=[],[],[]
    categories=('document','history','combined','empty')
    if len(cases)!=40 or len({c['case_id'] for c in cases})!=40:
        raise ValueError('Controlled case identities changed')
    for index,(language,protocol) in enumerate((('EN','json'),('EN','sse'),('ES','json'),('ES','sse'))):
        selected=sorted([c for c in cases if c['language']==language],key=lambda c:(categories.index(c['category']),c['case_id']))
        if Counter(c['category'] for c in selected)!=Counter({c:5 for c in categories}):
            raise ValueError('Controlled language composition changed')
        for ordinal in range(SAMPLES+WARMUPS):
            warm=ordinal<WARMUPS;case=selected[ordinal if warm else (ordinal-WARMUPS)%20]
            key=f'{language}/{protocol}/{ordinal}'
            sample={'sample_id':key,'language':language,'protocol':protocol,'warmup':warm,'category':case['category'],
                    'conversation_id':str(uuid5(namespace,key)),'request_id':str(uuid5(namespace,'request/'+key)),
                    'tenant_id':case['tenant_id'],'message':case['message']}
            samples.append(sample);fixtures.append({'sample':sample,'messages':case['history']})
        for arm in (('c0','c1') if index%2==0 else ('c1','c0')): order.append({'arm':arm,'cell':language+'-'+protocol})
    return samples,fixtures,order


def percentile(values, fraction):
    if not values or any(type(x) is not int or x < 0 for x in values):
        raise ValueError('Invalid controlled timing population')
    return sorted(values)[math.ceil(fraction * len(values)) - 1]


def summarize(arms):
    result = []
    for language in ('EN', 'ES'):
        for protocol in ('json', 'sse'):
            paired = {}
            for arm in ('c0', 'c1'):
                rows = [row for row in arms[arm] if row['language'] == language and row['protocol'] == protocol]
                if len(rows) != SAMPLES + WARMUPS or any(row['status'] != 'PASS' for row in rows):
                    raise ValueError('Incomplete/failed controlled timing cell')
                for row in rows:
                    if type(row['warmup']) is not bool:
                        raise ValueError('Invalid warmup marker')
                    if ([d['purpose'] for d in row['dispatches']] != ['rewrite','primary']
                            or any(len(d['sha256'])!=64 or any(c not in '0123456789abcdef' for c in d['sha256']) for d in row['dispatches'])):
                        raise ValueError('Invalid native dispatch evidence')
                measured = [row for row in rows if not row['warmup']]
                if len(measured) != SAMPLES or len({row['sample_id'] for row in rows}) != len(rows):
                    raise ValueError('Missing or duplicate controlled sample')
                if Counter(row['category'] for row in measured) != Counter({key:25 for key in ('document','history','combined','empty')}):
                    raise ValueError('Controlled composition changed')
                paired[arm] = {row['sample_id']:row for row in rows}
            if paired['c0'].keys() != paired['c1'].keys():
                raise ValueError('Unpaired controlled identities')
            for identity, baseline in paired['c0'].items():
                candidate = paired['c1'][identity]
                if any(baseline[key]!=candidate[key] for key in ('warmup','category','language','protocol')):
                    raise ValueError('Controlled paired population changed')
                if baseline['dispatches'] != candidate['dispatches']:
                    raise ValueError('Native payload/call-count parity failed')
            baseline = [row['preparation_ns'] for row in paired['c0'].values() if not row['warmup']]
            candidate = [row['preparation_ns'] for row in paired['c1'].values() if not row['warmup']]
            a,b = percentile(baseline,.95),percentile(candidate,.95)
            # Integer arithmetic implements the approved +5% and zero-baseline rule.
            passed = b * 100 <= a * 105
            result.append({'language':language,'protocol':protocol,'n_per_arm':SAMPLES,
                           'baseline_p50_ns':percentile(baseline,.5),'candidate_p50_ns':percentile(candidate,.5),
                           'baseline_p95_ns':a,'candidate_p95_ns':b,'limit_percent':5,
                           'baseline_p99_ns':percentile(baseline,.99),'candidate_p99_ns':percentile(candidate,.99),
                           'baseline_max_ns':max(baseline),'candidate_max_ns':max(candidate),
                           'status':'PASS' if passed else 'FAIL','payload_and_call_parity':True})
    return {'status':'CONTROLLED_G6_PASS' if all(row['status']=='PASS' for row in result) else 'CONTROLLED_G6_FAIL',
            'cells':result,'external_calls':0,'spend_usd':'0','live_absolute_bounds_claimed':False}
