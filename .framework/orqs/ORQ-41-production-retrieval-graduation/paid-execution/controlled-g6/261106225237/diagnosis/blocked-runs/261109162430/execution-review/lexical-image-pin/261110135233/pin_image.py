"""One approved offline image overlay; preserve all historical image/run pins."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from experiments.production_graduation.gate_validation.validate_g123 import check_p2

OUT = Path(__file__).resolve().parent
ROOT = Path.cwd()
PREVIOUS = OUT.parents[1]/'lexical-remediation/261110121850'
DOCKER = ['docker','--host','unix:///var/run/docker.sock']
PARENT = 'sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707'
SOURCE = ROOT/'app/core/providers/pgvector_store.py'
TAG = 'orq41-local:lexical-sql-'+OUT.name
CONFIG_KEYS = ('Env','Cmd','Entrypoint','WorkingDir','User','ExposedPorts','Volumes',
               'Healthcheck','StopSignal','Shell','OnBuild','ArgsEscaped','Labels')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as handle:
        handle.write(json.dumps(value,indent=2)+'\n')
        handle.flush()
        os.fsync(handle.fileno())


def call(args, timeout=90):
    process = subprocess.run(DOCKER+args,capture_output=True,timeout=timeout)
    if process.returncode:
        raise RuntimeError('Docker operation failed: '+args[0]+': '+process.stderr.decode()[:500])
    return process.stdout


def inspect(image):
    return json.loads(call(['image','inspect',image]))[0]


def summary(info):
    cfg={key:info['Config'].get(key) for key in CONFIG_KEYS}
    return dict(image_id=info['Id'],repo_tags=info.get('RepoTags',[]),
        repo_digests=info.get('RepoDigests',[]),os=info['Os'],architecture=info['Architecture'],
        created=info['Created'],size_bytes=info['Size'],rootfs=info['RootFS'],
        effective_config_sha256=hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest(),
        config_environment_keys=sorted(value.split('=',1)[0] for value in cfg.get('Env') or []))


def inventory(label, image):
    args=['run','--rm','--pull=never','--network=none','--read-only','--user=1000:1000',
          '--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=128',
          '--cpus=2','--cpuset-cpus=0,2','--memory=2147483648','--memory-swap=2147483648',
          '--mount',f'type=bind,src={ROOT/"experiments"},dst=/app/experiments,readonly',
          '--mount',f'type=bind,src={ROOT/".framework/orqs/ORQ-41-production-retrieval-graduation/campaign-redesign/p2_netguard"},dst=/p2_netguard,readonly',
          '--mount',f'type=bind,src={OUT},dst=/validation',
          '-e','PYTHONPATH=/p2_netguard:/app','-e','APP_SETTINGS_ENV_FILE=',
          '-e','PYTHONDONTWRITEBYTECODE=1','-e','PYTHONHASHSEED=41',
          '-e','AWS_CONFIG_FILE=/nonexistent','-e','AWS_SHARED_CREDENTIALS_FILE=/nonexistent',
          '-e','AWS_EC2_METADATA_DISABLED=true','-e','HOME=/nonexistent',
          '-e','P2_NET_AUDIT_LOG=/validation/probe-network.log',
          '--entrypoint','/usr/local/bin/python',image,'-B','/validation/inventory_probe.py']
    write(OUT/(label+'-probe-command.json'),dict(argv=DOCKER+args))
    process=subprocess.run(DOCKER+args,capture_output=True,timeout=90)
    (OUT/(label+'-probe.stdout')).write_bytes(process.stdout)
    (OUT/(label+'-probe.stderr')).write_bytes(process.stderr)
    assert process.returncode==0, label+' image inventory failed; inspect retained logs'
    result=json.loads(process.stdout)
    assert result['status']=='IMAGE_INVENTORY_AND_ADAPTER_IMPORT_PASS'
    assert result['interfaces']==['lo']
    write(OUT/(label+'-inventory.json'),result)
    return result


def main():
    check_p2()
    auth=json.loads((OUT/'authorization.json').read_text())
    assert auth['status']=='OPERATOR_AUTHORIZED_LOCAL_LEXICAL_IMAGE_BUILD_AND_PIN'
    assert auth['parent_image_id']==PARENT and sha(SOURCE)==auth['approved_source_sha256']
    assert sha(PREVIOUS/'completion.json')==auth['source_patch_completion_sha256']
    assert sha(PREVIOUS/'final-patch-review.json')==auth['source_patch_review_sha256']
    accepted=json.loads((PREVIOUS/'completion.json').read_text())
    assert accepted['status']=='LEXICAL_SQL_REMEDIATION_IMPLEMENTED_INDEPENDENT_REVIEW_PASS'
    assert all(sha(PREVIOUS/name)==digest for name,digest in accepted['artifacts_sha256'].items())
    assert all(sha(ROOT/name)==digest for name,digest in accepted['technical_files'].items())
    scope=json.loads((OUT/'scope-before.json').read_text())
    assert all(sha(ROOT/name)==digest for name,digest in scope.items())
    assert shutil.disk_usage(ROOT).free > 5*1024**3
    assert not (OUT/'build-started.json').exists()
    assert subprocess.run(DOCKER+['image','inspect',TAG],capture_output=True).returncode!=0
    parent=inspect(PARENT)
    assert parent['Id']==PARENT and (parent['Os'],parent['Architecture'])==('linux','amd64')
    write(OUT/'parent-image.json',summary(parent))
    before=inventory('parent',PARENT)
    original_sha=json.loads((PREVIOUS/'source-patch-validation.json').read_text())['original_provider_sha256']
    assert before['provider_sha256']==original_sha
    local={str(path.relative_to(ROOT/'app')):sha(path) for path in sorted((ROOT/'app').rglob('*'))
           if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc'}
    assert local.keys()==before['app_files'].keys(), 'Host and parent app source membership differs'
    assert [key for key in local if local[key]!=before['app_files'][key]]==['core/providers/pgvector_store.py']
    context=OUT/'context'
    context.mkdir(mode=0o700)
    (context/'pgvector_store.py').write_bytes(SOURCE.read_bytes())
    (context/'Dockerfile').write_text('FROM '+PARENT+'\nCOPY pgvector_store.py /app/app/core/providers/pgvector_store.py\n')
    for path in context.iterdir():
        path.chmod(0o644)
        os.utime(path,(0,0))
    files={path.name:sha(path) for path in sorted(context.iterdir())}
    assert sorted(files)==['Dockerfile','pgvector_store.py']
    build=DOCKER+['build','--pull=false','--network=none','-t',TAG,str(context)]
    write(OUT/'build-manifest.json',dict(parent_image_id=PARENT,tag=TAG,context_sha256=files,
        controller_sha256=sha(Path(__file__)),inventory_probe_sha256=sha(OUT/'inventory_probe.py'),
        authorization_sha256=sha(OUT/'authorization.json'),source_git_head=auth['source_git_head'],
        source_inventory_sha256=sha(OUT/'scope-before.json'),build_command=build,
        build_environment_override={'DOCKER_BUILDKIT':'0'},downloads=0,aa_g6_campaign_authorized=False))
    write(OUT/'build-started.json',dict(started_at=datetime.now(timezone.utc).isoformat(),
        manifest_sha256=sha(OUT/'build-manifest.json'),attempt=1,no_automatic_resume=True))
    build_env=dict(os.environ,DOCKER_BUILDKIT='0')
    process=subprocess.run(build,capture_output=True,timeout=240,env=build_env)
    (OUT/'build.stdout').write_bytes(process.stdout)
    (OUT/'build.stderr').write_bytes(process.stderr)
    assert process.returncode==0, 'Offline build failed; retained logs, no automatic retry'
    candidate=inspect(TAG)
    assert candidate['Id']!=PARENT
    assert candidate['RootFS']['Layers'][:-1]==parent['RootFS']['Layers']
    assert candidate['RootFS']['Type']==parent['RootFS']['Type']
    assert (candidate['Os'],candidate['Architecture'])==(parent['Os'],parent['Architecture'])
    assert all(candidate['Config'].get(key)==parent['Config'].get(key) for key in CONFIG_KEYS)
    assert inspect(PARENT)['Id']==PARENT
    write(OUT/'candidate-image.json',summary(candidate))
    after=inventory('candidate',candidate['Id'])
    assert before['app_files'].keys()==after['app_files'].keys()
    changed=[key for key in before['app_files'] if before['app_files'][key]!=after['app_files'][key]]
    assert changed==['core/providers/pgvector_store.py']
    assert after['app_files']==local
    assert after['provider_sha256']==auth['approved_source_sha256']
    assert after['compiled_sql_sha256']==json.loads((PREVIOUS/'candidate-2-source-probe.json').read_text())['compiled_sql_sha256']
    assert before['compiled_sql_sha256']==json.loads((PREVIOUS/'original-source-probe.json').read_text())['compiled_sql_sha256']
    assert before['installed_distributions']==after['installed_distributions']
    assert before['python']==after['python']
    assert all(sha(ROOT/name)==digest for name,digest in scope.items())
    assert {path.name:sha(path) for path in context.iterdir()}==files
    for audit in (OUT/'probe-network.log',Path(os.environ['P2_NET_AUDIT_LOG'])):
        assert not audit.exists() or audit.stat().st_size==0
    receipt=dict(status='LEXICAL_SQL_LOCAL_IMAGE_PINNED',created_utc=datetime.now(timezone.utc).isoformat(),
        image_id=candidate['Id'],tag=TAG,parent_image_id=PARENT,repo_digests=candidate.get('RepoDigests',[]),
        digest_kind='Local immutable Docker image ID; no registry push or repository digest claimed',
        changed_app_files=changed,source_sha256=after['provider_sha256'],
        compiled_sql_sha256=after['compiled_sql_sha256'],source_git_head=auth['source_git_head'],
        source_tree='Dirty source fingerprinted; image overlays only the reviewed adapter file',
        source_inventory_sha256=sha(OUT/'scope-before.json'),source_patch_review_sha256=auth['source_patch_review_sha256'],
        app_source_membership_equal=True,candidate_app_equals_host=True,dependencies_changed=False,
        effective_config_unchanged=True,parent_layers_preserved=True,new_layers=1,
        parent_inventory_sha256=sha(OUT/'parent-inventory.json'),candidate_inventory_sha256=sha(OUT/'candidate-inventory.json'),
        build_manifest_sha256=sha(OUT/'build-manifest.json'),protected_source_config_files_unchanged=len(scope),
        validation='Parent-executed local inventory/import/SQL-capture checks; not new independent performance review',
        inherited_functional_tests_passed=239,functional_suite_rerun=False,database_connections=0,
        api_requests=0,provider_calls=0,external_calls=0,downloads=0,spend_usd='0',
        old_run_and_image_pins_unchanged=True,calibration_run_prepared=False,aa_g6_campaign_executed=False,
        official_g6_status='CONTROLLED_G6_FAIL',paid_admission='BLOCKED_CONTROLLED_G6_FAIL')
    write(OUT/'receipt.json',receipt)
    print(json.dumps({key:receipt[key] for key in ('status','tag','image_id','parent_image_id','changed_app_files','spend_usd')},indent=2))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        failure=OUT/'failure.json'
        if not failure.exists():
            write(failure,dict(status='LEXICAL_SQL_LOCAL_IMAGE_PIN_FAILED',error=type(exc).__name__+': '+str(exc)[:500],
                no_automatic_retry=True,aa_g6_campaign_executed=False))
        raise
