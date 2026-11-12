"""One-file offline overlay on the reviewed immutable C1 parent."""
import hashlib,json,os,subprocess,tempfile,shutil
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path.cwd();ORQ=ROOT/'.framework/orqs/ORQ-41-production-retrieval-graduation'
OUT=ORQ/'paid-execution/controlled-g6/261106130053-rev2/diagnosis/receipt-copy-proposal/implementation/image-pin';OUT.mkdir(exist_ok=False)
parent='sha256:7417a2af20101903f3fc9326af26da074eec6dd3b90987b5b5f74c1986a58d06'
review=ORQ/'paid-execution/controlled-g6/261106130053-rev2/diagnosis/receipt-copy-proposal/implementation/independent-review/receipt.json'
manifest=json.loads((OUT.parent/'manifest.json').read_text());source=ROOT/'app/core/observability/context_evidence.py'
sha=lambda b:hashlib.sha256(b).hexdigest()
assert sha(source.read_bytes())==manifest['source_sha256']
assert json.loads(review.read_text())['status']=='C1_RECEIPT_COPY_IMPLEMENTATION_INDEPENDENT_REVIEW_PASS'
def docker(*args):
 p=subprocess.run(['docker','--host','unix:///var/run/docker.sock',*args],capture_output=True,timeout=240)
 if p.returncode: raise RuntimeError(p.stderr.decode()[:1000])
 return p.stdout
assert json.loads(docker('image','inspect',parent))[0]['Id']==parent
stamp=datetime.now(timezone.utc).strftime('%y%m%d%H%M%S');tag='orq41-local:c1-receiptcopy-'+stamp
context=Path(tempfile.mkdtemp(prefix='orq41-copy-image-'));shutil.copyfile(source,context/'context_evidence.py')
(context/'Dockerfile').write_text('FROM '+parent+'\nCOPY context_evidence.py /app/app/core/observability/context_evidence.py\n')
cmd=['docker','--host','unix:///var/run/docker.sock','build','--pull=false','--network=none','-t',tag,str(context)]
env=dict(os.environ,DOCKER_BUILDKIT='0')
p=subprocess.run(cmd,capture_output=True,timeout=240,env=env);(OUT/'build.log').write_bytes(p.stdout+p.stderr)
assert p.returncode==0,'Offline build failed; retain log'
image=json.loads(docker('image','inspect',tag))[0]['Id']
code="import pathlib,hashlib,json; p=pathlib.Path('/app/app'); print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in str(f) and f.suffix!='.pyc'},sort_keys=True))"
original=json.loads(docker('run','--rm','--pull=never','--network','none','--entrypoint','/usr/local/bin/python',parent,'-c',code))
updated=json.loads(docker('run','--rm','--pull=never','--network','none','--entrypoint','/usr/local/bin/python',image,'-c',code))
assert original.keys()==updated.keys()
changed=[k for k in original if original[k]!=updated[k]];assert changed==['core/observability/context_evidence.py'],changed
assert updated[changed[0]]==sha(source.read_bytes())
(OUT/'parent-app-inventory.json').write_text(json.dumps(original,indent=2)+'\n');(OUT/'candidate-app-inventory.json').write_text(json.dumps(updated,indent=2)+'\n')
receipt={'status':'OPTIMIZED_C1_LOCAL_IMAGE_PINNED','image_id':image,'tag':tag,'parent_image_id':parent,'changed_app_files':changed,'source_sha256':sha(source.read_bytes()),'source_git_head':subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(),'source_tree':'reviewed dirty tree; image overlays only the one approved file','review_receipt_sha256':sha(review.read_bytes()),'source_inventory_sha256':sha((OUT/'candidate-app-inventory.json').read_bytes()),'created_utc':datetime.now(timezone.utc).isoformat(),'build_network':'none','pull':False,'dependencies_changed':False,'provider_calls':0,'paid_spend_usd':'0'}
(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');(OUT/'pin.py').write_text(Path(__file__).read_text());print(json.dumps(receipt,indent=2))
