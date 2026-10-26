"""Judge behavior cannot depend on the method being evaluated."""
from types import SimpleNamespace
import pytest
import brick_utils
from evaluation_runner import evaluate_question, gold_query_text
from test_language_and_metrics import tiny_agent
from react_baseline import ReActBaselineAgent


@pytest.mark.parametrize('method', ['brickqa', 'react'])
def test_gold_does_not_rewrite_declared_namespaces(tiny_agent, monkeypatch, method):
    agent = ReActBaselineAgent(tiny_agent, backend='rdflib') if method == 'react' else tiny_agent
    def model_must_not_run(*args, **kwargs):
        pytest.fail('This test stops after the gold stage')
    monkeypatch.setattr(agent, 'run', model_must_not_run)
    # A well-formed wrong prefix must remain wrong; no method-specific repair.
    query = ('PREFIX brick: <urn:wrong:> '
             'SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }')
    import threading
    cancelled = threading.Event()
    def progress(stage):
        if stage == 'model':
            cancelled.set()
    row = evaluate_question(agent, {'question':'test', 'gold_sparql':query},
                            cancel_event=cancelled, on_progress=progress)
    assert row['gold_count'] == 0
    assert row['gold_execution_sparql'] == query
    assert row['gold_execution_status'] == 'empty_result'


def test_only_missing_gold_prefixes_follow_reference_ttl_extraction(tmp_path):
    path = tmp_path/'source.ttl'
    path.write_text('@prefix ex: <urn:source:> .\n@prefix p: <urn:p:> .\n', encoding='utf-8')
    query = 'SELECT ?s WHERE { ?s ex:p ?o }'
    assert gold_query_text(query, path) == 'PREFIX ex: <urn:source:>\nPREFIX p: <urn:p:>\n\n' + query
    declared = 'PREFIX ex: <urn:other:> ' + query
    assert gold_query_text(declared, path) == declared


def test_transport_failure_is_not_sparql_syntax_error(monkeypatch):
    import sparql_worker
    from rdflib import Graph
    monkeypatch.setattr(sparql_worker, 'run_isolated',
                        lambda *a: ('worker_error', 'EOFError; pid=123; exitcode=1'))
    _, status, error = brick_utils.query_graph('SELECT * WHERE {}', graph=Graph())
    assert status is brick_utils.SparqlExecutionStatus.OTHER_ERROR
    assert 'exitcode=1' in error


def test_empty_exception_message_remains_diagnosable(monkeypatch):
    from rdflib import Graph
    graph = Graph()
    def fail(*a, **kw):
        raise AssertionError()
    monkeypatch.setattr(graph, 'query', fail)
    _, _, error = brick_utils.query_graph('SELECT * WHERE {}', graph=graph, isolated=False)
    assert error == 'AssertionError: no exception message'


def test_worker_eof_keeps_process_evidence():
    from sparql_worker import QueryWorker
    graph = object()
    worker = QueryWorker()
    class Pipe:
        def send(self, value): pass
        def poll(self, timeout): return True
        def recv(self): raise EOFError()
        def close(self): pass
    worker.graph = graph
    worker.pipe = Pipe()
    worker.process = SimpleNamespace(pid=123, exitcode=7, is_alive=lambda:True,
                                    terminate=lambda:None, join=lambda **kw:None)
    kind, error = worker.run(graph, 'SELECT * WHERE {}', None, 1)
    assert kind == 'worker_error'
    assert 'EOFError' in error and 'pid=123' in error and 'exitcode=7' in error


@pytest.mark.parametrize('fails', [False, True])
def test_child_blas_limit_restores_parent_even_when_start_fails(monkeypatch, fails):
    import os
    from sparql_worker import _start_query_process, _NUMERICAL_THREADS
    monkeypatch.setenv('OPENBLAS_NUM_THREADS', '24')
    monkeypatch.delenv('OMP_NUM_THREADS', raising=False)
    previous = {key: os.environ.get(key) for key in _NUMERICAL_THREADS}
    def start():
        assert all(os.environ[key] == '1' for key in _NUMERICAL_THREADS)
        if fails:
            raise OSError('offline startup failure')
    if fails:
        with pytest.raises(OSError, match='startup failure'):
            _start_query_process(SimpleNamespace(start=start))
    else:
        _start_query_process(SimpleNamespace(start=start))
    assert {key: os.environ.get(key) for key in _NUMERICAL_THREADS} == previous
