import json
from experiments.production_graduation.campaign_runner import measurements as module
from experiments.production_graduation.campaign_runner.measurements import MeasurementRecorder
from experiments.production_graduation.campaign_runner.runner import LocalAPI,Runner
from experiments.production_graduation.campaign_runner.preflight import file_hash
from experiments.production_graduation.campaign_runner.states import State
from test_orq41_campaign_runner import packet,ROOT,CAMPAIGN,Driver
from test_orq41_client_measurements import prepare

def pin_observer(pins):
    pins['client_measurements']={'schema':module.SCHEMA,'required':True,
        'observer_sha256':file_hash(ROOT/'experiments/production_graduation/campaign_runner/measurements.py'),
        'transport_sha256':file_hash(ROOT/'experiments/production_graduation/campaign_runner/runner.py')}

def test_counterexample_wrong_manifest_receipt_can_finish_complete(tmp_path,packet,monkeypatch):
    manifest,pins,entry,rid,correct=prepare(tmp_path,packet,monkeypatch)
    pin_observer(pins)
    wrong='0'*64
    assert wrong!=pins['manifest_sha256']
    recorder=MeasurementRecorder(tmp_path/'wrong',CAMPAIGN,wrong)
    api=LocalAPI('http://127.0.0.1',pins,measurements=recorder)
    driver=Driver(pins)
    def execute(entry,rid,**kwargs):
        driver.sent.append(rid)
        return api.execute(entry,rid,**kwargs)
    driver.execute=execute
    runner=Runner(ROOT,tmp_path/'budget',CAMPAIGN,manifest,pins,driver,simulation=True,sleep=lambda _:None)
    assert runner.run()==State.COMPLETE
    receipt=json.loads((tmp_path/'wrong'/f'{rid}.json').read_text())
    assert receipt['manifest_sha256']==wrong and receipt['success'] is True

def test_counterexample_required_measurements_can_be_omitted(tmp_path,packet,monkeypatch):
    manifest,pins,entry,rid,_=prepare(tmp_path,packet,monkeypatch)
    pin_observer(pins)
    api=LocalAPI('http://127.0.0.1',pins)
    driver=Driver(pins)
    def execute(entry,rid,**kwargs):
        driver.sent.append(rid)
        return api.execute(entry,rid,**kwargs)
    driver.execute=execute
    runner=Runner(ROOT,tmp_path/'budget',CAMPAIGN,manifest,pins,driver,simulation=True,sleep=lambda _:None)
    assert runner.run()==State.COMPLETE
    assert not list((tmp_path/'timing').glob('*.json'))
