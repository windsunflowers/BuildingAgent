import json, sys, hashlib
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from rdflib import Graph
from brick_utils import query_graph
from sparql_worker import isolated_query_session
from evaluation_metrics import score_rows, METRIC_KEYS

def bag(rows):
 return Counter(tuple(sorted((k,json.dumps(v,sort_keys=True)) for k,v in r.items())) for r in rows)

def main():
 output=[]
 for rid,ttl in [('e885a265ee6254bf28e8fc765f4954024','dflexlibs_multizone'),('e3687039e90ae48cbb273e0abcaab5b15','TUC_building')]:
  path=ROOT/'output/evaluations'/rid/'report.json';report=json.loads(path.read_bytes());g=Graph().parse(ROOT/'data/buildings'/f'{ttl}.ttl',format='turtle'); rows=[];cache={}
  with isolated_query_session():
   def run(q):
    if q not in cache:
     data,status,error=query_graph(q,graph=g,timeout=15,prepare_prefixes=False,include_bindings=True)
     cache[q]=(data.get('bindings',[]) if data else [],status.value,error)
    return cache[q]
   for r in report['results']:
    gold,gs,ge=run(r.get('gold_execution_sparql') or r['gold_sparql']);pred,ps,pe=run(r['pred_sparql'])
    scores=score_rows(gold,pred) if gs in ('success','empty_result') and ps in ('success','empty_result') else {k:0 for k in METRIC_KEYS}
    rows.append({'index':r['question_index'],'gold_count':len(gold),'pred_count':len(pred),'status':ps,'error':pe,'gold_status':gs,'gold_error':ge,'same_gold_bindings':bag(gold)==bag(r['gold_bindings']),'same_pred_bindings':bag(pred)==bag(r.get('pred_bindings',[])),'saved_graphdb_scores':{k:r[k] for k in METRIC_KEYS},'local_replay_scores':{k:scores[k] for k in METRIC_KEYS}})
    if len(rows)%10==0: print(rid,len(rows),flush=True)
  summary={'report_id':rid,'report_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'same_gold':sum(r['same_gold_bindings'] for r in rows),'same_pred':sum(r['same_pred_bindings'] for r in rows),'local_mean':{k:sum(r['local_replay_scores'][k] for r in rows)/len(rows) for k in METRIC_KEYS},'rows':rows}
  output.append(summary); print(json.dumps({k:v for k,v in summary.items() if k!='rows'}),flush=True)
 (ROOT/'output/validation/graphdb_saved_queries_rdflib_replay_20261025.json').write_text(json.dumps({'kind':'saved_remote_vs_current_local_same_query_replay_not_model_rerun','runs':output},indent=2),encoding='utf-8')
if __name__=='__main__': main()
