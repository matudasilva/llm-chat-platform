import string
import pytest
from app.http.middleware.tenant import _validate
from experiments.production_graduation.campaign_runner.preflight import campaign_tenant
from experiments.production_graduation.campaign_runner.runner import LocalAPI,request_uuid
from experiments.production_graduation.campaign_runner.ledger import digest

def test_ascii_tenant_alphabet_matches_runtime_without_coercion():
    allowed=set(string.ascii_letters+string.digits+'_-')
    for ordinal in range(128):
        tenant=chr(ordinal)
        if tenant in allowed:
            assert campaign_tenant({'tenant_id':tenant})==_validate(tenant)==tenant
        else:
            with pytest.raises(ValueError):campaign_tenant({'tenant_id':tenant})

@pytest.mark.parametrize('tenant',['A'*64,'a_9-Z','orq37-t23'])
def test_valid_boundary_identity_not_rewritten(tenant):
    assert campaign_tenant({'tenant_id':tenant})==tenant==_validate(tenant)

@pytest.mark.parametrize('tenant',['A'*65,'Ａ','a\x00b','a\r\nb',None,False,' padded '])
def test_invalid_direct_transport_never_calls_request(monkeypatch,tenant):
    calls=[]
    class Connection:
        def __init__(self,*args,**kwargs):pass
        def connect(self):calls.append('connect')
        def request(self,*args,**kwargs):calls.append('request')
        def close(self):calls.append('close')
    monkeypatch.setattr('http.client.HTTPConnection',Connection)
    with pytest.raises(ValueError):
        LocalAPI('http://127.0.0.1',{}).execute({'tenant_id':tenant,'payload':{'message':'local','stream':False}},'00000000-0000-0000-0000-000000000001',deadline=1)
    assert calls==['close']

def test_default_compatibility_and_explicit_tenant_hash_binding():
    campaign='00000000-0000-0000-0000-000000000001'
    first={'seq':0,'payload':{'message':'fixture','stream':False}}
    second={**first,'tenant_id':'tenant-two'}
    assert campaign_tenant(first)=='orq37-t23'
    assert campaign_tenant(second)=='tenant-two'
    assert digest({'entries':[first]})!=digest({'entries':[second]})
    assert request_uuid(campaign,first)!=request_uuid(campaign,second)
