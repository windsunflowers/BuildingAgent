"""Discriminating checks for the pinned author protocol, without model calls."""
from rdflib import Graph
from brick_agent import BrickSparqlQuery
import brick_utils
from test_language_and_metrics import tiny_agent


def test_brick_executor_keeps_typed_terms_and_unbound_variables(tiny_agent):
    q = BrickSparqlQuery('SELECT ?uri ?literal ?missing WHERE { VALUES (?uri ?literal) { (<urn:item> "item"@en) } OPTIONAL { <urn:absent> <urn:p> ?missing } }')
    q.execute(isolated=False)
    assert q.execution_status is brick_utils.SparqlExecutionStatus.SUCCESS
    assert q.bindings == [{'uri': {'type': 'uri', 'value': 'urn:item'},
                           'literal': {'type': 'literal', 'value': 'item', 'xml:lang': 'en'}}]
    assert q.execution_variables == ['uri', 'literal', 'missing']


def test_brick_executor_does_not_rewrite_a_declared_namespace(tiny_agent):
    q = BrickSparqlQuery('PREFIX brick: <urn:wrong:> SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }')
    q.execute(isolated=False)
    assert q.execution_status is brick_utils.SparqlExecutionStatus.EMPTY_RESULT


def test_initialization_does_not_add_ontology(monkeypatch):
    brick_utils.BrickGraph.reset_singleton()
    def forbidden(graph):
        raise AssertionError('Extra ontology would change the author execution graph')
    monkeypatch.setattr(brick_utils, '_merge_brick_ontology', forbidden)
    graph = Graph().parse(data='<urn:s> <urn:p> <urn:o> .', format='turtle')
    try:
        bg = brick_utils.BrickGraph()
        bg.initialize(graph=graph)
        assert set(bg.get_graph()) == set(bg.source_graph) == set(graph)
        assert len(bg.get_graph()) == 1
    finally:
        brick_utils.BrickGraph.reset_singleton()
