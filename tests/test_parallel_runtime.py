"""Offline concurrency checks, including real spawned RDF workers on Windows."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import threading
from pathlib import Path
from unittest.mock import Mock

from rdflib import Graph

import brick_utils
import llm_client
from sparql_worker import isolated_query_session


def test_concurrent_queries_use_different_processes_and_clean_up():
    graph = Graph().parse(data='<urn:s> <urn:p> <urn:o> .', format='turtle')
    barrier = threading.Barrier(2)
    sessions = []
    def execute(value):
        with isolated_query_session() as worker:
            sessions.append(worker)
            barrier.wait(timeout=5)
            data, status, error = brick_utils.query_graph(
                'SELECT ?v WHERE { VALUES ?v { "' + value + '" } }', graph=graph, timeout=10)
            assert error is None and status is brick_utils.SparqlExecutionStatus.SUCCESS
            return data['rows'], worker.process.pid
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, ['first','second']))
    assert [r[0] for r in results] == [[{'v':'first'}],[{'v':'second'}]]
    assert len({r[1] for r in results}) == 2
    assert all(s.process is None and s.pipe is None for s in sessions)


def test_model_clients_and_usage_are_thread_local(monkeypatch):
    barrier = threading.Barrier(3)
    class OfflineClient:
        def __init__(self):
            self.model = 'offline'
            self.base_url = 'offline'
            self.client = Mock()
    monkeypatch.setattr(llm_client, 'LLMClient', OfflineClient)
    def generate(value):
        client = llm_client.get_client()
        client.last_usage = value
        barrier.wait(timeout=5)
        assert llm_client.get_client() is client and client.last_usage == value
        llm_client.close_thread_client()
        client.client.close.assert_called_once()
        return client
    with ThreadPoolExecutor(max_workers=3) as pool:
        clients = list(pool.map(generate, range(3)))
    assert len({id(client) for client in clients}) == 3


def test_cli_process_pool_preserves_failed_gold_rows_without_calling_model(tmp_path):
    root = Path(__file__).resolve().parents[1]
    benchmark = tmp_path / 'questions.jsonl'
    benchmark.write_text('\n'.join(json.dumps({'question':str(i)}) for i in range(3)), encoding='utf-8')
    report = tmp_path / 'report.json'
    subprocess.run([str(root / '.venv/Scripts/python.exe'), str(root / 'evaluate.py'),
                    '--benchmark',str(benchmark),'--report',str(report),'--workers','2'],
                   cwd=root, check=True, capture_output=True, timeout=45)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result['configuration']['workers'] == 2
    assert [r['question_index'] for r in result['results']] == [1,2,3]
    assert [r['question'] for r in result['results']] == ['0','1','2']
    assert result['summary']['gold_errors'] == 3
