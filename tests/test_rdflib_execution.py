"""Differential checks against native RDFLib, including guarded query shapes."""
import json
from collections import Counter
import pytest
from rdflib import Graph
from sparql_worker import _execute
from rdflib_execution import query_execution, _enabled

DATA = """@prefix e: <urn:> .
e:a e:p e:b, e:c, e:a . e:b e:p e:a; e:q "one"@en .
e:c e:q "two" . e:a e:q "one" ."""

def bag(data):
    return Counter(json.dumps(row, sort_keys=True) for row in data['bindings'])

@pytest.mark.parametrize('query,eligible', [
    ('SELECT ?s ?v WHERE { ?s <urn:p> ?m . ?m <urn:q> ?v }',True),
    ('SELECT DISTINCT ?v WHERE { ?s <urn:p> ?m . ?m <urn:q> ?v }',True),
    ('SELECT ?s ?o WHERE { ?s <urn:p>+ ?o . ?o <urn:q> ?v }',True),
    ('SELECT ?s ?o WHERE { ?s <urn:p>* ?o . ?s <urn:q> ?v }',True),
    ('SELECT ?s WHERE { ?s <urn:p> ?s . ?s <urn:q> ?v }',True),
    ('SELECT ?s ?v WHERE { ?s <urn:p> ?m . ?m <urn:q> ?v } ORDER BY ?s ?v LIMIT 2',False),
    ('SELECT ?s WHERE { ?s <urn:p> ?o } LIMIT 1',False),
    ('SELECT (COUNT(*) AS ?n) WHERE { ?s <urn:p> ?o }',False),
    ('SELECT ?s ?v WHERE { ?s <urn:p> ?o OPTIONAL { ?o <urn:q> ?v } }',False),
    ('SELECT ?s WHERE { { ?s <urn:p> ?o } UNION { ?s <urn:p> ?o } }',False),
    ('SELECT ?s WHERE { ?s <urn:p> ?o FILTER(?s != ?o) }',False),
    ('SELECT ?s ?id WHERE { ?s <urn:p> ?o BIND(STRUUID() AS ?id) }',False),
    ('SELECT ?s WHERE { { SELECT ?s WHERE { ?s <urn:p> ?o } LIMIT 1 } }',False),
    ('ASK { <urn:a> <urn:p> ?o }',False),
])
def test_eligibility_and_native_multiset(monkeypatch,query,eligible):
    g=Graph().parse(data=DATA,format='turtle')
    monkeypatch.setenv('BRICK_RDFLIB_OPTIMIZER','native')
    expected=_execute(g,query,None,True)
    monkeypatch.setenv('BRICK_RDFLIB_OPTIMIZER','connected_bgp')
    with query_execution(g,query):
        assert _enabled.get() is eligible
    assert not _enabled.get()
    actual=_execute(g,query,None,True)
    if 'STRUUID' in query:
        assert actual['total']==expected['total']
    elif actual['ask']:
        assert actual==expected
    else:
        assert actual['vars']==expected['vars'] and bag(actual)==bag(expected)
        if not eligible:
            assert actual['bindings']==expected['bindings']


def test_context_is_restored_on_error(monkeypatch):
    monkeypatch.setenv('BRICK_RDFLIB_OPTIMIZER','connected_bgp')
    g=Graph()
    with pytest.raises(RuntimeError):
        with query_execution(g,'SELECT * WHERE { ?s <urn:p> ?m . ?m <urn:q> ?v }'):
            assert _enabled.get()
            raise RuntimeError('offline')
    assert not _enabled.get()


def test_duplicate_rows_and_rdf_term_types_are_preserved(monkeypatch):
    g=Graph().parse(data='''@prefix e: <urn:> .
      e:a e:p e:b, e:c . e:b e:q "same"@en . e:c e:q "same"@en .
      e:d e:p e:a; e:q <urn:value> . e:e e:p e:a; e:q "urn:value" .
      [] e:p e:a; e:q "3"^^<http://www.w3.org/2001/XMLSchema#integer> .''',format='turtle')
    query='SELECT ?value WHERE { ?s <urn:p> ?m . ?m <urn:q> ?value }'
    monkeypatch.setenv('BRICK_RDFLIB_OPTIMIZER','native')
    expected=_execute(g,query,None,True)
    monkeypatch.setenv('BRICK_RDFLIB_OPTIMIZER','connected_bgp')
    actual=_execute(g,query,None,True)
    assert bag(actual)==bag(expected)
    assert max(bag(actual).values()) >= 2
    query='SELECT ?s ?value WHERE { ?s <urn:p> <urn:a> . ?s <urn:q> ?value }'
    monkeypatch.setenv('BRICK_RDFLIB_OPTIMIZER','native')
    expected=_execute(g,query,None,True)
    monkeypatch.setenv('BRICK_RDFLIB_OPTIMIZER','connected_bgp')
    assert bag(_execute(g,query,None,True))==bag(expected)
