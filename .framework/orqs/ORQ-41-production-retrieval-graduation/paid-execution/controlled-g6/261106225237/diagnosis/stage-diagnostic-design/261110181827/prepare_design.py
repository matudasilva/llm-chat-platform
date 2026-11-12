"""Build a non-executable stage-diagnostic preview from retained files only."""
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, UUID, uuid5


ROOT = Path.cwd()
ORQ = Path('.framework/orqs/ORQ-41-production-retrieval-graduation')
DIAG = ORQ / 'paid-execution/controlled-g6/261106225237/diagnosis'
RUN = DIAG / 'blocked-runs/261110150634'
OUT = Path(__file__).resolve().parent
checks = 0


def require(value, message):
    global checks
    if not value:
        raise ValueError(message)
    checks += 1


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def main():
    require(not sys.flags.optimize, 'Optimized validation is not allowed')
    require('sitecustomize' in sys.modules, 'Missing P2 guard')
    require(os.environ.get('AWS_EC2_METADATA_DISABLED') == 'true', 'Metadata discovery enabled')
    require(os.environ.get('APP_SETTINGS_ENV_FILE') == '', 'Dotenv discovery enabled')
    require(not any(key in os.environ for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
        'AWS_SESSION_TOKEN', 'AWS_PROFILE', 'OPENAI_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS')),
        'Unexpected credentials')
    for name, position in (('/proc/net/route', 0), ('/proc/net/ipv6_route', -1)):
        lines = Path(name).read_text().splitlines()
        if position == 0:
            lines = lines[1:]
        require(all(line.split()[position] == 'lo' for line in lines if line.strip()), 'External route present')
    protected = read(RUN / 'execution-review/scope-before.json')
    for name, digest in protected.items():
        require(sha(Path(name)) == digest, 'Protected source changed: ' + name)
    original = read(RUN / 'execution-review/completion.json')
    for name, digest in original['artifacts_sha256'].items():
        require(sha(RUN / name) == digest, 'Original evidence changed: ' + name)
    offline = DIAG / 'offline-lexical-aa/261110173331'
    for name, digest in read(offline / 'completion.json')['artifacts_sha256'].items():
        require(sha(offline / name) == digest, 'Offline evidence changed: ' + name)
    plan, fixtures = read(RUN / 'plan.json'), read(RUN / 'fixtures.json')
    require(sha(RUN / 'plan.json') == 'e3f6f8efae1de5858e3402ee131cead41a28a42050b7115ded5c08a26f53eb54', 'Plan drift')
    namespace = uuid5(NAMESPACE_URL, str(OUT.relative_to(ROOT)))
    preview = []
    for fixture in fixtures:
        original_sample = fixture['sample']
        if original_sample['block'] != 0:
            continue
        sample = dict(original_sample)
        sample.update(request_id=str(uuid5(namespace, 'request/' + sample['sample_id'])),
                      conversation_id=str(uuid5(namespace, sample['sample_id'])))
        preview.append(dict(sample=sample, original_sample_id=original_sample['sample_id'],
            history_message_count=len(fixture['messages']),
            history_content_sha256=hashlib.sha256(json.dumps(fixture['messages'],
                sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(),
            history_uuid_rule='uuid5(preview_namespace, sample_id + /history/ + decimal_index)'))
    require(len(preview) == 180, 'Unexpected preview population')
    require(sum(p['history_message_count'] for p in preview) == 4224, 'History count changed')
    ids = {p['sample']['request_id'] for p in preview} | {p['sample']['conversation_id'] for p in preview}
    require(len(ids) == 360 and all(str(UUID(v)) == v for v in ids), 'Preview UUID reuse/format')
    prior_plans = {}
    for path in sorted((ORQ / 'paid-execution/controlled-g6').rglob('plan.json')):
        data = read(path)
        samples = data.get('samples', [])
        old = {s[field] for s in samples for field in ('request_id', 'conversation_id') if field in s}
        require(not ids & old, 'Preview collides with historical plan: ' + str(path))
        prior_plans[str(path)] = sha(path)
    order = []
    for cell, modes in [('EN-json', ['off', 'on']), ('EN-sse', ['on', 'off']),
                        ('ES-json', ['on', 'off']), ('ES-sse', ['off', 'on'])]:
        selected = [p['sample'] for p in preview if p['sample']['language'] + '-' + p['sample']['protocol'] == cell]
        require(len(selected) == 45, 'Cell population mismatch')
        require([s['warmup'] for s in selected] == [True] * 20 + [False] * 25, 'Warmup/order mismatch')
        require(Counter(s['category'] for s in selected[:20]) == dict.fromkeys(('document', 'history', 'combined', 'empty'), 5), 'Warmup composition changed')
        for mode in modes:
            order.append(dict(cell=cell, mode=mode, full_c1=True, block=0))
    require(len(order) == 8, 'Wrong worker count')
    require(sum(p['sample']['warmup'] for p in preview) * 2 == 160, 'Wrong warmup volume')
    require(sum(not p['sample']['warmup'] for p in preview) * 2 == 200, 'Wrong measurement volume')
    seams = {
        'app/services/conversation_history_adapter.py': ['SqlConversationHistoryAdapter.fetch_ordered'],
        'app/core/domain/retrieval_pipeline.py': ['RetrievalPipeline.retrieve', 'RetrievalPipeline._rewrite', 'RetrievalPipeline._rerank'],
        'app/core/providers/pgvector_store.py': ['PgVectorStore.hybrid_search'],
        'app/core/domain/added_context_budget.py': ['enforce_added_context_cap'],
        'app/core/providers/bedrock_provider.py': ['_build_payload'],
    }
    inventory = []
    for name, targets in seams.items():
        tree = ast.parse(Path(name).read_text())
        found = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[node.name] = node
            elif isinstance(node, ast.ClassDef):
                found.update({node.name + '.' + item.name: item for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))})
        for target in targets:
            require(target in found, 'Missing seam: ' + target)
            node = found[target]
            inventory.append(dict(file=name, file_sha256=sha(Path(name)), callable=target,
                line=node.lineno, asynchronous=isinstance(node, ast.AsyncFunctionDef)))
    helpers = ['blocked_latency.py', 'blocked_latency_worker.py', 'controlled_latency_profile.py',
               'wait_observer.py', 'controlled_latency.py', 'local_api.py', 'transports.py',
               'capture.py', 'performance_cleanup.py', 'aa_calibration_resources.py']
    helper_hashes = {str(Path('experiments/production_graduation/gate_validation') / name):
        sha(Path('experiments/production_graduation/gate_validation') / name) for name in helpers}
    for path in ['stage_latency.py', 'stage_latency_worker.py', 'stage_latency_observer.py']:
        require(not (Path('experiments/production_graduation/gate_validation') / path).exists(), 'Unexpected implementation')
    require(not Path('tests/experiments/test_orq41_stage_latency.py').exists(), 'Unexpected implementation')
    require(not (OUT / 'plan.json').exists() and not (OUT / 'execution-started.json').exists(), 'Design is executable')
    write('fixtures.preview.json', preview)
    write('seam-inventory.json', dict(seams=inventory, helpers_sha256=helper_hashes,
        limitation='Original blocked run_block exposes no endpoint callback; derive a separate diagnostic loop, never wrap after bookkeeping.',
        prior_plan_inventory=prior_plans))
    write('contract.preview.json', dict(status='DESIGN_PROPOSED_NOT_APPROVED_NOT_EXECUTABLE',
        schema='orq41-stage-diagnostic-design-v1', not_a_gate=True, implementation_authorized=False,
        preparation_authorized=False, execution_authorized=False, run_id=OUT.name,
        preview_namespace=str(namespace), source_plan_sha256=sha(RUN / 'plan.json'),
        fixtures_preview_sha256=sha(OUT / 'fixtures.preview.json'),
        source_fixture_sha256=sha(RUN / 'fixtures.json'), proposal_sha256=sha(OUT / 'proposal.md'),
        images={mode: plan['images']['c1'] for mode in ('off', 'on')},
        postgres_image=plan['postgres_image'], auxiliary_images=plan['auxiliary_images'],
        resources=plan['resources'], normalized_config_reference_sha256=plan['normalized_config_sha256'],
        effective_configuration_verified_now=False, environment='NOT_PROVISIONED',
        prospective_databases={mode: 'orq41_stage_' + OUT.name + '_' + mode for mode in ('off', 'on')},
        order=order, full_c1_both_modes=True, total_local_requests=360, measured=200, warmups=160,
        concurrency=1, attempts_per_identity=1, executions=1, prepared_conversations_per_mode=180,
        prepared_history_messages_per_mode=4224, expected_final_messages_per_mode=4584,
        request_deadline_s=300, cleanup_bound_s=10, expected_new_local_provider_spend_usd='0',
        boundary=plan['boundary'], no_statistical_gate=True, no_p95_correction=True,
        observer_limit_per_request=dict(coarse=128, existing_wait_events=256),
        global_state='In Progress / Implement / DECISION_FREEZE_PASS',
        official_g6_status='CONTROLLED_G6_FAIL', paid_admission='BLOCKED_CONTROLLED_G6_FAIL'))
    for name, digest in protected.items():
        require(sha(Path(name)) == digest, 'Source changed during design')
    audit = Path(os.environ['P2_NET_AUDIT_LOG'])
    require(not audit.exists() or audit.stat().st_size == 0, 'Network attempt recorded')
    write('validation.json', dict(status='PURE_DESIGN_PREVIEW_CHECKS_PASS', checks=checks,
        prior_plans_checked=len(prior_plans), protected_sources_unchanged=len(protected),
        retained_execution_artifacts_verified=len(original['artifacts_sha256']) + 1,
        runtime_seams_found=len(inventory), new_harness_implemented=False, actual_requests=0,
        service_operations=0, external_provider_calls=0, network_attempts=0, spend_usd='0',
        independent_review_claimed=False, script_sha256=sha(Path(__file__))))
    print(f'PURE_DESIGN_PREVIEW_CHECKS_PASS: {checks} checks; 360 prospective requests; actual requests=0')


if __name__ == '__main__':
    main()
