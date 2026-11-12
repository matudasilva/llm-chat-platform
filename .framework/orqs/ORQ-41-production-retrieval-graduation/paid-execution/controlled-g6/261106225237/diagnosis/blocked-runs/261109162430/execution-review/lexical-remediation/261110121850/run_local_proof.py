"""Freeze then execute bounded, request-free lexical SQL proof under P2.

Existing diagnostic programs are reused unchanged. No image build, /chat,
provider, A/A or formal G6 execution is performed. Execution is one-shot.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from experiments.production_graduation.gate_validation import blocked_latency as h
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

OUT = Path(__file__).resolve().parent
REVIEW = OUT.parents[1]
COMMON = REVIEW / 'sql-diagnostic/run_sql_diagnostic.py'
PLAN = REVIEW / 'plan-comparison/run_plan_comparison.py'
WORKER = REVIEW / 'driver-diagnostic/driver_worker.py'
OLD_DRIVER = REVIEW / 'driver-diagnostic/261109222205/manifest.json'
spec = importlib.util.spec_from_file_location('immutable_plan_program', PLAN)
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)
c = plan.common
LABELS = ('original', 'candidate-2')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    h.write_json(path, value)


def scope_unchanged():
    scope = json.loads((OUT / 'scope-before.json').read_text())
    assert all(sha(h.ROOT / name) == digest for name, digest in scope.items())
    return len(scope)


def freeze():
    check_p2()
    scope_unchanged()
    assert not (OUT / 'local-proof-manifest.json').exists()
    suite = ET.parse(OUT/'candidate-2-regression.xml').getroot().find('testsuite')
    assert int(suite.attrib['tests']) == 239
    assert all(int(suite.attrib.get(key,0)) == 0 for key in ('failures','errors','skipped'))
    env = json.loads((OUT / 'environment-preflight.json').read_text())
    old = json.loads(OLD_DRIVER.read_text())
    assert len(old['slots']) == 30
    targets = [s for s in old['slots'] if s['phase'] == 'diagnostic']
    assert len(targets) == 10
    identities, programs = {}, {}
    for label in LABELS:
        probe = json.loads((OUT / (label + '-source-probe.json')).read_text())
        assert probe['actual_bind_order'] == ['query_embedding', 'top_k', 'query_text', 'rrf_k']
        assert probe['compiled_sql_sha256'] == sha(OUT / (label + '-compiled-query.sql'))
        identities[label] = probe
        directory = OUT / ('driver-' + label)
        directory.mkdir(mode=0o700)
        manifest = dict(old, run_id=OUT.name + '-' + label,
                        image_source_sha256=probe['sources'], worker_sha256=sha(WORKER),
                        original_scope='Authorized lexical remediation; not a gate or A/A')
        write(directory / 'manifest.json', manifest)
    assert identities['original']['config_identity'] == identities['candidate-2']['config_identity']
    vector = '[' + ','.join(str(float(v)) for v in old['vector']) + ']'
    slots = []
    directory = OUT / 'plans'
    directory.mkdir(mode=0o700)
    for index, target in enumerate(targets):
        for mode in ('force_custom_plan', 'force_generic_plan'):
            order = LABELS if index % 2 == 0 else LABELS[::-1]
            for label in order:
                slot = dict(case_id=target['case_id'], category=target['category'],
                            tenant_id=target['tenant_id'], query_text=target['query_text'],
                            top_k=20, rrf_k=60, mode=mode, label=label)
                key = f'{len(slots):02}-{label}-{slot["case_id"]}-{mode}'
                program = plan.case_program((OUT / (label + '-compiled-query.sql')).read_text(), vector, slot)
                h.private_write(directory / (key + '.sql'), program.encode())
                programs[key + '.sql'] = sha(directory / (key + '.sql'))
                slots.append(dict(key=key, **slot))
    assert len(slots) == 40
    manifest = dict(schema='orq41-lexical-remediation-local-proof-v1',
        frozen_at=datetime.now(timezone.utc).isoformat(), controller_sha256=sha(Path(__file__)),
        plan_helper_sha256=sha(PLAN), common_helper_sha256=sha(COMMON), worker_sha256=sha(WORKER),
        original_driver_manifest_sha256=sha(OLD_DRIVER), environment_sha256=sha(OUT/'environment-preflight.json'),
        candidate_module_sha256=sha(OUT/'candidate-2-pgvector_store.py'),
        original_module_sha256=sha(OUT/'original-pgvector_store.py'),
        regression_xml_sha256=sha(OUT/'candidate-2-regression.xml'),
        test_module_sha256=sha(h.ROOT/'tests/core/test_pgvector_query_equivalence.py'),
        candidate_design_review_sha256=sha(OUT/'candidate-2-design-review.json'),
        identities=identities, plans=slots, plan_sql_sha256=programs,
        driver_manifests_sha256={label:sha(OUT/('driver-'+label)/'manifest.json') for label in LABELS},
        explain_executions=40, adapter_calls=60, adapter_calls_per_variant=30,
        concurrency=1, repetitions=1, automatic_retries=0, analyze_before_plans=list(h.TABLES),
        runtime_plan_cache_mode='auto', forced_modes_only_in_local_explain_transactions=True,
        statement_timeout_s=30, lock_timeout_s=5, external_provider_calls=0,
        api_requests=0, spend_usd='0', not_a_gate=True,
        limitations=['Single run; shared cluster state and order effects.',
                    'Prepared EXPLAIN timing and adapter timing are different measurements.',
                    'Does not establish the historical A/A gap cause or a G6 PASS.'])
    write(OUT / 'local-proof-manifest.json', manifest)
    print('LOCAL_PROOF_VOLUME_FROZEN: 40 EXPLAIN, 60 adapter calls, no requests')


def nodes(node):
    yield node
    for child in node.get('Plans', []):
        yield from nodes(child)


def driver_command(label, env):
    directory = OUT / ('driver-' + label)
    mounts = [(h.ROOT/'experiments','/app/experiments'), (h.ROOT/'.framework','/app/.framework'),
              (h.ORQ/'campaign-redesign/p2_netguard','/p2_netguard'),
              (OUT/(label+'-pgvector_store.py'),'/app/app/core/providers/pgvector_store.py')]
    args = ['run','--rm','--pull=never','--network','container:'+env['container'],
            '--user=1000:1000','--cpus=2','--cpuset-cpus=0,2','--memory=2147483648',
            '--memory-swap=2147483648','--env-file',env['private_state']+'/tests.env']
    for source, target in mounts:
        args += ['--mount',f'type=bind,src={source},dst={target},readonly']
    args += ['--mount',f'type=bind,src={OUT},dst=/validation',
             '-e','DRIVER_RUN_DIR=/validation/driver-'+label,
             '-e','DRIVER_MANIFEST_SHA='+sha(directory/'manifest.json'),
             '--entrypoint','python',env['app_image'],
             str(Path('/app')/WORKER.relative_to(h.ROOT))]
    return c.DOCKER + args


def execute():
    check_p2()
    manifest = json.loads((OUT/'local-proof-manifest.json').read_text())
    assert manifest['controller_sha256'] == sha(Path(__file__))
    assert manifest['plan_helper_sha256'] == sha(PLAN) and manifest['worker_sha256'] == sha(WORKER)
    assert manifest['common_helper_sha256'] == sha(COMMON)
    assert manifest['environment_sha256'] == sha(OUT/'environment-preflight.json')
    assert manifest['original_driver_manifest_sha256'] == sha(OLD_DRIVER)
    assert manifest['candidate_module_sha256'] == sha(OUT/'candidate-2-pgvector_store.py')
    assert manifest['original_module_sha256'] == sha(OUT/'original-pgvector_store.py')
    assert manifest['regression_xml_sha256'] == sha(OUT/'candidate-2-regression.xml')
    assert manifest['test_module_sha256'] == sha(h.ROOT/'tests/core/test_pgvector_query_equivalence.py')
    assert manifest['candidate_design_review_sha256'] == sha(OUT/'candidate-2-design-review.json')
    assert all(sha(OUT/'plans'/name) == value for name,value in manifest['plan_sql_sha256'].items())
    assert all(sha(OUT/('driver-'+label)/'manifest.json') == digest
               for label,digest in manifest['driver_manifests_sha256'].items())
    for label in LABELS:
        assert manifest['identities'][label]['compiled_sql_sha256'] == sha(OUT/(label+'-compiled-query.sql'))
    scope_unchanged()
    assert not (OUT/'local-proof-started.json').exists()
    env = json.loads((OUT/'environment-preflight.json').read_text())
    info = json.loads(c.invoke('inspect',env['container']))[0]
    assert info['Id'] == env['id'] and info['Image'] == env['postgres_image']
    assert info['State']['Running'] and info['HostConfig']['NetworkMode'] == 'none'
    assert not info['HostConfig'].get('PortBindings')
    write(OUT/'local-proof-started.json',dict(manifest_sha256=sha(OUT/'local-proof-manifest.json'),
                                           started_at=datetime.now(timezone.utc).isoformat()))
    results, drivers, error, cleanup = [], {}, None, None
    try:
        for table in manifest['analyze_before_plans']:
            c.sql(env['container'],env['database'],'ANALYZE "public"."'+table+'";')
        before = c.identity(env['container'],env['database'],dict(schema_sha256=env['p3']['schema_sha256']))
        write(OUT/'local-proof-preflight.json',before)
        for index,slot in enumerate(manifest['plans']):
            key = slot['key']
            directory = OUT/'plans'
            write(directory/(key+'-admitted.json'),dict(index=index,attempt=1,slot=slot,
                                                       manifest_sha256=sha(OUT/'local-proof-manifest.json')))
            command = c.DOCKER+['exec','-i',env['container'],'psql','-X','-q','-A','-t',
                                '-v','ON_ERROR_STOP=1','-U','rag_app','-d',env['database']]
            process = subprocess.run(command,input=(directory/(key+'.sql')).read_bytes(),
                                     capture_output=True,timeout=45)
            h.private_write(directory/(key+'-stdout.log'),process.stdout)
            h.private_write(directory/(key+'-stderr.log'),process.stderr)
            assert process.returncode == 0, 'Plan execution failed: '+key
            meta,plans,after = c.decode_documents(process.stdout.decode())
            assert meta['current_user'] == meta['session_user'] == 'rag_app'
            assert meta['read_only'] == meta['row_security'] == 'on'
            assert meta['tenant'] == slot['tenant_id'] and meta['superuser'] is meta['bypass_rls'] is False
            assert meta['settings']['plan_cache_mode'] == slot['mode']
            assert dict(meta['settings'],plan_cache_mode='auto') == before['settings']
            counts = after['prepared_after']
            assert counts['parameter_types'] == '{vector,bigint,text,bigint}'
            assert counts['generic_plans']+counts['custom_plans'] == 1
            assert counts['generic_plans' if slot['mode']=='force_generic_plan' else 'custom_plans'] == 1
            assert plans[0]['Plan']['Actual Rows'] == 20
            if slot['label'] == 'candidate-2':
                tree = list(nodes(plans[0]['Plan']))
                for cte in ('semantic','lexical_query'):
                    producers = [node for node in tree if node.get('Subplan Name') == 'CTE '+cte]
                    assert len(producers) == 1 and producers[0]['Actual Loops'] == 1
                    assert producers[0]['Actual Rows'] == (20 if cte=='semantic' else 1)
                for node in tree:
                    assert 'plainto_tsquery' not in node.get('Filter','')
            row = dict(index=index,slot=slot,status='PASS',metadata=meta,prepared_after=counts,explain=plans[0])
            write(directory/(key+'-result.json'),row)
            results.append(row)
        for label in LABELS:
            directory = OUT/('driver-'+label)
            write(directory/'execution-started.json',dict(manifest_sha256=sha(directory/'manifest.json')))
            command = driver_command(label,env)
            write(directory/'command.json',dict(argv=command))
            process = subprocess.run(command,capture_output=True,timeout=180)
            h.private_write(directory/'stdout.log',process.stdout)
            h.private_write(directory/'stderr.log',process.stderr)
            assert process.returncode == 0, 'Adapter diagnostic failed: '+label
            drivers[label] = json.loads((directory/'worker.json').read_text())
            assert drivers[label]['status'] == 'DRIVER_DIAGNOSTIC_COMPLETE'
            assert drivers[label]['successful_adapter_calls'] == drivers[label]['adapter_invocations_begun'] == 30
        for old,new in zip(drivers['original']['rows'],drivers['candidate-2']['rows'],strict=True):
            assert old['result_sha256'] == new['result_sha256']
            assert old['output_projection'] == new['output_projection']
        after = c.identity(env['container'],env['database'],dict(schema_sha256=env['p3']['schema_sha256']))
        assert before == after
        assert c.readonly(env['container'],env['empty_database'],
                          'SELECT (SELECT count(*) FROM documents),(SELECT count(*) FROM chunks);').strip() == '0|0'
        scope_unchanged()
        for audit in (OUT/'network-audit.log',Path('/tmp/orq41-lexical-remediation-network.log')):
            assert not audit.exists() or audit.stat().st_size == 0
        write(OUT/'local-proof-postflight.json',dict(status='PASS',database=after,
              protected_files_unchanged=scope_unchanged(),external_calls=0,app_requests=0,spend_usd='0'))
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)[:250]
    finally:
        try:
            c.invoke('stop','--time','10',env['container'],timeout=25)
            assert not json.loads(c.invoke('inspect',env['container']))[0]['State']['Running']
            cleanup = dict(status='STOPPED_DATA_RETAINED',container=env['container'],no_resume=True)
        except Exception as exc:
            cleanup = dict(status='FAILED',error=type(exc).__name__)
        write(OUT/'local-proof-cleanup.json',cleanup)
    complete = not error and len(results)==40 and len(drivers)==2 and cleanup['status']=='STOPPED_DATA_RETAINED'
    write(OUT/'local-proof-result.json',dict(status='LOCAL_LEXICAL_PROOF_PASS' if complete else 'LOCAL_LEXICAL_PROOF_FAILED',
        error=error,explain_executions_resolved=len(results),driver_calls_resolved=sum(d['successful_adapter_calls'] for d in drivers.values()),
        manifest_sha256=sha(OUT/'local-proof-manifest.json'),cleanup=cleanup,external_calls=0,api_requests=0,
        spend_usd='0',official_g6_status='CONTROLLED_G6_FAIL',paid_admission='BLOCKED_CONTROLLED_G6_FAIL'))
    print('LOCAL_LEXICAL_PROOF_PASS' if complete else 'LOCAL_LEXICAL_PROOF_FAILED',error or '')
    if not complete:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('freeze','execute'))
    args = parser.parse_args()
    freeze() if args.action == 'freeze' else execute()
