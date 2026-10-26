"""Author GraphDB branch, explicit backend isolation and real HTTP transport."""
import ast
import __future__
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import react_graphdb
from react_baseline import ReActBaselineAgent
from react_reference import ROOT, reference
from evaluation_runner import evaluate_question
from evaluation_metrics import METRIC_KEYS
from test_language_and_metrics import tiny_agent
from test_react_baseline import scripted_client, WRITER, CRITIC


def test_endpoint_mapping_and_unknown_building():
    assert react_graphdb.endpoint_for('data/buildings/TUC_building.ttl').endswith('/TUC_building_test')
    assert react_graphdb.endpoint_for('dflexlibs_multizone').endswith('/DFLEX')
    assert react_graphdb.endpoint_for('bldg11').endswith('/bldg11')
    with pytest.raises(ValueError, match='No GraphDB'):
        react_graphdb.endpoint_for('unknown')


@pytest.mark.parametrize('count', [0, 15])
def test_remote_execution_matches_original_branch(tiny_agent, monkeypatch, count):
    bindings = [{'n':{'type':'literal','value':str(n),'datatype':'urn:integer'}} for n in range(count)]
    payload = {'head':{'vars':['n','missing']}, 'results':{'bindings':bindings}}
    class Wrapper:
        def __init__(self, endpoint): pass
        def setQuery(self, query): pass
        def setReturnFormat(self, value): pass
        def query(self): return self
        def convert(self): return payload
    # Execute the pinned original method, not a hand-written expected summary.
    tree = ast.parse((ROOT/'sparql_refinement_agent.py').read_bytes())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='SparqlRefinementAgent')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name=='_run_sparql_query')
    namespace = {'SPARQLWrapper':Wrapper, 'JSON':'JSON', 'json':json}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'original-graphdb','exec',
                 flags=__future__.annotations.compiler_flag),namespace)
    expected = namespace['_run_sparql_query'](SimpleNamespace(is_remote=True,sparql_endpoint_url='http://test'), 'SELECT ?n WHERE {}')
    monkeypatch.setattr(react_graphdb,'execute_json',lambda *a:(payload['head']['vars'],bindings))
    _,actual = ReActBaselineAgent(tiny_agent,backend='graphdb',building='TUC_building')._run_sparql_query('SELECT ?n WHERE {}')
    assert actual == expected
    assert len(actual['results']) == count


def test_remote_failure_never_falls_back_to_rdflib(tiny_agent, monkeypatch):
    def fail(*args): raise OSError('Repository unavailable')
    monkeypatch.setattr(react_graphdb,'execute_json',fail)
    agent=ReActBaselineAgent(tiny_agent,backend='graphdb',building='bldg11')
    _,result=agent._run_sparql_query('SELECT ?x WHERE { VALUES ?x { 1 } }')
    assert result['results']==[] and result['syntax_ok'] is False
    assert result['summary_string']=='The query failed to execute with the following error: Repository unavailable'


def test_gold_writer_final_share_http_repository_and_full_score(tiny_agent, monkeypatch):
    requests=[]
    bindings=[{'n':{'type':'literal','value':str(n)}} for n in range(15)]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path,self.headers['Accept']))
            if 'BAD_QUERY' in self.path:
                self.send_response(400); self.end_headers(); self.wfile.write(b'Endpoint parse detail'); return
            data=json.dumps({'head':{'vars':['n']},'results':{'bindings':bindings}}).encode()
            self.send_response(200); self.send_header('Content-Type','application/sparql-results+json')
            self.end_headers(); self.wfile.write(data)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    endpoint=f'http://127.0.0.1:{server.server_port}/repositories/TUC'
    monkeypatch.setattr(react_graphdb,'endpoint_for',lambda building:endpoint)
    query='SELECT ?n WHERE { VALUES ?n { 1 } }'
    _,calls=scripted_client(monkeypatch,[WRITER(query),CRITIC()])
    try:
        row=evaluate_question(ReActBaselineAgent(tiny_agent,backend='graphdb',building='TUC_building'),
                              {'question':'List values','gold_sparql':query})
        with pytest.raises(RuntimeError, match='Endpoint parse detail'):
            react_graphdb.execute_json(endpoint,'SELECT ?n WHERE { <urn:BAD_QUERY> ?p ?n }',5)
    finally:
        server.shutdown(); server.server_close(); thread.join()
    assert row['status']=='done' and row['gold_count']==row['pred_count']==15
    assert all(row[key]==1 for key in METRIC_KEYS)
    assert len(requests)==4  # gold, writer, final, explicit HTTP-error check.
    for path,accept in requests[:3]:
        assert urlsplit(path).path=='/repositories/TUC'
        assert parse_qs(urlsplit(path).query)=={'query':[query]}
        assert accept=='application/sparql-results+json'
    critic=calls[1][0][1]['content'].split('Execution Results Summary:\n',1)[1]
    assert critic=='Query executed successfully. Here are the first 10 results:\n'+json.dumps(bindings[:10],indent=2)
    assert row['evaluation_graph']['endpoint']==endpoint
    assert row['implementation_mode']=='buildingqa_react_graphdb_author_v1'
    assert row['gold_execution_policy']=='same_graphdb_repository_as_prediction_v1'
    assert reference('rdflib')['feedback_policy']=='upstream_rdflib_row_count_only_v1'


def test_transport_rejects_updates_before_network():
    with pytest.raises(Exception):
        react_graphdb.execute_json('http://127.0.0.1:1', 'DELETE WHERE { ?s ?p ?o }',1)


def test_api_forwards_selected_backend(tiny_agent, monkeypatch, tmp_path):
    import app
    captured=[]
    class OfflineThread:
        def __init__(self,target,args,**kwargs): captured.append(args)
        def start(self): pass
    monkeypatch.setattr(app.threading,'Thread',OfflineThread)
    monkeypatch.setattr(react_graphdb,'endpoint_for',lambda building:'http://offline')
    monkeypatch.setattr(react_graphdb,'check_repository',lambda endpoint:None)
    path=tmp_path/'benchmark.jsonl'
    path.write_text(json.dumps({'question':'List values'}),encoding='utf-8')
    receipt=app.start_eval(app.EvalRequest(benchmark=str(path),method='react'))
    assert receipt['method']=='react' and receipt['react_backend']=='graphdb'
    assert captured[-1][-2:]==('graphdb','react')
    with pytest.raises(Exception):
        app.EvalRequest(react_backend='automatic_fallback')


def test_default_graphdb_uses_notebook_three_rounds(tiny_agent, monkeypatch):
    import inspect
    import evaluate
    from evaluation_methods import evaluation_agent
    from react_reference import MAX_ITERATIONS
    assert reference()['execution_mode'] == 'remote_GraphDB'
    assert reference()['max_iterations'] == MAX_ITERATIONS == 3
    assert inspect.signature(evaluation_agent).parameters['backend'].default == 'graphdb'
    # CLI source is checked alongside the API default without invoking models.
    assert "choices=('rdflib', 'graphdb'), default='graphdb'" in inspect.getsource(evaluate.main)
    bindings = [{'x': {'type':'literal', 'value':'1'}}]
    monkeypatch.setattr(react_graphdb, 'execute_json', lambda *args:(['x'], bindings))
    query = 'SELECT ?x WHERE { VALUES ?x { 1 } }'
    _, calls = scripted_client(monkeypatch, [answer for _ in range(3)
                                            for answer in (WRITER(query), CRITIC('IMPROVE', 'Revise'))])
    agent = evaluation_agent(tiny_agent, 'react', building='TUC_building')
    state, final = agent.run('List values', verbose=False)
    assert agent.execution_backend == 'graphdb'
    assert agent.endpoint.endswith('/repositories/TUC_building_test')
    assert len(calls) == 6 and state.react_iterations == 3
    assert state.stop_reason == 'max_iterations' and final.sparql == query


def test_refused_connection_includes_endpoint_and_is_transport_failure(monkeypatch):
    from urllib.error import URLError
    class Opener:
        def open(self, *args, **kwargs):
            raise URLError(ConnectionRefusedError(10061, 'connection refused'))
    monkeypatch.setattr(react_graphdb, 'build_opener', lambda *args:Opener())
    with pytest.raises(react_graphdb.GraphDBUnavailableError, match='http://offline/repositories/TUC'):
        react_graphdb.check_repository('http://offline/repositories/TUC')


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_api_unavailable_repository_starts_no_evaluation(tiny_agent, monkeypatch, tmp_path, language):
    import app
    from fastapi import HTTPException
    path = tmp_path/'benchmark.jsonl'
    path.write_text(json.dumps({'question':'List values'}), encoding='utf-8')
    monkeypatch.setattr(react_graphdb, 'endpoint_for', lambda building:'http://offline')
    def fail(endpoint):
        raise react_graphdb.GraphDBUnavailableError('connection refused: '+endpoint)
    monkeypatch.setattr(react_graphdb, 'check_repository', fail)
    monkeypatch.setattr(app.threading, 'Thread', lambda *a, **kw:pytest.fail('No worker may start'))
    with pytest.raises(HTTPException) as error:
        app.start_eval(app.EvalRequest(benchmark=str(path), method='react', react_backend='graphdb',
                                      interface_language=language))
    assert error.value.status_code == 503
    assert ('评测尚未启动' if language=='zh' else 'evaluation has not started') in error.value.detail
    assert not app.eval_tasks and not app._eval_running
