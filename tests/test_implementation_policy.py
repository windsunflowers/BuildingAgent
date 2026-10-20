import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef, Literal, RDF, RDFS, XSD

import app
import brick_utils as utils
from brick_agent import BrickAgent, BrickAction, AgentState, BrickSparqlQuery
from brick_decomposer import QueryDecomposition, SensorMention, TemporalConstraint, AggregationRequirement
from brick_utils import SparqlExecutionStatus
from evaluation_runner import evaluate_question
from evaluation_metrics import METRIC_KEYS
from implementation_policy import evaluation_policy, evaluation_timeout
from implementation_policy import UPSTREAM_COMMIT, author

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def author_graph(monkeypatch):
    monkeypatch.setattr(utils, '_merge_brick_ontology', lambda graph: False)
    utils.BrickGraph.reset_singleton()
    def make():
        utils.BrickGraph.reset_singleton()
        data = Graph()
        data.bind('plant', 'https://example.net/plant#')
        for i in range(12):
            sensor = URIRef(f'https://example.net/plant#T{i}')
            data.add((sensor, RDF.type, utils.BRICK.Temperature_Sensor))
            data.add((sensor, RDFS.label, Literal(f'Room temp {i}')))
        data.add((URIRef('https://example.net/plant#T0'), utils.BRICK.hasPoint, URIRef('https://example.net/plant#T1')))
        bg = utils.BrickGraph()
        bg.initialize(graph=data)
        return bg
    yield make
    utils.BrickGraph.reset_singleton()


def test_pinned_source_is_byte_identical_to_commit():
    raw = subprocess.check_output(['git', 'show', f'{UPSTREAM_COMMIT}:brick_utils.py'], cwd=ROOT)
    assert (ROOT / 'third_party/brickqa_upstream/brick_utils.py').read_bytes() == raw
    manifest = json.loads((ROOT / 'third_party/brickqa_upstream/source_manifest.json').read_text(encoding='utf-8'))
    assert manifest['sha256'] == hashlib.sha256(raw).hexdigest()
    for name, info in manifest['additional_files'].items():
        original = subprocess.check_output(['git', 'show', f'{UPSTREAM_COMMIT}:{name}'], cwd=ROOT)
        assert (ROOT / 'third_party/brickqa_upstream' / name).read_bytes() == original
        assert hashlib.sha256(original).hexdigest() == info['sha256']


def test_search_matches_original_order_limit_uri_types_and_labels(author_graph, monkeypatch):
    bg = author_graph()
    reference = object.__new__(author.BrickGraph)
    reference._graph = bg.get_graph()
    monkeypatch.setattr(author.BrickGraph, '_instance', reference)
    for term in ('example.net/plant', 'Temperature_Sensor', 'Room temp', 'no match'):
        expected = author.search_brick.__wrapped__(term)
        assert utils.search_brick(term) == expected
    assert len(utils.search_brick('Temperature_Sensor')) == 8
    assert len(utils.search_brick('Temperature_Sensor', 3)) == 3
    assert utils.search_brick('example.net/plant')  # Full URI, not just local name.
    assert utils.search_brick('Room temp')  # No underscore normalization.


def test_author_entity_and_property_rules_do_not_fall_back(author_graph):
    bg = author_graph()
    assert not utils.get_brick_entity('T0')['properties']
    assert utils.get_brick_entity('T0')['uri'] == 'bldg-59#T0'
    assert 'constant bldg-59#' in bg.last_tool_diagnostic['reason']
    assert not utils.get_brick_entity('plant:T0')['properties']
    assert utils.get_brick_entity('plant:T0')['uri'] == 'bldg-59#plant:T0'
    assert utils.get_brick_entity('https://example.net/plant#T0')['properties']
    assert utils.get_property_examples('brick:hasPoint') == []
    assert bg.last_tool_diagnostic['resolved_uri'] == 'brick:hasPoint'
    assert utils.get_property_examples('hasPoint') == []
    assert bg.last_tool_diagnostic['resolved_uri'] == str(utils.REF.hasPoint)
    assert utils.get_property_examples(str(utils.BRICK.hasPoint))
    events = [json.loads(line) for line in Path(bg.diagnostic_log).read_text(encoding='utf-8').splitlines()]
    assert events and all(event['fallback_used'] is False for event in events)


def test_original_search_errors_are_recorded_without_repair(author_graph):
    bg = author_graph()
    assert utils.search_brick('"') == []
    assert bg.last_tool_diagnostic['status'] == 'error'
    assert bg.last_tool_diagnostic['errors'][0]['reason']
    assert bg.last_tool_diagnostic['fallback_used'] is False


def test_csv_matches_original_rdf_and_preserves_file_order_and_row_indices(author_graph, tmp_path):
    csv = tmp_path / 'data.csv'
    csv.write_text('Datetime,T0,unknown\n01/03/2018 12:00,30,300\n01/01/2018 12:00,10,100\n01/02/2018 12:00,20,200\n', encoding='utf-8')
    bg = author_graph()
    expected = object.__new__(author.BrickGraph)
    expected._graph = Graph()
    for triple in bg.get_graph():
        expected._graph.add(triple)
    author.BrickGraph.add_timeseries_data(expected, str(csv), 2, '2018-01-01', '2018-01-03')
    bg.add_timeseries_data(str(csv), 2, '2018-01-01', '2018-01-03')
    assert set(bg.get_graph()) == set(expected._graph)
    assert bg.timeseries_meta['selected_row_indices'] == [1, 2]
    assert (utils.BLDG.T0, utils.REF.hasObservation, utils.BLDG.obs_T0_1) in bg.get_graph()
    assert (utils.BLDG.unknown, utils.REF.hasObservation, utils.BLDG.obs_unknown_2) in bg.get_graph()
    values = list(bg.get_graph().objects(None, utils.REF.hasValue))
    assert values and all(value.datatype == XSD.float for value in values)
    stamps = list(bg.get_graph().objects(None, utils.REF.hasTimestamp))
    assert all(stamp.datatype == XSD.dateTime for stamp in stamps)
    assert not list(bg.get_graph().objects(URIRef('https://example.net/plant#T0'), utils.REF.hasObservation))


@pytest.mark.parametrize('text,start,end,error', [
    ('Datetime,T0\n2018-01-01T12:00:00,1\n', None, None, ValueError),
    ('Datetime,T0\n01/01/2018 12:00,1\n', '2019-01-01', None, IndexError),
    ('Datetime,T0\n01/01/2018 12:00,bad-number\n', None, None, ValueError),
])
def test_csv_original_failures_are_recorded(author_graph, tmp_path, text, start, end, error):
    bg = author_graph()
    csv = tmp_path / 'bad.csv'
    csv.write_text(text, encoding='utf-8')
    with pytest.raises(error):
        bg.add_timeseries_data(str(csv), 100, start, end)
    event = json.loads(Path(bg.diagnostic_log).read_text(encoding='utf-8').splitlines()[-1])
    assert event['status'] == 'error' and event['reason']
    assert event['fallback_used'] is False


def test_author_language_and_api_have_no_method_switch(author_graph, monkeypatch):
    bg = author_graph()
    runner = BrickAgent(use_decomposer=False)
    action, _ = runner.execute_action(BrickAction('inspect', 'get_brick_entity', 'T0'))
    before = set(bg.get_graph())
    runner.language = 'en'
    other, _ = runner.execute_action(BrickAction('inspect', 'get_brick_entity', 'T0'))
    assert action.observation_raw == other.observation_raw
    assert set(bg.get_graph()) == before
    assert runner.implementation_mode == bg.implementation_mode == 'upstream'
    client = TestClient(app.app)
    for route, payload in [('/api/ask',{'question':'test','mode':'local'}),('/api/ask',{'question':'test','implementation_mode':'fixed'}),('/api/load',{'ttl':'x.ttl','implementation_mode':'fixed'}),('/api/evaluate',{'implementation_mode':'fixed'})]:
        assert client.post(route,json=payload).status_code == 422
    for schema in ('AskRequest','LoadRequest','EvalRequest'):
        assert 'implementation_mode' not in client.get('/openapi.json').json()['components']['schemas'][schema]['properties']
    assert not hasattr(utils, '_search_brick_fixed')
    assert not hasattr(utils.BrickGraph, '_add_timeseries_data_fixed')


def test_cli_defaults_to_author_methods(monkeypatch, tmp_path):
    import evaluate
    bench = tmp_path / 'empty.jsonl'
    bench.write_text('', encoding='utf-8')
    report = tmp_path / 'report.json'
    monkeypatch.setattr('sys.argv', ['evaluate.py', '--benchmark', str(bench), '--report', str(report)])
    evaluate.main()
    assert json.loads(report.read_text(encoding='utf-8'))['configuration']['implementation_mode'] == 'upstream'




def _native_run():
    import ast
    from typing import Tuple, Optional
    source = (ROOT / 'third_party/brickqa_upstream/brick_agent.py').read_text(encoding='utf-8')
    cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == 'BrickAgent')
    run = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
    namespace = {'Tuple':Tuple, 'Optional':Optional, 'AgentState':AgentState,
                 'BrickAction':BrickAction, 'BrickSparqlQuery':BrickSparqlQuery}
    exec(compile(ast.Module(body=[run], type_ignores=[]), '<pinned BrickQA run>', 'exec'), namespace)
    return namespace['run']


@pytest.mark.parametrize('scenario', ['warning_stop', 'duplicate', 'max_steps', 'failed_last_query', 'no_query'])
def test_author_stop_and_final_selection_match_pinned_run(author_graph, monkeypatch, scenario):
    author_graph()
    for run_method in (_native_run(), BrickAgent.run):
        runner = BrickAgent(use_decomposer=False)
        calls = []
        final = BrickSparqlQuery('SELECT ?x WHERE {}', execution_result=[{'x':'A'}],
                                 execution_status=SparqlExecutionStatus.SUCCESS, diagnostic_warnings=['Missing sensors: test'])
        if scenario == 'failed_last_query':
            final.execution_status = SparqlExecutionStatus.SYNTAX_ERROR
        def controller(state):
            index = len(calls)
            calls.append(index)
            if scenario == 'no_query' or (scenario in ('warning_stop','failed_last_query') and index):
                return BrickAction('finish', 'stop', '')
            return BrickAction('query', 'execute_sparql', 'same' if scenario=='duplicate' else str(index))
        runner.controller = controller
        runner.execute_action = lambda action: (action, final if action.action_name=='execute_sparql' else None)
        state, selected = run_method(runner, 'offline test', verbose=False)
        result = ([(a.action_name,a.action_argument) for a in state.actions], selected)
        if run_method is BrickAgent.run:
            assert result == expected
        else:
            expected = result
        assert len(state.actions) <= 15


@pytest.mark.parametrize('language', ['zh','en'])
def test_author_diagnostics_do_not_reject_correct_results(author_graph, monkeypatch, language):
    author_graph()
    runner = BrickAgent(use_decomposer=False, language=language)
    decomposition = QueryDecomposition([SensorMention('setpoint','brick:Zone_Air_Temperature_Setpoint','test')],
        1, TemporalConstraint(False,'none',{},''), AggregationRequirement(False,[],[]), 'test', {})
    query = 'SELECT ?value WHERE { VALUES ?value { "A" "B" } }'
    actions = iter([BrickAction('query','execute_sparql',query), BrickAction('finish','stop','')])
    def controller(state):
        state.decomposition = decomposition
        return next(actions)
    monkeypatch.setattr(runner, 'controller', controller)
    original = BrickSparqlQuery.execute
    monkeypatch.setattr(BrickSparqlQuery, 'execute', lambda self, isolated=True: original(self, isolated=False))
    result = evaluate_question(runner, {'question':'offline test', 'gold_sparql':query})
    assert result['status'] == 'done'
    assert all(result[key] == 1 for key in METRIC_KEYS)
    assert result['diagnostic_warnings'] and not result['validation_warnings']
    assert result['stop_reason'] == 'model_stop'
    assert 'Missing sensors' not in runner._current_state.actions[0].observation
    assert runner._current_state.actions[0].action_argument == query


def test_author_failed_sparql_is_not_scored_as_valid_empty(author_graph, monkeypatch):
    author_graph()
    runner = BrickAgent(use_decomposer=False)
    final = BrickSparqlQuery('SELECT {', execution_result=[], execution_status=SparqlExecutionStatus.SYNTAX_ERROR, error='parse error')
    monkeypatch.setattr(runner, 'run', lambda *args, **kwargs: (AgentState('test'), final))
    result = evaluate_question(runner, {'question':'test','gold_sparql':'SELECT ?x WHERE { FILTER(false) }'})
    assert result['status'] == 'error'
    assert result['pred_sparql'] == final.sparql
    assert result['execution_error'] == 'parse error'
    assert all(result[key] == 0 for key in METRIC_KEYS)


def test_question_deadline_is_explicit_and_mode_specific():
    assert evaluation_timeout() is None
    assert evaluation_timeout(30) == 30
    assert evaluation_timeout(0) is None
    assert evaluation_policy()['sparql_timeout_seconds'] == 180
    for invalid in (-1, float('inf'), float('nan')):
        with pytest.raises(ValueError):
            evaluation_timeout(invalid)
