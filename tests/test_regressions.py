import json
import threading
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef, RDF, RDFS, Literal

import app
import brick_utils as utils
from brick_agent import BrickAgent, BrickSparqlQuery, AgentState, BrickAction
from brick_decomposer import BrickQueryDecomposer, QueryDecomposition, SensorMention, TemporalConstraint, AggregationRequirement
from brick_temporal_handler import validate_multi_sensor_joins, validate_sensor_coverage
from evaluation_metrics import score_rows
from building_data import complete_turtle_prefix

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def building(monkeypatch):
    monkeypatch.setattr(utils, '_merge_brick_ontology', lambda graph: True)
    utils.BrickGraph.reset_singleton()
    bg = utils.BrickGraph()
    graph = Graph().parse(data='''@prefix bldg: <urn:test:> .
      @prefix brick: <https://brickschema.org/schema/Brick#> .
      @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
      brick:Zone_Air_Temperature_Sensor rdfs:subClassOf brick:Temperature_Sensor .
      brick:Temperature_Sensor rdfs:subClassOf brick:Sensor .
      bldg:room_temp a brick:Zone_Air_Temperature_Sensor .
      bldg:other_temp a brick:Zone_Air_Temperature_Sensor .
      bldg:AHU1 a brick:AHU ; brick:hasPoint bldg:room_temp ; brick:feeds bldg:Zone1 .
      bldg:Zone1 a brick:HVAC_Zone .
    ''', format='turtle')
    bg.initialize(graph=graph)
    a = BrickAgent(use_decomposer=False)
    monkeypatch.setattr(app, 'agent', a)
    monkeypatch.setattr(app, 'graph_meta', {'building': 'test', 'ttl': 'test.ttl', 'warnings': [], 'triples': 7, 'sensors': 2})
    monkeypatch.setattr(app, '_active_tid', None)
    monkeypatch.setattr(app, '_eval_running', False)
    monkeypatch.setattr(app, '_loading', False)
    monkeypatch.setattr(app, 'tasks', {})
    execute = BrickSparqlQuery.execute
    monkeypatch.setattr(BrickSparqlQuery, 'execute', lambda self, isolated=True: execute(self, isolated=False))
    return bg


def test_namespace_and_partial_prefixes(building):
    rows, status = utils.execute_sparql('PREFIX brick: <wrong:> SELECT ?p WHERE { bldg:AHU1 brick:hasPoint ?p }', True)
    assert rows == [{'p': 'urn:test:room_temp'}]
    assert status is utils.SparqlExecutionStatus.SUCCESS


def test_entity_and_property_tools_follow_author_rules(building):
    assert utils.get_brick_entity('room_temp')['uri'] == 'bldg-59#room_temp'
    assert not utils.get_brick_entity('room_temp')['properties']
    assert utils.get_brick_entity('urn:test:room_temp')['uri'] == 'bldg-59#urn:test:room_temp'
    assert utils.get_property_examples('brick:hasPoint') == []
    assert utils.get_property_examples(str(utils.BRICK.hasPoint))
    assert utils.search_brick('room_temp')[0]['uri'] == 'urn:test:room_temp'


def test_cache_cleared_on_graph_switch(building):
    utils.get_brick_entity('room_temp')
    utils.BrickGraph.reset_singleton()
    utils.BrickGraph().initialize(graph=Graph())
    assert not utils.get_brick_entity('room_temp')['properties']


@pytest.mark.parametrize('query,value', [('ASK { bldg:AHU1 brick:hasPoint ?p }', True), ('ASK { bldg:absent brick:hasPoint ?p }', False)])
def test_ask_preserves_false(building, query, value):
    data, status, error = utils.query_graph(query)
    assert data['value'] is value and data['rows'] == [{'ASK': value}]
    assert status is utils.SparqlExecutionStatus.SUCCESS and error is None


def test_read_only_and_unsupported_query_feedback(building):
    for query in ('DELETE WHERE { ?s ?p ?o }', 'SELECT * WHERE { SERVICE <http://example.com> { ?s ?p ?o } }', 'SELECT {'):
        data, status, error = utils.query_graph(query)
        assert data is None and error
    assert utils.query_graph('SELECT ?p WHERE { bldg:AHU1 brick:hasPoint ?p }')[0]['total'] == 1


def test_lazy_result_materialization_is_timed_out(building):
    class SlowResult:
        type = 'SELECT'
        vars = []
        def __iter__(self):
            time.sleep(.2)
            return iter([])
    class SlowGraph:
        def namespaces(self):
            return []
        def query(self, query):
            return SlowResult()
    start = time.monotonic()
    data, status, error = utils.query_graph('SELECT * WHERE {}', graph=SlowGraph(), timeout=.03)
    assert status is utils.SparqlExecutionStatus.TIMED_OUT
    assert time.monotonic() - start < .15


def test_order_by_does_not_lose_rows_or_timezones(building):
    a = app.agent
    fixed = a._validate_and_fix_sparql('SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor } ORDER BY DESC(?s)')
    assert 'LIMIT' not in fixed
    assert len(utils.execute_sparql(fixed)) == 2
    fixed = a._validate_and_fix_sparql('SELECT ?t WHERE { VALUES ?t { "2025-01-01T00:00:00Z"^^xsd:dateTime } }')
    assert '00:00:00Z' in fixed




def test_csv_uses_author_uris_datatypes_and_row_order(building, tmp_path):
    source = tmp_path / 'data.csv'
    source.write_text('Datetime,room_temp,unknown\n04/01/2025 00:00,10,99\n04/01/2025 01:00,20,99\n04/01/2025 02:00,30,99\n', encoding='utf-8')
    building.add_timeseries_data(str(source), max_rows=2)
    assert building.timeseries_meta['selected_row_indices'] == [1,2]
    assert (utils.BLDG.room_temp, utils.REF.hasObservation, utils.BLDG.obs_room_temp_1) in building.get_graph()
    assert (utils.BLDG.unknown, utils.REF.hasObservation, utils.BLDG.obs_unknown_1) in building.get_graph()
    assert all(value.datatype == utils.XSD.float for value in building.get_graph().objects(None, utils.REF.hasValue))
    app.agent._extract_date_metadata()
    assert app.agent.dataset_year == '2025'
    with pytest.raises(IndexError):
        building.add_timeseries_data(str(source), start_date='2030-01-01')


def decomposition():
    return QueryDecomposition(
        [SensorMention('room', 'brick:Zone_Air_Temperature_Sensor', 'room temperature'),
         SensorMention('other', 'brick:Zone_Air_Temperature_Sensor', 'other temperature')],
        2, TemporalConstraint(False, 'none', {}, ''), AggregationRequirement(False, [], []), 'compare', {})






def test_validation_warning_reaches_agent_observation(building):
    d = decomposition()
    d.aggregation = AggregationRequirement(True, ['AVG'], [])
    app.agent._current_state = AgentState('average', decomposition=d)
    action, query = app.agent.execute_action(BrickAction('retrieve', 'execute_sparql', 'SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }'))
    assert query.diagnostic_warnings and not query.validation_warnings
    assert 'Missing aggregation' not in action.observation


def test_metrics_keep_global_column_pairing():
    gold = [{'a':'A','b':'B'}, {'a':'B','b':'C'}]
    incorrect = [{'a':'B','b':'A'}, {'a':'B','b':'C'}]
    assert score_rows(gold, incorrect)['row_matching_f1'] == .5
    swapped = [{'other':'B','name':'A'}, {'other':'C','name':'B'}]
    assert score_rows(gold, swapped)['row_matching_f1'] == 1
    assert score_rows(gold, swapped)['exact_match'] == 0
    assert score_rows(gold, [{'x':'A','y':'B'},{'x':'B','y':'C'}])['exact_match'] == 1


def test_sample_recovery_only_keeps_complete_statements():
    text = '@prefix x: <urn:x:> .\nx:a x:p "a.b" .\nx:b x:p [ x:q "incomplete" ;'
    prefix = complete_turtle_prefix(text)
    assert len(Graph().parse(data=prefix, format='turtle')) == 1


def test_api_repeated_query_export_and_validation(building):
    client = TestClient(app.app)
    app.agent.controller = lambda state: BrickAction('Retrieve','execute_sparql','SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }') if not state.actions else BrickAction('Finish','stop','')
    for i in range(2):
        response = client.post('/api/ask', json={'question':'楼里有哪些温度传感器？'})
        assert response.status_code == 200
        tid = response.json()['task_id']
        for _ in range(100):
            data = client.get('/api/task/'+tid).json()
            if data['status'] != 'running':
                break
            time.sleep(.01)
        assert data['status'] == 'done'
        assert data['final_sparql']['num_results'] == 2
        assert client.get('/api/task/'+tid+'/export').content.startswith(b'\xef\xbb\xbf')
        assert len(client.get('/api/task/'+tid+'/results?offset=1&limit=1').json()['rows']) == 1
    assert client.post('/api/ask', json={'question':123}).status_code == 422
    assert client.post('/api/sparql', json={'query':'ASK {}','limit':-1}).status_code == 422


def test_failed_load_keeps_previous_graph(building, tmp_path):
    invalid = tmp_path / 'bad.ttl'
    invalid.write_text('this is not turtle', encoding='utf-8')
    original = utils.BrickGraph().get_graph()
    client = TestClient(app.app)
    assert client.post('/api/load', json={'ttl':str(invalid)}).status_code == 400
    assert utils.BrickGraph().get_graph() is original


def test_busy_load_rejected(building, monkeypatch):
    monkeypatch.setattr(app, '_active_tid', 'running')
    client = TestClient(app.app)
    assert client.post('/api/load', json={'ttl':'anything.ttl'}).status_code == 409
    assert client.post('/api/evaluate', json={}).status_code == 409


@pytest.mark.parametrize('question', ['室温最新值', '昨天的室外温度', '最近24小时的最大值'])
def test_chinese_temporal_queries_decompose(question):
    assert BrickQueryDecomposer().should_decompose(question)
