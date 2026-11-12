"""Materialize prospective paired campaign inputs, without DB/network/provider I/O."""
import hashlib,json,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent
from experiments.production_graduation.campaign_runner.ledger import digest
if (HERE/'manifest.json').exists(): raise SystemExit('Refuse replacing existing executable input identities')
namespace=uuid.uuid4()
def identity(name): return str(uuid.uuid5(namespace,name))
doc_en=['Explain how provider abstraction separates adapters from domain services.','Explain how chat exchanges persist atomically.','Explain tenant isolation in retrieval.','Explain how streaming errors and partial output are handled.','Explain why telemetry failures must remain best effort.']
doc_es=['Explicá cómo la abstracción de providers separa adapters y servicios de dominio.','Explicá cómo se persisten atómicamente los intercambios de chat.','Explicá el aislamiento por tenant en retrieval.','Explicá cómo se manejan errores y salida parcial en streaming.','Explicá por qué los fallos de telemetría deben ser best effort.']
entries=[];fixtures=[];cases=[]
for language in ('EN','ES'):
 for category in ('document','history','combined','empty'):
  for n in range(5):
   case_id=f'{language}-{category}-{n+1:02d}'; key=f'ORQ41PROJECT{language}{n+1:02d}'
   fact=(f'{key} has approved recovery contact Team Amber {n+1}.' if language=='EN' else f'{key} tiene como contacto de recuperación aprobado al Equipo Ámbar {n+1}.')
   question=(doc_en if language=='EN' else doc_es)[n]
   if category=='history': question=f'What recovery contact was approved for {key}?' if language=='EN' else f'¿Qué contacto de recuperación se aprobó para {key}?'
   if category=='combined': question += (f' Also recall the recovery contact approved for {key}.' if language=='EN' else f' Recordá además el contacto de recuperación aprobado para {key}.')
   if category=='empty': question=f'What evidence is available for unregistered project ORQ41UNKNOWN{n+1:02d}?' if language=='EN' else f'¿Qué evidencia hay para el proyecto no registrado ORQ41UNKNOWN{n+1:02d}?'
   tenant='orq37-t23' if category in ('document','combined') else f'orq41-{str(namespace)[:8]}-{language.lower()}-{category}'
   history=[]
   if category in ('history','combined'):
    history=[{'role':'user','content':fact},{'role':'assistant','content':'Acknowledged.' if language=='EN' else 'Registrado.'}]
    for turn in range(1,24):
     history += [{'role':'user','content':f'Routine log {turn}: synthetic maintenance record.' if language=='EN' else f'Registro rutinario {turn}: mantenimiento sintético.'},{'role':'assistant','content':'Noted.' if language=='EN' else 'Anotado.'}]
   cases.append(dict(case_id=case_id,language=language,category=category,tenant_id=tenant,message=question,history=history))
for block in ('EN-C1','EN-E1','ES-C1','ES-E1'):
 language=block[:2];selected=[c for c in cases if c['language']==language]
 for index in range(21):
  for stream in (False,True):
   protocol='sse' if stream else 'json';slot=f'{block}/{index}/{protocol}'
   case=selected[index-1] if index else dict(case_id=f'{block}-warmup-{protocol}',category='warmup',tenant_id='orq37-t23',message=(doc_en if language=='EN' else doc_es)[0],history=[])
   cid=identity(slot)
   fixtures.append(dict(slot=slot,conversation_id=cid,tenant_id=case['tenant_id'],messages=case['history']))
   entries.append(dict(seq=len(entries),block=block,language=language,warmup=index==0,tenant_id=case['tenant_id'],case_id=case['case_id'],category=case['category'],payload=dict(message=case['message'],stream=stream,conversation_id=cid)))
manifest={'entries':entries};assert len(entries)==168 and len({x['conversation_id'] for x in fixtures})==168
for name,value in [('manifest.json',manifest),('fixtures.prospective.json',{'namespace':str(namespace),'status':'NOT_SEEDED','conversations':fixtures}),('cases.json',{'cases':cases})]:
 (HERE/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
(HERE/'materialization.json').write_text(json.dumps({'status':'MANIFEST_MATERIALIZED_FIXTURES_NOT_SEEDED','manifest_sha256':digest(manifest),'entries':168,'measured':160,'warmups':8,'case_identities':40,'fresh_conversations':168,'history_turns':24,'out_of_window_fact':'First complete turn; existing history window max_messages20 unchanged','files_sha256':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('manifest.json','fixtures.prospective.json','cases.json')},'provider_calls':0,'db_writes':0,'spend_usd':'0'},indent=2)+'\n')
print('Materialized168 entries,40 paired identities,168 fresh prospective conversations; no DB/network/provider I/O')
