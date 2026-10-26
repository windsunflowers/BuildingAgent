import sys,json,random
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(Path(__file__).resolve().parent)]
from rdflib import Graph,URIRef,Literal
from rdflib.plugins.sparql import CUSTOM_EVALS
from sparql_worker import _execute
from probe_mortar009_connected_bgp_20261026 import custom
NAME='diagnostic_connected_bgp'
def bag(data):
 return Counter(json.dumps(row,sort_keys=True,ensure_ascii=False) for row in data['bindings'])
def main():
 rng=random.Random(260626);checks=[]
 queries=[
 'SELECT ?s ?o WHERE { ?s <urn:p> ?m . ?m <urn:q> ?o }',
 'SELECT ?s ?o WHERE { ?s <urn:p> ?o . OPTIONAL { ?o <urn:q> ?x } }',
 'SELECT ?s ?o WHERE { { ?s <urn:p> ?o } UNION { ?s <urn:p> ?o } }',
 'SELECT ?s ?o WHERE { ?s <urn:p> ?m . ?m <urn:q> ?o . FILTER(?s != ?o) }',
 'SELECT ?s ?o WHERE { ?s <urn:p>+ ?o . ?o <urn:q> ?x }',
 'SELECT ?s ?o WHERE { ?s <urn:p>* ?o . ?s <urn:q> ?x }',
 'SELECT ?s WHERE { ?s <urn:p> ?s . ?s <urn:q> ?x }',
 'SELECT ?s ?value WHERE { ?s <urn:q> ?value . ?s <urn:p> ?o }',
 ]
 for case in range(12):
  g=Graph();nodes=[URIRef('urn:n'+str(i)) for i in range(8)]
  for _ in range(22): g.add((rng.choice(nodes),URIRef('urn:p'),rng.choice(nodes)))
  for n in nodes:
   g.add((n,URIRef('urn:q'),Literal(rng.choice(['a','b','c']),lang='en')))
  for query in queries:
   CUSTOM_EVALS.pop(NAME,None);expected=_execute(g,query,None,True)
   CUSTOM_EVALS[NAME]=custom;actual=_execute(g,query,None,True)
   assert expected['vars']==actual['vars'] and bag(expected)==bag(actual),(case,query)
   checks.append({'case':case,'query':query,'rows':expected['total'],'same_multiset':True})
 CUSTOM_EVALS.pop(NAME,None)
 result={'kind':'experimental_local_differential_test_not_production','passed':len(checks),'random_seed':260626,'checks':checks}
 (ROOT/'output/validation/connected_bgp_differential_20261026.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('passed',len(checks))
if __name__=='__main__':main()
