import http.client,io,json,uuid
import pytest
from experiments.production_graduation.campaign_runner import measurements as module
from experiments.production_graduation.campaign_runner.measurements import MeasurementRecorder
from experiments.production_graduation.campaign_runner.runner import LocalAPI,Runner
from experiments.production_graduation.campaign_runner.preflight import file_hash
from experiments.production_graduation.campaign_runner.states import State
from test_orq41_campaign_runner import packet,ROOT,CAMPAIGN,Driver
from test_orq41_client_measurements import prepare

def pinned(pins):
    pins['client_measurements']={'schema':module.SCHEMA,'required':True,
        'observer_sha256':file_hash(ROOT/'experiments/production_graduation/campaign_runner/measurements.py'),
        'transport_sha256':file_hash(ROOT/'experiments/production_graduation/campaign_runner/runner.py')}

@pytest.mark.parametrize('mode',['missing','manifest','campaign'])
def test_required_observer_identity_refused_before_admission(tmp_path,packet,mode):
    manifest,pins=packet;pinned(pins);driver=Driver(pins)
    if mode!='missing':
        driver.measurements=MeasurementRecorder(tmp_path/'measure',str(uuid.uuid4()) if mode=='campaign' else CAMPAIGN,'0'*64 if mode=='manifest' else pins['manifest_sha256'])
    runner=Runner(ROOT,tmp_path/'budget',CAMPAIGN,manifest,pins,driver,simulation=True,sleep=lambda _:None)
    assert runner.run()==State.FAILED and not driver.sent and runner.ledger.total==0
    assert not runner.ledger.pending

@pytest.mark.parametrize('missing',[True,False])
def test_local_transport_binding_cannot_be_bypassed(tmp_path,packet,missing):
    manifest,pins=packet;pinned(pins)
    recorder=None if missing else MeasurementRecorder(tmp_path/'measure',CAMPAIGN,'0'*64)
    with pytest.raises(ValueError):LocalAPI('http://127.0.0.1',pins,measurements=recorder)

def test_fragmented_arrival_first_event_first_content_done_and_body_eof_distinct(tmp_path,packet,monkeypatch):
    manifest,pins,entry,rid,recorder=prepare(tmp_path,packet,monkeypatch,stream=True)
    frames=[b'event: ping\ndata: ping\n\n',b'event: token\ndata: \n\n',b'event: token\ndata: payload\n\n',b'event: done\ndata: '+json.dumps({'status':'success','request_id':rid}).encode()+b'\n\n',b'\n\n']
    body=b''.join(frames);headers=b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n';clock=[0]
    boundaries=[];position=len(headers)
    for index,frame in enumerate(frames):position+=len(frame);boundaries.append((position,[1,2,3,4,9][index]))
    class Wire(io.BytesIO):
        def readinto(self,buffer):
            for end,nanoseconds in [(len(headers),500_000_000)]+[(end,seconds*1_000_000_000) for end,seconds in boundaries]:
                if self.tell()<end:
                    clock[0]=nanoseconds
                    return super().readinto(memoryview(buffer)[:min(len(buffer),end-self.tell())])
            return 0
    class Socket:
        def makefile(self,*args,**kwargs):return Wire(headers+body)
        def sendall(self,*args):pass
        def settimeout(self,*args):pass
        def close(self):pass
    base=http.client.HTTPConnection
    class Connection(base):
        def connect(self):self.sock=Socket()
    monkeypatch.setattr(http.client,'HTTPConnection',Connection)
    monkeypatch.setattr(module.time,'monotonic_ns',lambda:clock[0])
    assert LocalAPI('http://127.0.0.1',pins,measurements=recorder).execute(entry,rid,deadline=300).success
    row=json.loads((tmp_path/'timing'/f'{rid}.json').read_text())
    assert [row[k] for k in ('headers_ms','first_event_ms','ttft_ms','done_ms','full_response_ms')]==[500,1000,3000,4000,9000]
