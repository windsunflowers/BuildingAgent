from pathlib import Path
import sys,time,json
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from rdflib import Graph,RDF,RDFS,Namespace
from rdflib.plugins.sparql import CUSTOM_EVALS
from rdflib.plugins.sparql.evaluate import evalBGP
from brick_utils import query_graph
from sparql_worker import isolated_query_session

def connected_bgp(ctx, triples):
 if not triples:
  yield ctx.solution();return
 chosen=min(range(len(triples)),key=lambda i:sum(ctx[n] is None for n in triples[i]))
 first=triples[chosen];rest=triples[:chosen]+triples[chosen+1:]
 for row in evalBGP(ctx,[first]):
  yield from connected_bgp(ctx.thaw(row),rest)
def custom(ctx,part):
 if part.name!='BGP':raise NotImplementedError
 return connected_bgp(ctx,list(part.triples))
CUSTOM_EVALS['diagnostic_connected_bgp']=custom

def independent(g):
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
   for zone in seen & z: result[(str(point),str(node),str(zone))]+=w*t[point]
 return +result

def main():
 report=json.loads((ROOT/'output/evaluations/e69c5d55371da4354b7c3f5f74f2ba16f/report.json').read_bytes())
 q=next(r['gold_execution_sparql'] for r in report['results'] if r['status']=='gold_error')
 g=Graph().parse(ROOT/'data/buildings/bldg11.ttl',format='turtle');t=time.monotonic()
 with isolated_query_session(): data,status,error=query_graph(q,graph=g,timeout=30,prepare_prefixes=False,include_bindings=True)
 out={'kind':'experimental_rdflib_custom_bgp_not_production','seconds':time.monotonic()-t,'status':status.value,'error':error,'rows':len(data['rows']) if data else None,'graphdb_calls':0}
 if data:
  actual=Counter(tuple(r[k]['value'] for k in ['temp_sensor','vav','zone']) for r in data['bindings'])
  out['same_multiset_as_independent_raw_graph_join']=actual==independent(g)
 print(json.dumps(out),flush=True)
 (ROOT/'output/validation/mortar009_connected_bgp_probe_20261026.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
if __name__=='__main__':main()
