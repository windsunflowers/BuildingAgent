from pathlib import Path
import sys,json,time,hashlib
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from rdflib import Graph,RDF,RDFS,Namespace
from brick_utils import query_graph
from implementation_policy import evaluation_policy
from sparql_worker import isolated_query_session
from rdflib_execution import execution_metadata

def expected_rows(g):
 B=Namespace('https://brickschema.org/schema/Brick#')
 def descendants(root):
  seen={root};todo=[root]
  while todo:
   for x in g.subjects(RDFS.subClassOf,todo.pop()):
    if x not in seen:seen.add(x);todo.append(x)
  return seen
 vc,tc=descendants(B.VAV),descendants(B.Temperature_Sensor)
 v=Counter(s for s,t in g.subject_objects(RDF.type) if t in vc)
 t=Counter(s for s,k in g.subject_objects(RDF.type) if k in tc)
 z=set(g.subjects(RDF.type,B.HVAC_Zone));result=Counter()
 for node,w in v.items():
  seen=set();pending=list(g.objects(node,B.feeds))
  while pending:
   x=pending.pop()
   if x not in seen:seen.add(x);pending.extend(g.objects(x,B.feeds))
  for point in g.objects(node,B.hasPoint):
   for zone in seen & z:result[(str(point),str(node),str(zone))]+=w*t[point]
 return +result

def main():
 source=ROOT/'output/evaluations/e69c5d55371da4354b7c3f5f74f2ba16f/report.json';raw=source.read_bytes();d=json.loads(raw)
 g=Graph().parse(ROOT/'data/buildings/bldg11.ttl',format='turtle');expected=expected_rows(g);results=[]
 budget=evaluation_policy()['sparql_timeout_seconds'];assert budget==180
 with isolated_query_session():
  for row in d['results']:
   if row['status']!='gold_error':continue
   q=row['gold_execution_sparql'];t=time.monotonic()
   data,status,error=query_graph(q,graph=g,timeout=budget,prepare_prefixes=False,include_bindings=True)
   assert status.value=='success',error
   actual=Counter(tuple(r[k]['value'] for k in ['temp_sensor','vav','zone']) for r in data['bindings'])
   assert actual==expected
   result={'original_question_index':row['question_index'],'query_id':row['query_id'],'query_sha256':hashlib.sha256(q.encode()).hexdigest(),'status':status.value,'rows':data['total'],'elapsed_seconds':time.monotonic()-t,'same_multiset_as_independent_raw_graph_join':True}
   results.append(result);print(json.dumps(result),flush=True)
 out={'kind':'nine_original_gold_queries_local_rdflib_no_model_calls','source_report':str(source),'source_sha256':hashlib.sha256(raw).hexdigest(),'execution':execution_metadata(),'sparql_budget_seconds':budget,'source_triples':len(g),'results':results}
 assert len(results)==9 and source.read_bytes()==raw
 (ROOT/'output/validation/nine_gold_rdflib_fixed_20261026.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
 original_items=[json.loads(line) for line in Path(d['configuration']['benchmark']).read_text(encoding='utf-8').splitlines() if line.strip()]
 subset=[{**original_items[r['original_question_index']-1],'original_question_index':r['original_question_index']} for r in results]
 (ROOT/'output/validation/bldg11_mortar009_retry_20261026.jsonl').write_text(''.join(json.dumps(item,ensure_ascii=False)+'\n' for item in subset),encoding='utf-8')
if __name__=='__main__':main()
