"""Compare adapter inputs with real RDFLib SPARQL JSON binding results."""
import json
import pytest
from rdflib import Graph
from brick_utils import query_graph, SparqlExecutionStatus
from evaluation_metrics import score_rows, METRIC_KEYS, to_bindings
from third_party.buildingqa.metrics import get_entity_and_row_matching_f1, get_exact_match_f1


@pytest.mark.parametrize('pred_select', ['?label ?missing', '?missing ?label', '?label'])
def test_rdflib_bindings_match_official_scoring(pred_select):
    graph = Graph()
    body = '''WHERE { VALUES ?label { "ABC"@en "完成" "ABC"@en } OPTIONAL { <urn:none> <urn:absent> ?missing } }'''
    gold_query = 'SELECT ?label ?missing ' + body
    pred_query = 'SELECT ' + pred_select + ' ' + body
    raw_gold = json.loads(graph.query(gold_query).serialize(format='json'))['results']['bindings']
    raw_pred = json.loads(graph.query(pred_query).serialize(format='json'))['results']['bindings']
    gold, gold_status, error = query_graph(gold_query, graph=graph, isolated=False)
    pred, pred_status, error = query_graph(pred_query, graph=graph, isolated=False)
    assert gold_status is pred_status is SparqlExecutionStatus.SUCCESS
    # Unbound cells are omitted in SPARQL JSON; duplicate rows are retained.
    assert len(to_bindings(gold['rows'])) == len(raw_gold) == 3
    expected = {**get_entity_and_row_matching_f1(raw_gold, raw_pred),
                'exact_match_f1':get_exact_match_f1(raw_gold, raw_pred)}
    scores = score_rows(gold['rows'], pred['rows'])
    assert {key:scores[key] for key in METRIC_KEYS} == expected
