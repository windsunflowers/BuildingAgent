from pathlib import Path
import sys,json,time,hashlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from rdflib import Graph
from brick_utils import query_graph
from sparql_worker import isolated_query_session
from react_graphdb import execute_json,ENDPOINTS

def main():
 report=json.loads((ROOT/'output/evaluations/e69c5d55371da4354b7c3f5f74f2ba16f/report.json').read_bytes())
 q=next(r['gold_execution_sparql'] for r in report['results'] if r['status']=='gold_error')
 g=Graph().parse(ROOT/'data/buildings/bldg11.ttl',format='turtle');out={'query_sha256':hashlib.sha256(q.encode()).hexdigest(),'source_triples':len(g),'model_calls':0}
 t=time.monotonic()
 with isolated_query_session():
  data,status,error=query_graph(q,graph=g,timeout=180,prepare_prefixes=False,include_bindings=True)
 out['rdflib_serial']={'elapsed_seconds':time.monotonic()-t,'status':status.value,'error':error,'rows':len(data['rows']) if data else None};print(json.dumps(out['rdflib_serial']),flush=True)
 (ROOT/'output/validation/mortar009_rdflib_serial180_20261026.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
