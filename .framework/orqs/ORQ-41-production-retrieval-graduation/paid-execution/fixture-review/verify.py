import asyncio,hashlib,json,uuid
from collections import Counter,defaultdict
from pathlib import Path
from experiments.production_graduation.campaign_runner.ledger import digest
from experiments.production_graduation.campaign_runner.preflight import campaign_tenant
from app.core.domain.conversation_history import ConversationHistoryAssembler,HistoryMessage
from app.core.domain.conversation_turns import build_materialized_window
HERE=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution')
manifest=json.loads((HERE/'manifest.json').read_text());entries=manifest['entries'];case_rows=json.loads((HERE/'cases.json').read_text())['cases'];cases={row['case_id']:row for row in case_rows}
fixture=json.loads((HERE/'fixtures.prospective.json').read_text());fixtures=fixture['conversations'];by_cid={row['conversation_id']:row for row in fixtures};mat=json.loads((HERE/'materialization.json').read_text())
assert len(entries)==len(fixtures)==len(by_cid)==168 and len(cases)==len(case_rows)==40
assert mat['manifest_sha256']==digest(manifest)
assert all(hashlib.sha256((HERE/name).read_bytes()).hexdigest()==h for name,h in mat['files_sha256'].items())
assert fixture['status']=='NOT_SEEDED'
assert [row['seq'] for row in entries]==list(range(168))
assert list(dict.fromkeys(row['block'] for row in entries))==['EN-C1','EN-E1','ES-C1','ES-E1']
assert sum(row['warmup'] for row in entries)==8
paired=defaultdict(list);warmups=[]
for row in entries:
 c=by_cid[row['payload']['conversation_id']];assert row['tenant_id']==c['tenant_id']==campaign_tenant(row)
 assert str(uuid.uuid5(uuid.UUID(fixture['namespace']),c['slot']))==c['conversation_id']
 block,index,protocol=c['slot'].split('/');assert block==row['block'] and (protocol=='sse') is row['payload']['stream']
 assert row['language']==row['block'][:2] and len(row['payload']['message'])<8000
 if row['warmup']:
  assert index=='0' and row['category']=='warmup' and not c['messages'];warmups.append(row['case_id']);continue
 case=cases[row['case_id']];assert row['payload']['message']==case['message'] and row['category']==case['category'] and c['messages']==case['history']
 assert case['language']==row['language'] and case['tenant_id']==row['tenant_id']
 paired[row['case_id']].append((row['block'][-2:],row['payload']['stream']))
assert len(set(warmups))==8 and not set(warmups)&set(cases)
for cid,values in paired.items():assert sorted(values)==[('C1',False),('C1',True),('E1',False),('E1',True)]
for block in ('EN-C1','EN-E1','ES-C1','ES-E1'):
 rows=[e for e in entries if e['block']==block];assert len(rows)==42
 assert all(a['payload']['stream']!=b['payload']['stream'] for a,b in zip(rows,rows[1:]))
 assert Counter(e['category'] for e in rows)=={'document':10,'history':10,'combined':10,'empty':10,'warmup':2}
for lang in ('EN','ES'):assert Counter(c['category'] for c in cases.values() if c['language']==lang)=={'document':5,'history':5,'combined':5,'empty':5}
checked=0
for case in cases.values():
 if case['category'] in ('document','combined'):assert case['tenant_id']=='orq37-t23'
 else:assert case['tenant_id']!='orq37-t23'
 if case['category'] not in ('history','combined'):
  assert not case['history'];continue
 history=case['history'];assert len(history)==48 and [x['role'] for x in history]==['user','assistant']*24
 first_fact=history[0]['content'];assert sum(first_fact in m['content'] for m in history)==1
 messages=tuple(HistoryMessage(sequence=i+1,role=m['role'],content=m['content']) for i,m in enumerate(history))
 class Port:
  async def fetch_ordered(self,*args):return messages
 assembled=asyncio.run(ConversationHistoryAssembler(max_messages=20,max_chars=12000).assemble(Port(),uuid.uuid4(),case['tenant_id']))
 partition=build_materialized_window(all_messages=messages,bounded_messages=assembled.messages)
 assert len(partition.window)==20 and first_fact not in [m.content for m in partition.window]
 assert partition.excluded_units[0].messages[0].content==first_fact
 checked+=1
assert checked==20
out={'status':'PROSPECTIVE_FIXTURE_MATERIALIZATION_INDEPENDENT_REVIEW_PASS','reviewer':'/root/g9_final_distinct_reviewer','entries':168,'measured':160,'warmups':8,'paired_case_identities':40,'unique_prospective_conversations':168,'out_of_window_history_case_identities_checked':20,'history_conversations':80,'prospective_history_messages':3840,'fixture_state':'NOT_SEEDED','pins_or_live_config_verified':False,'db_calls':0,'api_calls':0,'external_calls':0,'spend_usd':'0','manifest_sha256':digest(manifest),'source_and_artifacts_sha256':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('prepare_manifest.py','manifest.json','cases.json','fixtures.prospective.json','materialization.json')},'findings':[],'limitations':['Prospective unique identities, not independently proven absent from live database','Tenant document absence and P3 document answerability require read-only DB checks after seeding','No live configuration/source/network/provider pins accepted by this review']}
(HERE/'fixture-review/receipt.json').write_text(json.dumps(out,indent=2)+'\n');print(out['status'], '168 entries;40 paired cases;20 actual window checks')
