"""Fake-only crash changes cleanup failure to PASS; no host operations."""
from pathlib import Path
import importlib.util,tempfile
spec=importlib.util.spec_from_file_location('t',Path('tests/experiments/test_orq41_dedicated_lifecycle.py'))
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
class Crash(BaseException):pass
for crash in (False,True):
 with tempfile.TemporaryDirectory() as tmp:
  s,c,b,k=t.setup.__wrapped__(Path(tmp),t.manifest.__wrapped__())
  t.complete(c);t.complete(c,'s1');s.stop('complete');b.running[t.API]=False
  original=b.graceful_stop
  def stop(cid):
   if cid==t.PG:
    b.running[cid]=False
    raise TimeoutError('signal delivered, reply lost')
   if cid==t.REDIS and crash:
    b.running[cid]=False
    raise Crash()
   original(cid)
  b.graceful_stop=stop
  try:result=s.recover(sleep=k.advance)
  except Crash:
   b.graceful_stop=original;result=s.recover(sleep=k.advance)
  print('crash='+str(crash),result)
  assert result==('LIFECYCLE_PASS' if crash else 'FAILED')
