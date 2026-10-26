from pathlib import Path
import sys,time,json
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from rdflib import Graph
from rdflib.paths import Path as RDFPath
from collections import OrderedDict,Counter
from brick_utils import query_graph
from sparql_worker import isolated_query_session
from react_graphdb import execute_json,ENDPOINTS
class CachedPathGraph(Graph):
 def __init__(self,*a,**kw):
  super().__init__(*a,**kw);self.path_cache=OrderedDict()
 def triples(self, triple):
  if not isinstance(triple[1],RDFPath):
   yield from super().triples(triple);return
  if triple not in self.path_cache:
   value=tuple(super().triples(triple))
   if len(value)<=100000:
    self.path_cache[triple]=value
    if len(self.path_cache)>256:self.path_cache.popitem(last=False)
   yield from value;return
  self.path_cache.move_to_end(triple);yield from self.path_cache[triple]
def main():
 d=json.loads((ROOT/'output/evaluations/e69c5d55371da4354b7c3f5f74f2ba16f/report.json').read_bytes());q=next(r['gold_execution_sparql'] for r in d['results'] if r['status']=='gold_error');g=CachedPathGraph().parse(ROOT/'data/buildings/bldg11.ttl',format='turtle')
 t=time.monotonic()
 with isolated_query_session(): data,status,error=query_graph(q,graph=g,timeout=20,prepare_prefixes=False,include_bindings=True)
 out={'kind':'experimental_path_cache_not_production','seconds':time.monotonic()-t,'status':status.value,'error':error,'rows':len(data['rows']) if data else None}
 if data:
  _,remote=execute_json(ENDPOINTS['bldg11'],q,15)
  bag=lambda rows:Counter(tuple(sorted((k,json.dumps(v,sort_keys=True)) for k,v in r.items())) for r in rows)
  out['same_as_remote']=bag(data['bindings'])==bag(remote)
 print(json.dumps(out),flush=True);(ROOT/'output/validation/mortar009_path_cache_probe_20261026.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
if __name__=='__main__':main()
