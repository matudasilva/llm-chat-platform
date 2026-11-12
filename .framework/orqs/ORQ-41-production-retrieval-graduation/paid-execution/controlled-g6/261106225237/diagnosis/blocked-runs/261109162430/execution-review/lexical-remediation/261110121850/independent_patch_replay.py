"""Read-only independent replay of retained SQL remediation evidence."""
import ast,hashlib,json
from pathlib import Path
from statistics import median
from collections import Counter,defaultdict
import xml.etree.ElementTree as ET
p=Path(__file__).resolve().parent
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
load=lambda f:json.loads(f.read_text())
manifest=load(p/'local-proof-manifest.json');analysis=load(p/'analysis.json');result=load(p/'local-proof-result.json')
assert sha(p/'run_local_proof.py')==manifest['controller_sha256'];assert sha(p/'candidate-2-regression.xml')==manifest['regression_xml_sha256'];assert sha(Path('tests/core/test_pgvector_query_equivalence.py'))==manifest['test_module_sha256'];assert sha(p/'candidate-2-design-review.json')==manifest['candidate_design_review_sha256'];assert sha(p/'candidate-2-pgvector_store.py')==manifest['candidate_module_sha256']==sha(Path('app/core/providers/pgvector_store.py'))
assert sha(p/'original-pgvector_store.py')==manifest['original_module_sha256'];assert result['manifest_sha256']==sha(p/'local-proof-manifest.json')
old=ast.parse((p/'original-pgvector_store.py').read_text());new=ast.parse((p/'candidate-2-pgvector_store.py').read_text())
def query(t):return next(n for n in ast.walk(t)if isinstance(n,ast.Constant)and isinstance(n.value,str)and 'WITH semantic AS' in n.value)
a,b=query(old),query(new);oldsql=a.value;newsql=b.value;a.value=b.value='<SQL>';assert ast.dump(old)==ast.dump(new);assert oldsql.count('ORDER BY')==newsql.count('ORDER BY')==5;assert oldsql.count('LIMIT :top_k')==newsql.count('LIMIT :top_k')==3
ref=next(n.value.value for n in ast.parse(Path('tests/core/test_pgvector_query_equivalence.py').read_text()).body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='_REFERENCE_SQL'for t in n.targets));assert ref==oldsql
suites=ET.parse(p/'candidate-2-regression.xml').getroot().findall('testsuite');assert sum(int(s.attrib['tests'])for s in suites)==239 and all(int(s.attrib[k])==0 for s in suites for k in('failures','errors','skipped'))
def nodes(n):
 yield n
 for c in n.get('Plans',[]):yield from nodes(c)
values=defaultdict(list);rawhash={};producer_count=0
assert len(manifest['plans'])==40
for slot in manifest['plans']:
 key=slot['key'];raw=load(p/'plans'/(key+'-result.json'));assert raw['slot']==slot and raw['status']=='PASS';assert sha(p/'plans'/(key+'.sql'))==manifest['plan_sql_sha256'][key+'.sql'];rawhash['plans/'+key+'-result.json']=sha(p/'plans'/(key+'-result.json'))
 md=raw['metadata'];assert md['current_user']==md['session_user']=='rag_app'and md['read_only']==md['row_security']=='on'and md['tenant']==slot['tenant_id']and not md['superuser']and not md['bypass_rls'];assert raw['prepared_after']['parameter_types']=='{vector,bigint,text,bigint}';assert raw['prepared_after']['generic_plans']==(slot['mode']=='force_generic_plan');assert raw['prepared_after']['custom_plans']==(slot['mode']=='force_custom_plan')
 ex=raw['explain'];values[f"{slot['label']}/{slot['mode']}/{slot['category']}"].append(ex['Execution Time'])
 if slot['label']=='candidate-2':
  ns=list(nodes(ex['Plan']));lex=[n for n in ns if n.get('Subplan Name')=='CTE lexical_query'];sem=[n for n in ns if n.get('Subplan Name')=='CTE semantic'];assert len(lex)==len(sem)==1;assert lex[0]['Actual Rows']==lex[0]['Actual Loops']==1;assert sem[0]['Actual Rows']==20 and sem[0]['Actual Loops']==1;deps=[n for n in nodes(lex[0])if n.get('Node Type')=='CTE Scan'and n.get('CTE Name')=='semantic'];assert len(deps)==1 and deps[0]['Actual Rows']==20 and deps[0]['Actual Loops']==1
  def outside(n,inside=False):
   inside=inside or n.get('Subplan Name')=='CTE lexical_query'
   if not inside:assert 'plainto_tsquery'not in json.dumps({k:v for k,v in n.items()if k!='Plans'})
   for c in n.get('Plans',[]):outside(c,inside)
  outside(ex['Plan']);producer_count+=1
for key,v in values.items():assert analysis['explain_ms'][key]==dict(n=5,min_ms=min(v),median_ms=median(v),max_ms=max(v))
rows={};driverstats={}
for label in('original','candidate-2'):
 directory=p/('driver-'+label);dm=load(directory/'manifest.json');assert sha(directory/'manifest.json')==manifest['driver_manifests_sha256'][label];worker=load(directory/'worker.json');assert worker['status']=='DRIVER_DIAGNOSTIC_COMPLETE'and worker['successful_adapter_calls']==worker['adapter_invocations_begun']==30;assert len(worker['rows'])==30
 rr=[];counts=Counter();dv=defaultdict(list)
 for i,slot in enumerate(dm['slots']):
  files=list(directory.glob(f'{i:02d}-*-result.json'));assert len(files)==1;raw=load(files[0]);assert raw==worker['rows'][i];rawhash[str(files[0].relative_to(p))]=sha(files[0]);assert raw['index']==i and raw['status']=='PASS'and raw['error']is None and raw['adapter_call_begun']and raw['output_rows']==slot['expected_rows']
  for k in('slot_id','phase','case_id','category','tenant_id','query_text'):assert raw[k]==slot[k]
  assert raw['before']['plan_cache_mode']==raw['after']['plan_cache_mode']=='auto';assert raw['before']['current_user']==raw['after']['current_user']=='rag_app';counts[raw['chosen_mode']]+=1
  cached=raw['after']['hybrid_cached'];assert len(cached)==1 and cached[0]['parameter_types']=='{vector,bigint,text,bigint}';assert cached[0]['custom_plans']==min(i+1,5)and cached[0]['generic_plans']==max(0,i-4)
  assert raw['chosen_mode']==('custom'if i<5 else'generic');rr.append(raw)
  if raw['phase']=='diagnostic':dv[raw['category']].append(raw['adapter_wall_ns']/1e6)
 assert counts==dict(custom=5,generic=25);rows[label]=rr
 for cat,v in dv.items():assert analysis['driver'][label]['diagnostic_ms_by_category'][cat]==dict(n=5,min_ms=min(v),median_ms=median(v),max_ms=max(v))
for a,b in zip(rows['original'],rows['candidate-2']):assert a['slot_id']==b['slot_id']and a['output_projection']==b['output_projection']and a['result_sha256']==b['result_sha256']
assert producer_count==20;scope=load(p/'scope-before.json');changed=[f for f,h in scope.items()if sha(Path(f))!=h];assert changed==['app/core/providers/pgvector_store.py'];assert len(scope)==500
out=dict(status='LEXICAL_SQL_REMEDIATION_RETAINED_EVIDENCE_INDEPENDENT_REPLAY_PASS',candidate_sha256=manifest['candidate_module_sha256'],test_sha256=manifest['test_module_sha256'],non_sql_ast_unchanged=True,frozen_reference_exact=True,plans=40,candidate_plans_with_dependency_and_single_producers=20,adapter_calls=60,ordered_all_driver_outputs_equal=True,auto_counts_each=dict(custom=5,generic=25),xml_passed=239,protected_unchanged=499,changed=changed,raw_result_sha256=rawhash,analysis_sha256=sha(p/'analysis.json'),manifest_sha256=sha(p/'local-proof-manifest.json'),verifier_sha256=sha(Path(__file__)))
(p/'independent-patch-replay.json').write_text(json.dumps(out,indent=2)+'\n');print(out['status'])
