"""Invoke reviewed preparation once; retain source/environment preservation proof."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from experiments.production_graduation.gate_validation import blocked_latency as driver
from experiments.production_graduation.gate_validation.validate_g123 import check_p2

OUT=Path(__file__).resolve().parent


def source_identity():
    source=driver.aa.Database(driver.aa.SOURCE_PG)
    business=driver.readonly(source,'orq41',driver.PROJECTION_SQL)
    return dict(schema_sha256=source.schema_hash('orq41'),
        business_projection_sha256=hashlib.sha256(business.encode()).hexdigest(),
        counts=driver.readonly(source,'orq41','SELECT (SELECT count(*) FROM conversations),'
            '(SELECT count(*) FROM messages),(SELECT count(*) FROM documents),'
            '(SELECT count(*) FROM chunks);').strip())


def main():
    check_p2()
    auth=OUT/'preparation-authorization.json'
    assert not (OUT/'preparation-started.json').exists()
    driver.write_json(OUT/'preparation-started.json',dict(authorization_sha256=driver.sha_file(auth),
        started_at=datetime.now(timezone.utc).isoformat(),attempt=1,no_automatic_resume=True))
    try:
        before=source_identity()
        driver.write_json(OUT/'source-environment-before.json',before)
        run=driver.prepare(auth)
        plan=json.loads((run/'plan.json').read_text())
        fixtures=json.loads((run/'fixtures.json').read_text())
        prep=json.loads((run/'preparation.json').read_text())
        driver.validate_plan(plan,fixtures,prepared=True)
        after=source_identity()
        assert before==after, 'Existing source environment changed'
        driver.write_json(OUT/'source-environment-after.json',after)
        assert plan['images']==dict.fromkeys(driver.ARMS,'sha256:775d925078229f173fc48a4b95d5ca1620cb518b46433ead60cec3440029b852')
        assert all(not (run/name).exists() for name in ('execution-started.json','execution-authorization.json','result.json'))
        services={}
        for key,name in plan['containers'].items():
            info=json.loads(driver.docker('inspect',name))[0]
            assert info['State']['Running'] and not info['HostConfig'].get('PortBindings')
            expected=plan['postgres_image'] if key=='postgres' else plan['auxiliary_images'][key]
            assert info['Image']==expected
            services[key]=dict(name=name,id=info['Id'],image=info['Image'],
                network_mode=info['HostConfig']['NetworkMode'],published_ports=False)
        driver.write_json(run/'environment-binding.json',dict(status='LEXICAL_AA_ISOLATED_ENVIRONMENT_PREPARED',
            services=services,resources=driver.aa.inspect_environment(plan),
            original_source_environment=after,original_source_environment_unchanged=True,
            source_review_sha256=driver.sha_file(OUT/'source-review.json'),
            image_amendment_approval_sha256=driver.IMAGE_APPROVAL_SHA256,
            api_requests=0,provider_calls=0,external_calls=0,spend_usd='0'))
        driver.write_json(OUT/'environment-preparation-result.json',dict(status='BLOCKED_AA_PREPARED_NOT_EXECUTED',
            run_directory=str(run.relative_to(driver.ROOT)),plan_sha256=driver.sha_file(run/'plan.json'),
            fixtures_sha256=driver.sha_file(run/'fixtures.json'),preparation_sha256=driver.sha_file(run/'preparation.json'),
            source_environment_unchanged=True,databases=prep['databases'],api_requests=0,
            provider_calls=0,external_calls=0,spend_usd='0',packet_review_pending=True))
        print('LEXICAL_AA_ENVIRONMENT_PREPARED_NO_EXECUTION',run.relative_to(driver.ROOT))
    except Exception as exc:
        driver.write_json(OUT/'environment-preparation-failure.json',dict(status='PREPARATION_FAILED_NO_RETRY',
            error=type(exc).__name__+': '+str(exc)[:250],api_requests=0,provider_calls=0,external_calls=0))
        raise


if __name__=='__main__':
    main()
