"""Read-only immutable-image source/dependency comparison; no app imports."""
import difflib,hashlib,json,subprocess
from pathlib import Path
OUT=Path(__file__).resolve().parent
images={'c0':'sha256:3feaa36e5787976cf2447344be39b6e9976e5f3db2248c6beef652dbfb45dcc3','c1':'sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707'}
code="import pathlib,json,sys,importlib.metadata as m; p=pathlib.Path('/app/app'); print(json.dumps({'python':sys.version,'packages':sorted((d.metadata['Name'],d.version) for d in m.distributions()),'files':{str(f.relative_to(p)):f.read_text() for f in sorted(p.rglob('*.py'))}},sort_keys=True))"
data={}
for arm,image in images.items():
 cmd=['docker','--host','unix:///var/run/docker.sock','run','--rm','--pull=never','--network','none','--entrypoint','/usr/local/bin/python',image,'-c',code]
 r=subprocess.run(cmd,capture_output=True,timeout=120);assert r.returncode==0,r.stderr.decode()
 data[arm]=json.loads(r.stdout);(OUT/(arm+'-source.json')).write_bytes(r.stdout)
a,b=data['c0']['files'],data['c1']['files'];changed=[name for name in sorted(set(a)|set(b)) if a.get(name)!=b.get(name)]
patch=''.join(''.join(difflib.unified_diff(a.get(name,'').splitlines(True),b.get(name,'').splitlines(True),fromfile='c0/'+name,tofile='c1/'+name)) for name in changed)
(OUT/'images.diff').write_text(patch)
result={'images':images,'python_equal':data['c0']['python']==data['c1']['python'],'packages_equal':data['c0']['packages']==data['c1']['packages'],'changed_files':changed,'source_receipts':{arm:hashlib.sha256((OUT/(arm+'-source.json')).read_bytes()).hexdigest() for arm in images},'api_requests':0,'database_queries':0,'provider_calls':0,'external_calls':0,'spend_usd':'0'}
(OUT/'comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
