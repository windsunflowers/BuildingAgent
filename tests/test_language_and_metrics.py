import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app
import brick_decomposer
import brick_utils
import llm_client
from brick_agent import AgentState, BrickAction, BrickAgent, BrickSparqlQuery
from brick_utils import SparqlExecutionStatus
from evaluation_metrics import METRIC_KEYS, score_rows, summarize_results
from evaluation_runner import evaluate_question, GoldSparqlQuery
from prompting import load_prompt

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = '49d9e283c2a3958e9be110583be6575cbd40039b'


@pytest.fixture
def tiny_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(brick_utils, '_merge_brick_ontology', lambda graph: True)
    brick_utils.BrickGraph.reset_singleton()
    path = tmp_path / 'building.ttl'
    path.write_text('''@prefix bldg: <urn:test:> .
      @prefix brick: <https://brickschema.org/schema/Brick#> .
      @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
      brick:Zone_Air_Temperature_Sensor rdfs:subClassOf brick:Temperature_Sensor .
      bldg:temperature a brick:Zone_Air_Temperature_Sensor .''', encoding='utf-8')
    a = BrickAgent(use_decomposer=False, language='en')
    a.initialize_graph(ttl_file=str(path))
    a.log_file = str(tmp_path / 'prompts.jsonl')
    original_execute = BrickSparqlQuery.execute
    monkeypatch.setattr(BrickSparqlQuery, 'execute', lambda self, isolated=True: original_execute(self, isolated=False))
    original_gold_execute = GoldSparqlQuery.execute
    monkeypatch.setattr(GoldSparqlQuery, 'execute', lambda self, isolated=True: original_gold_execute(self, isolated=False))
    monkeypatch.setattr(app, 'agent', a)
    monkeypatch.setattr(app, 'graph_meta', {'building': 'building', 'ttl': str(path), 'warnings': [], 'triples': 1, 'sensors': 1})
    monkeypatch.setattr(app, '_active_tid', None)
    monkeypatch.setattr(app, '_eval_running', False)
    monkeypatch.setattr(app, '_loading', False)
    monkeypatch.setattr(app, 'tasks', {})
    monkeypatch.setattr(app, 'eval_tasks', {})
    monkeypatch.setattr(app, '_eval_cancel_events', {})
    monkeypatch.setattr(app, '_eval_execution_events', {})
    monkeypatch.setattr(app, '_eval_agents', {})
    monkeypatch.setattr(app, 'BASE_DIR', tmp_path)
    yield a
    brick_utils.BrickGraph.reset_singleton()


@pytest.mark.parametrize('name', ['brick_controller.prompt', 'brick_decomposition.prompt'])
def test_english_templates_are_exact_upstream_files(name):
    expected = subprocess.check_output(['git', 'show', f'{UPSTREAM}:prompts/{name}'], cwd=ROOT)
    assert (ROOT / 'prompts/en' / name).read_bytes() == expected
    assert not re.search('[一-鿿]', load_prompt(name, 'en'))


def test_english_agent_uses_english_prompt_and_tool_feedback(tiny_agent, monkeypatch):
    prompts = []
    answers = iter(['Thought: Retrieve temperature sensors.\nAction: execute_sparql(SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor })',
                    'Thought: The question is answered.\nAction: stop()'])
    def generate(prompt, **kwargs):
        prompts.append(prompt)
        return next(answers)
    fake = SimpleNamespace(generate_text=generate, last_usage=None, model='offline-test')
    monkeypatch.setattr(llm_client, 'get_client', lambda: fake)
    state, final = tiny_agent.run('Which sensors exist?', verbose=False)
    assert state.language == 'en'
    assert len(final.execution_result) == 1
    assert len(prompts) == 2
    assert all(not re.search('[一-鿿]', prompt) for prompt in prompts)
    assert all('{{' not in prompt and '{%' not in prompt for prompt in prompts)
    assert 'Your task is' in prompts[0]
    assert 'Namespaces in the loaded graph' not in prompts[0]
    assert 'Brick class aliases use' not in prompts[0]
    import hashlib
    requests = [json.loads(line) for line in Path(tiny_agent.log_file).read_text(encoding='utf-8').splitlines()
                if json.loads(line).get('event') == 'model_request']
    assert len(requests) == len(prompts) == 2
    for request, prompt in zip(requests, prompts):
        raw = Path(request['prompt_file']).read_bytes()
        assert raw.decode('utf-8') == prompt
        assert hashlib.sha256(raw).hexdigest() == request['prompt_sha256']
    tiny_agent.language = 'zh'
    # Legacy assignments now change display only; user text stays verbatim.
    from prompting import build_controller_prompt
    prompt, _ = build_controller_prompt(tiny_agent, AgentState('保留用户问题'))
    assert '保留用户问题' in prompt and '用中文' not in prompt
    assert tiny_agent.language == 'en' and tiny_agent.interface_language == 'zh'


def test_english_decomposer_does_not_receive_chinese_instructions(monkeypatch):
    prompts = []
    def generate(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({'sensors': [], 'query_intent': 'List sensors'})
    monkeypatch.setattr(brick_decomposer, 'get_client', lambda: SimpleNamespace(generate_text=generate, last_usage=None))
    d = brick_decomposer.BrickQueryDecomposer()
    result = d.decompose('List sensors', verbose=False, context='Namespaces: urn:test:', language='en')
    assert result.query_intent == 'List sensors'
    assert not d.last_fallback
    assert not re.search('[一-鿿]', prompts[0])


@pytest.mark.parametrize('gold,pred,expected', [
    ([{'a':'A'},{'a':'B'}], [{'x':'A'}], (2/3,2/3,2/3)),
    ([{'a':'A'},{'a':'A'}], [{'x':'A'}], (1,2/3,2/3)),
    ([{'a':'A','b':'B'}], [{'x':'B','y':'A'}], (1,1,0)),
    ([{'a':'A','b':'B'}], [{'x':'A'}], (0,0,0)),
    ([{'a':'A'}], [{'x':'A','y':'B'}], (1,1,0)),
    ([{'a':'A','b':'B'},{'a':'A','b':'C'}], [{'x':'A','y':'B'},{'x':'Z','y':'B'}], (.75,.5,.5)),
    ([{'a':'ABC'}], [{'x':'abc'}], (0,1,1)),
    ([], [], (1,1,1)),
    ([{'a':'A'}], [], (0,0,0)),
])
def test_reference_metric_edge_cases(gold, pred, expected):
    scores = score_rows(gold, pred)
    assert tuple(scores[key] for key in METRIC_KEYS) == pytest.approx(expected)


def test_metrics_keep_global_column_alignment():
    gold = [{'a':'A','b':'B'},{'a':'B','b':'C'}]
    pred = [{'x':'B','y':'A'},{'x':'B','y':'C'}]
    assert score_rows(gold, pred)['row_matching_f1'] == .5


def test_failures_and_building_macro_use_explicit_denominators():
    perfect = {'status':'done','building':'a', **{key:1 for key in METRIC_KEYS}}
    failed = {'status':'error','building':'b', **{key:0 for key in METRIC_KEYS}}
    summary = summarize_results([perfect,failed,failed,failed])
    for key in METRIC_KEYS:
        assert summary[key] == .25
        assert summary['building_macro'][key] == .5
    invalid = summarize_results([perfect, {'status':'gold_error','building':'a'}])
    assert not invalid['valid'] and invalid['gold_errors'] == 1
    assert all(invalid[key] is None for key in METRIC_KEYS)


def test_web_evaluation_uses_all_three_metrics_and_persists_report(tiny_agent, monkeypatch, tmp_path):
    tiny_agent.use_decomposer = True
    tiny_agent.decomposer = brick_decomposer.BrickQueryDecomposer()
    def run(question, **kwargs):
        assert tiny_agent.language == 'en' and kwargs == {'verbose':False}
        assert not tiny_agent.use_temporal_handler and not tiny_agent.use_aggregation
        if question == 'model failure':
            raise RuntimeError('Offline model failure')
        state = AgentState(question, language='en')
        state.actions.append(BrickAction('Finished', 'stop', ''))
        tiny_agent._current_state = state
        return state, BrickSparqlQuery('SELECT ?x WHERE {}', execution_result=[{'x':'A'}],
                                      bindings=[{'x': {'type':'literal', 'value':'A'}}],
                                      execution_status=SparqlExecutionStatus.SUCCESS)
    monkeypatch.setattr(tiny_agent, 'run', run)
    benchmark = tmp_path / 'benchmark.jsonl'
    gold = 'SELECT ?x WHERE { VALUES ?x { "A" "B" } }'
    benchmark.write_text('\n'.join(json.dumps({'question':q,'gold_sparql':gold}) for q in ('partial answer','model failure')), encoding='utf-8')
    app.eval_tasks['test'] = {'status':'running','results':[],'summary':{},'error':None}
    app._run_eval('test', str(benchmark), 0, 'en')
    report = app.eval_tasks['test']
    assert report['status'] == 'done'
    assert report['configuration']['experiment'] == 'buildingqa'
    assert report['configuration']['decomposition_policy']['prompt_variant'] == 'sensors_only'
    assert all(not row['decomposition_policy']['temporal'] and not row['decomposition_policy']['operations']
               for row in report['results'])
    assert report['metric_reference']['sha256'] == 'd7d982fe1f9eaa020d00615ec8ab48ed6f0b6117cd4963a53f8e39473447010b'
    assert report['summary']['model_errors'] == 1
    for key in METRIC_KEYS:
        assert report['summary'][key] == pytest.approx(1/3)
        assert report['results'][0][key] == pytest.approx(2/3)
        assert report['results'][1][key] == 0
    assert json.loads(Path(report['report_path']).read_text(encoding='utf-8'))['summary'] == report['summary']
    client = TestClient(app.app)
    assert client.get('/api/eval_task/test/export').status_code == 200
    assert client.post('/api/evaluate', json={'language':'fr'}).status_code == 422


def test_gold_error_is_not_a_model_zero_or_success(tiny_agent, monkeypatch):
    def should_not_run(*args, **kwargs):
        pytest.fail('Model must not be called when gold cannot execute')
    monkeypatch.setattr(tiny_agent, 'run', should_not_run)
    row = evaluate_question(tiny_agent, {'question':'anything','gold_sparql':'SELECT {'})
    assert row['status'] == 'gold_error'
    assert all(row[key] is None for key in METRIC_KEYS)


def test_language_reaches_api_task_and_english_examples(tiny_agent, monkeypatch):
    client = TestClient(app.app)
    examples = client.get('/api/examples?language=en').json()['questions']
    assert examples and all(not re.search('[一-鿿]', q) for q in examples)
    monkeypatch.setattr(tiny_agent, 'controller', lambda state: BrickAction('Retrieve', 'execute_sparql', 'SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }') if not state.actions else BrickAction('Finish','stop',''))
    response = client.post('/api/ask', json={'question':'What temperature sensors are in the building?', 'language':'en'})
    assert response.status_code == 200
    import time
    for _ in range(100):
        data = client.get('/api/task/' + response.json()['task_id']).json()
        if data['status'] != 'running':
            break
        time.sleep(.01)
    assert data['status'] == 'done' and data['language'] == 'en'
    assert data['final_sparql']['num_results'] == 1
    assert client.post('/api/ask', json={'question':'test','language':'fr'}).status_code == 422


@pytest.mark.parametrize('display_language', ['zh', 'en'])
def test_cli_reports_three_official_metrics_and_retains_model_failures(monkeypatch, tmp_path, display_language):
    import evaluate
    benchmark = tmp_path / 'questions.jsonl'
    target = tmp_path / 'report.json'
    benchmark.write_text('\n'.join(json.dumps({'question':q}) for q in ('partial', 'failed')), encoding='utf-8')
    def fake_item(item, args):
        assert args.language == display_language
        failed = item['question'] == 'failed'
        return {'question':item['question'], 'building':'test', 'status':'error' if failed else 'done',
                **{key:0.0 if failed else 2/3 for key in METRIC_KEYS}}
    monkeypatch.setattr(evaluate, 'evaluate_item', fake_item)
    monkeypatch.setattr('sys.argv', ['evaluate.py','--benchmark',str(benchmark),'--language',display_language,'--report',str(target),'--workers','1'])
    evaluate.main()
    report = json.loads(target.read_text(encoding='utf-8'))
    assert report['configuration']['language'] == 'en'
    assert report['configuration']['prompt_language'] == 'en'
    assert report['configuration']['interface_language'] == display_language
    assert report['summary']['model_errors'] == 1
    assert all(report['summary'][key] == pytest.approx(1/3) for key in METRIC_KEYS)


def test_existing_ttl_context_reaches_query_without_changing_execution_graph(tiny_agent, monkeypatch, tmp_path):
    import hashlib
    import time
    selected = tmp_path / 'building_sample_100.ttl'
    content = '# Preserve file order and comments\n@prefix b: <urn:test:> .\nb:context b:label "Only in the prompt" .\n'
    selected.write_bytes(content.encode('utf-8'))
    monkeypatch.setattr(app, '_list_buildings', lambda: ([{'ttl': str(selected)}], []))
    before = set(tiny_agent.brick_graph.source_graph)
    seen = []
    def run(question, **kwargs):
        seen.append(tiny_agent.ttl_schema_content)
        return AgentState(question, language='en'), None
    monkeypatch.setattr(tiny_agent, 'run', run)
    client = TestClient(app.app)
    response = client.post('/api/ask', json={'question':'test','context_ttl':str(selected)})
    assert response.status_code == 200
    for _ in range(100):
        data = client.get('/api/task/' + response.json()['task_id']).json()
        if data['status'] != 'running':
            break
        time.sleep(.01)
    assert seen == [content]
    assert set(tiny_agent.brick_graph.source_graph) == before
    assert data['context_ttl'] == {'file': selected.name, 'sha256': hashlib.sha256(selected.read_bytes()).hexdigest(), 'triples': 1}
    assert client.post('/api/ask', json={'question':'test','context_ttl':str(selected),'context':100}).status_code == 400
    assert client.post('/api/ask', json={'question':'test','context_ttl':str(tmp_path / 'unknown.ttl')}).status_code == 400
    monkeypatch.setitem(app.graph_meta, 'ttl', str(tmp_path / 'other.ttl'))
    assert client.post('/api/ask', json={'question':'test','context_ttl':str(selected)}).status_code == 400


def test_evaluation_uses_snapshot_and_restores_previous_context(tiny_agent, monkeypatch, tmp_path):
    selected = tmp_path / 'building_sample_100.ttl'
    original = '@prefix b: <urn:test:> . b:a b:p b:b .\n'
    selected.write_bytes(original.encode('utf-8'))
    monkeypatch.setattr(app, '_list_buildings', lambda: ([{'ttl': str(selected)}], []))
    snapshot = app._prepare_ttl_context(app.EvalRequest(context_ttl=str(selected)))
    selected.write_text('changed after request', encoding='utf-8')
    tiny_agent.ttl_schema_content = 'previous context'
    tiny_agent.schema_description = 'interactive guide must not reach the benchmark'
    def evaluate(a, item, **kwargs):
        assert a.ttl_schema_content == original
        assert a.schema_description is None
        return {'status':'done','building':'building', **{key:1 for key in METRIC_KEYS}}
    monkeypatch.setattr(app, 'evaluate_question', evaluate)
    benchmark = tmp_path / 'benchmark.jsonl'
    benchmark.write_text(json.dumps({'question':'offline'}), encoding='utf-8')
    app.eval_tasks['snapshot'] = {'status':'running','results':[],'summary':{},'error':None}
    app._run_eval('snapshot', str(benchmark), context_snapshot=snapshot)
    report = app.eval_tasks['snapshot']
    assert report['status'] == 'done'
    assert report['configuration']['context_mode'] == 'existing_ttl'
    assert report['configuration']['context_ttl']['triples'] == 1
    assert Path(report['report_path']).with_name('context.ttl').read_text(encoding='utf-8') == original
    import hashlib
    assert hashlib.sha256(Path(report['report_path']).with_name('context.ttl').read_bytes()).hexdigest() == report['configuration']['context_ttl']['sha256']
    assert tiny_agent.ttl_schema_content == 'previous context'
    assert tiny_agent.schema_description == 'interactive guide must not reach the benchmark'
    assert report['configuration']['schema_description_in_prompt'] is False


def test_evaluation_rejects_wrong_building_before_start(tiny_agent, monkeypatch, tmp_path):
    benchmark = tmp_path / 'wrong.jsonl'
    benchmark.write_text(json.dumps({'question':'test', 'ttl':'other.ttl'}), encoding='utf-8')
    monkeypatch.setattr(tiny_agent, 'run', lambda *a, **k: pytest.fail('Mismatched benchmarks must not call a model'))
    response = TestClient(app.app).post('/api/evaluate', json={'benchmark':str(benchmark)})
    assert response.status_code == 400
    assert '不匹配' in response.json()['detail']
    assert not app._eval_running and not app.eval_tasks


def test_active_evaluation_id_and_live_progress_are_recoverable(tiny_agent, monkeypatch, tmp_path):
    benchmark = tmp_path / 'questions.jsonl'
    benchmark.write_text(json.dumps({'question':'test', 'ttl':app.graph_meta['ttl']}), encoding='utf-8')
    app.eval_tasks['e123'] = {'status':'running', 'results':[], 'summary':{}, 'error':None}
    app._eval_running = True
    client = TestClient(app.app)
    seen = []
    def evaluate(a, item, on_progress, **kwargs):
        on_progress('model')
        a._current_state = AgentState('test', phase='模型正在选择下一步', total_tokens=25)
        response = client.get('/api/eval_task/e123').json()
        seen.append(response['current'])
        assert client.get('/api/status').json()['active_eval_task_id'] == 'e123'
        return {'status':'done', 'building':'building', **{key:1 for key in METRIC_KEYS}}
    monkeypatch.setattr(app, 'evaluate_question', evaluate)
    app._run_eval('e123', str(benchmark))
    assert seen[0]['index'] == 1 and seen[0]['total'] == 1
    assert seen[0]['stage'] == 'model' and seen[0]['tokens'] == 25
    assert seen[0]['elapsed_seconds'] >= 0
    assert app.eval_tasks['e123']['status'] == 'done'
    assert not app._eval_running
    assert client.get('/api/status').json()['active_eval_task_id'] is None


def test_evaluation_initialization_failure_releases_busy_state(tiny_agent, monkeypatch, tmp_path):
    app.eval_tasks['e123'] = {'status':'running', 'results':[], 'summary':{}, 'error':None}
    app._eval_running = True
    monkeypatch.setattr(app, 'method_metadata', lambda *args: (_ for _ in ()).throw(RuntimeError('initialization failed')))
    app._run_eval('e123', str(tmp_path / 'unused.jsonl'))
    assert app.eval_tasks['e123']['status'] == 'error'
    assert app.eval_tasks['e123']['error'] == 'initialization failed'
    assert not app._eval_running


def test_cancel_evaluation_retains_completed_results_and_stops_next_questions(tiny_agent, monkeypatch, tmp_path):
    benchmark = tmp_path / 'questions.jsonl'
    benchmark.write_text('\n'.join(json.dumps({'question':str(i), 'ttl':app.graph_meta['ttl']}) for i in range(3)), encoding='utf-8')
    app.eval_tasks['cancel-test'] = {'status':'running', 'results':[], 'summary':{}, 'error':None}
    app._eval_running = True
    client = TestClient(app.app)
    calls = []
    previous_event = tiny_agent.cancel_event
    def evaluate(a, item, on_progress, cancel_event, **kwargs):
        calls.append(item['question'])
        if len(calls) == 1:
            return {'question':item['question'], 'status':'done', 'building':'building', **{key:1 for key in METRIC_KEYS}}
        on_progress('model')
        assert a.cancel_event is not cancel_event
        assert client.post('/api/eval_task/cancel-test/cancel').json()['cancel_requested']
        assert client.post('/api/eval_task/cancel-test/cancel').json()['cancel_requested']
        assert cancel_event.is_set() and a.cancel_event.is_set() and app._eval_running
        return {'question':item['question'], 'status':'cancelled', **{key:None for key in METRIC_KEYS}}
    monkeypatch.setattr(app, 'evaluate_question', evaluate)
    app._run_eval('cancel-test', str(benchmark))
    run = app.eval_tasks['cancel-test']
    assert calls == ['0','1'] and run['status'] == 'cancelled'
    assert run['summary']['done'] == 1 and run['summary']['total'] == 3
    assert run['summary']['errors'] == 0 and run['summary']['exact_match_f1'] == 1
    assert run['interrupted_question']['status'] == 'cancelled'
    assert tiny_agent.cancel_event is previous_event and not previous_event.is_set()
    assert not app._eval_running and not app._eval_cancel_events
    report = Path(run['report_path'])
    original = report.read_bytes()
    assert json.loads(original)['status'] == 'cancelled'
    assert client.post('/api/eval_task/cancel-test/cancel').json()['status'] == 'cancelled'
    assert report.read_bytes() == original
    assert client.post('/api/eval_task/unknown/cancel').status_code == 404


def test_cancel_during_initialization_does_not_start_first_question(tiny_agent, monkeypatch, tmp_path):
    benchmark = tmp_path / 'questions.jsonl'
    benchmark.write_text(json.dumps({'question':'test', 'ttl':app.graph_meta['ttl']}), encoding='utf-8')
    app.eval_tasks['cancel-early'] = {'status':'running', 'results':[], 'summary':{}, 'error':None}
    app._eval_running = True
    monkeypatch.setattr(tiny_agent, 'set_schema_context', lambda *args: app.cancel_evaluation('cancel-early'))
    monkeypatch.setattr(app, 'evaluate_question', lambda *args, **kwargs: pytest.fail('Cancelled evaluation started a question'))
    app._run_eval('cancel-early', str(benchmark))
    run = app.eval_tasks['cancel-early']
    assert run['status'] == 'cancelled' and run['results'] == []
    assert run['summary']['done'] == 0 and run['summary']['total'] == 1
    assert not app._eval_running


@pytest.mark.parametrize('stage', ['gold', 'model'])
def test_question_cancellation_is_not_scored_as_failure_or_cleared(tiny_agent, monkeypatch, stage):
    import threading
    cancel_event = threading.Event()
    monkeypatch.setattr(tiny_agent, 'run', lambda *args, **kwargs: pytest.fail('Cancelled question reached model'))
    def progress(current):
        if current == stage:
            cancel_event.set()
    row = evaluate_question(tiny_agent, {'question':'test','gold_sparql':'SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }'},
                            cancel_event=cancel_event, on_progress=progress)
    assert cancel_event.is_set() and row['status'] == 'cancelled'
    assert all(row[key] is None for key in METRIC_KEYS)


def test_question_timeout_does_not_cancel_the_whole_evaluation(tiny_agent, monkeypatch):
    import threading
    import evaluation_runner
    requested = threading.Event()
    class ImmediateTimer:
        def __init__(self, timeout, callback):
            self.callback = callback
        def start(self):
            self.callback()
        def cancel(self):
            pass
    monkeypatch.setattr(evaluation_runner.threading, 'Timer', ImmediateTimer)
    def timed_out(*args, **kwargs):
        assert tiny_agent.cancel_event.is_set()
        raise InterruptedError('Question timed out')
    monkeypatch.setattr(tiny_agent, 'run', timed_out)
    item = {'question':'test','gold_sparql':'SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }'}
    row = evaluate_question(tiny_agent, item, timeout=1, cancel_event=requested)
    assert row['status'] == 'error' and not requested.is_set()
    def next_question(*args, **kwargs):
        assert not tiny_agent.cancel_event.is_set()
        raise ValueError('Offline test: next question started')
    monkeypatch.setattr(tiny_agent, 'run', next_question)
    row = evaluate_question(tiny_agent, item, cancel_event=requested)
    assert 'next question started' in row['error'] and not requested.is_set()


@pytest.mark.parametrize('saved_status', ['done', 'running'])
def test_saved_evaluation_is_restored_without_rewriting_or_restarting(tiny_agent, tmp_path, saved_status):
    tid = 'e' + '1' * 32
    target = tmp_path / 'output/evaluations' / tid / 'report.json'
    target.parent.mkdir(parents=True)
    original = json.dumps({'status':saved_status, 'results':[], 'summary':{'total':5, 'done':2, 'entity_set_f1':.2}, 'error':None}).encode('utf-8')
    target.write_bytes(original)
    client = TestClient(app.app)
    response = client.get('/api/eval_task/' + tid)
    assert response.status_code == 200
    data = response.json()
    assert data['restored_from_disk'] is True
    assert data['status'] == ('done' if saved_status == 'done' else 'interrupted')
    assert data['summary']['entity_set_f1'] == .2
    assert client.get('/api/status').json()['active_eval_task_id'] is None
    assert target.read_bytes() == original
    assert client.get('/api/eval_task/' + tid + '/export').content == original


def test_parallel_evaluation_overlaps_and_preserves_question_order(tiny_agent, monkeypatch, tmp_path):
    import threading
    import time
    benchmark = tmp_path / 'parallel.jsonl'
    benchmark.write_text('\n'.join(json.dumps({'question':str(i)}) for i in range(3)), encoding='utf-8')
    tid = 'parallel'
    app.eval_tasks[tid] = {'status':'running','results':[],'summary':{},'error':None}
    app._eval_running = True
    tiny_agent.decomposer = SimpleNamespace(last_usage=None, last_fallback=False)
    gate = threading.Barrier(3)
    last_finished = threading.Event()
    snapshot_ready = threading.Event()
    agents, finish_order, progress = [], [], []
    client = TestClient(app.app)
    def evaluate(a, item, on_progress, **kwargs):
        i = int(item['question'])
        agents.append(a)
        a.decomposer.last_usage = {'total_tokens':i + 10}
        a._current_state = AgentState(item['question'], phase='phase-' + str(i), total_tokens=i + 10)
        on_progress('model')
        gate.wait(timeout=5)
        if i == 0:
            snapshot = client.get('/api/eval_task/' + tid).json()['active_questions']
            progress.extend(snapshot)
            snapshot_ready.set()
            assert last_finished.wait(5)
            time.sleep(.04)
        elif i == 2:
            assert snapshot_ready.wait(5)
            last_finished.set()
        else:
            assert snapshot_ready.wait(5)
            time.sleep(.02)
        finish_order.append(i)
        return {'question':item['question'],'status':'done','building':'building', **{key:i / 2 for key in METRIC_KEYS}}
    monkeypatch.setattr(app, 'evaluate_question', evaluate)
    app._run_eval(tid, str(benchmark), workers=3)
    report = app.eval_tasks[tid]
    assert report['status'] == 'done' and report['configuration']['workers'] == 3
    assert len({id(a) for a in agents}) == len({id(a.cancel_event) for a in agents}) == 3
    assert len({id(a.decomposer) for a in agents}) == len({a.log_file for a in agents}) == 3
    assert all(a.brick_graph is tiny_agent.brick_graph and a is not tiny_agent for a in agents)
    assert tiny_agent.decomposer.last_usage is None
    assert [r['question'] for r in report['results']] == ['0','1','2']
    assert [r['question_index'] for r in report['results']] == [1,2,3]
    assert finish_order[0] != 0
    assert {c['question']:c['phase'] for c in progress} == {str(i):'phase-' + str(i) for i in range(3)}
    assert all(report['summary'][key] == .5 for key in METRIC_KEYS)
    assert not app._eval_running and not app._eval_agents


def test_parallel_cancel_reaches_all_running_questions_and_never_starts_queue(tiny_agent, monkeypatch, tmp_path):
    import threading
    benchmark = tmp_path / 'parallel-cancel.jsonl'
    benchmark.write_text('\n'.join(json.dumps({'question':str(i)}) for i in range(10)), encoding='utf-8')
    tid = 'parallel-cancel'
    app.eval_tasks[tid] = {'status':'running','results':[],'summary':{},'error':None}
    app._eval_running = True
    gate = threading.Barrier(3)
    calls = []
    def evaluate(a, item, on_progress, cancel_event, **kwargs):
        calls.append(item['question'])
        on_progress('model')
        gate.wait(timeout=5)
        if item['question'] == '0':
            assert TestClient(app.app).post('/api/eval_task/' + tid + '/cancel').json()['cancel_requested']
        assert cancel_event.wait(5)
        assert a.cancel_event.wait(5)
        return {'question':item['question'], 'status':'cancelled', **{key:None for key in METRIC_KEYS}}
    monkeypatch.setattr(app, 'evaluate_question', evaluate)
    app._run_eval(tid, str(benchmark), workers=3)
    report = app.eval_tasks[tid]
    assert sorted(calls) == ['0','1','2']
    assert report['status'] == 'cancelled' and report['results'] == []
    assert report['summary']['done'] == 0 and report['summary']['total'] == 10
    assert [r['question_index'] for r in report['interrupted_questions']] == [1,2,3]
    assert not app._eval_running and not app._eval_agents and not app._eval_execution_events


@pytest.mark.parametrize('workers', [0,9,1.5,'3',True])
def test_web_rejects_invalid_concurrency(tiny_agent, workers):
    assert TestClient(app.app).post('/api/evaluate', json={'workers':workers}).status_code == 422


def test_web_defaults_to_three_parallel_questions():
    assert app.EvalRequest().workers == 3


def test_real_agent_parallel_trajectories_and_token_usage_do_not_mix(tiny_agent, monkeypatch, tmp_path):
    import threading
    barrier = threading.Barrier(2)
    clients = threading.local()
    class OfflineController:
        def __init__(self):
            self.calls = 0
            self.last_usage = None
            self.model = 'offline-concurrency'
        def generate_text(self, prompt, **kwargs):
            letter = 'A' if 'QUESTION_A' in prompt else 'B'
            amount = 10 if letter == 'A' else 20
            self.last_usage = {'prompt_tokens':amount,'completion_tokens':1,'total_tokens':amount + 1}
            self.calls += 1
            if self.calls == 1:
                barrier.wait(timeout=5)
                return f'Thought: Retrieve {letter}.\nAction: execute_sparql(SELECT ?x WHERE {{ VALUES ?x {{ "{letter}" }} }})'
            return 'Thought: Finished.\nAction: stop()'
    def get_client():
        if not hasattr(clients, 'client'):
            clients.client = OfflineController()
        return clients.client
    monkeypatch.setattr(llm_client, 'get_client', get_client)
    benchmark = tmp_path / 'agent-parallel.jsonl'
    benchmark.write_text('\n'.join(json.dumps({'question':'QUESTION_' + letter,
                         'gold_sparql':f'SELECT ?x WHERE {{ VALUES ?x {{ "{letter}" }} }}'}) for letter in ['A','B']), encoding='utf-8')
    app.eval_tasks['agent-parallel'] = {'status':'running','results':[],'summary':{},'error':None}
    app._eval_running = True
    app._run_eval('agent-parallel', str(benchmark), workers=2)
    report = app.eval_tasks['agent-parallel']
    assert report['status'] == 'done'
    for row, letter, tokens in zip(report['results'], ['A','B'], [22,42]):
        assert row['status'] == 'done' and row['pred_rows'] == [{'x':letter}]
        assert row['tokens']['total'] == tokens and row['steps'] == 2
        assert all(row[key] == 1 for key in METRIC_KEYS)
        assert Path(row['prompt_log']).is_file()


def test_api_passes_default_concurrency_to_worker(tiny_agent, monkeypatch, tmp_path):
    benchmark = tmp_path / 'start-parallel.jsonl'
    benchmark.write_text(json.dumps({'question':'test'}), encoding='utf-8')
    captured = {}
    class OfflineThread:
        def __init__(self, target, args, **kwargs):
            captured.update(target=target, args=args)
        def start(self):
            captured['started'] = True
    monkeypatch.setattr(app.threading, 'Thread', OfflineThread)
    response = app.start_eval(app.EvalRequest(benchmark=str(benchmark)))
    assert captured['started'] and captured['target'] is app._run_eval
    assert captured['args'][-3:] == (3, 'graphdb', 'brickqa')
    assert captured['args'][0] == response['task_id']


def test_english_exception_feedback_has_no_untranslated_control_messages(tiny_agent, monkeypatch):
    def broken_execute(self):
        raise ValueError('invalid PREFIX declaration')
    monkeypatch.setattr(BrickSparqlQuery, 'execute', broken_execute)
    action, query = tiny_agent.execute_action(BrickAction('Execute the query', 'execute_sparql', 'SELECT * WHERE {}'))
    assert query is None and 'PREFIX error:' in action.observation
    assert not re.search('[一-鿿]', action.observation)
    monkeypatch.setattr('brick_agent.get_property_examples', lambda *args: (_ for _ in ()).throw(RuntimeError('offline failure')))
    action, query = tiny_agent.execute_action(BrickAction('Inspect examples', 'get_property_examples', 'hasPoint'))
    assert action.observation == 'Error executing action: offline failure'


def test_english_feedback_preserves_chinese_rdf_values(tiny_agent, monkeypatch):
    def execute(self):
        self.execution_result = [{'label':'完成'}]
        self.execution_status = SparqlExecutionStatus.SUCCESS
        return self
    monkeypatch.setattr(BrickSparqlQuery, 'execute', execute)
    action, query = tiny_agent.execute_action(BrickAction('Read label', 'execute_sparql', 'SELECT ?label WHERE {}'))
    assert query.execution_result == [{'label':'完成'}]
    assert '完成' in action.observation and 'Done' not in action.observation
    monkeypatch.setattr('brick_agent.get_property_examples', lambda *args: [('urn:a','urn:p','完成')])
    action, query = tiny_agent.execute_action(BrickAction('Read relationship', 'get_property_examples', 'urn:p'))
    assert action.observation == 'urn:a -- urn:p --> 完成'


def test_metric_reference_rejects_a_changed_source(monkeypatch):
    from evaluation_metrics import metric_reference, REFERENCE_SHA256
    import evaluation_metrics
    assert metric_reference()['sha256'] == REFERENCE_SHA256
    monkeypatch.setattr(evaluation_metrics, 'REFERENCE_SHA256', '0' * 64)
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        metric_reference()

@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('temporal,operations', [(False, False), (True, True), (False, True), (True, False)])
def test_module_ablation_changes_actual_prompt_without_changing_question(language, temporal, operations):
    from prompting import build_decomposition_prompt
    question = 'Which sensors recorded a maximum yesterday?'
    prompt = build_decomposition_prompt(question, language, 'Namespaces: urn:test:',
                                         use_temporal=temporal, use_aggregation=operations)
    assert question in prompt and 'Namespaces: urn:test:' in prompt
    if temporal and operations:
        assert prompt == load_prompt('brick_decomposition.prompt', 'en').replace('{{ question }}', question) + '\nGraph context: Namespaces: urn:test:'
    else:
        assert '# Examples' not in prompt and '**Temporal Types:**' not in prompt
        assert ('"temporal"' in prompt) == temporal
        assert ('**Extract Temporal**' in prompt) == temporal
        assert ('"aggregation"' in prompt) == operations
        assert ('**Extract Aggregations**' in prompt) == operations
        assert all(token in prompt for token in ('"sensors"', '"sensor_count"', '"query_intent"'))
    assert not re.search('[一-鿿]', prompt)


def test_disabled_response_fields_are_ignored_before_parsing():
    raw = {'sensors': [], 'temporal': 'invalid disabled field',
           'aggregation': {'required': True, 'operations': ['AVG'], 'conditions': ['secret-condition']}}
    result = brick_decomposer.BrickQueryDecomposer()._json_to_decomposition(
        raw, use_temporal=False, use_aggregation=False)
    assert not result.temporal.has_constraint and result.temporal.type == 'none'
    assert result.temporal.details == {} and result.temporal.sparql_pattern == ''
    assert not result.aggregation.required and result.aggregation.operations == []
    assert result.aggregation.conditions == []
    assert 'temporal' not in result.raw_json and 'aggregation' not in result.raw_json
    assert 'temporal' in raw and 'aggregation' in raw


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('full', [False, True])
def test_agent_module_policy_reaches_decomposer_and_controller(tiny_agent, monkeypatch, language, full):
    from prompting import build_controller_prompt
    prompts = []
    def generate(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({'sensors': [], 'sensor_count': 0, 'query_intent': 'List sensors',
            'temporal': {'has_constraint': True, 'type': 'yesterday', 'details': {'date': '2020-01-01'}},
            'aggregation': {'required': True, 'operations': ['AVG'], 'conditions': ['value > 7']}})
    monkeypatch.setattr(brick_decomposer, 'get_client', lambda: SimpleNamespace(generate_text=generate, last_usage=None))
    tiny_agent.use_decomposer = True
    tiny_agent.decomposer = brick_decomposer.BrickQueryDecomposer()
    tiny_agent.use_temporal_handler = full
    tiny_agent.use_aggregation = full
    tiny_agent.language = language
    tiny_agent.dataset_date_range = 'SENTINEL-TIMESERIES-RANGE'
    monkeypatch.setattr(tiny_agent, 'controller', lambda state: BrickAction('Finished', 'stop', ''))
    state, _ = tiny_agent.run('Which temperature sensors are in each zone?', verbose=False)
    assert len(prompts) == 1 and ('"temporal"' in prompts[0]) == full
    assert ('"aggregation"' in prompts[0]) == full
    assert 'SENTINEL-TIMESERIES-RANGE' not in prompts[0]
    assert 'Graph context:' not in prompts[0]
    assert state.decomposition.temporal.has_constraint == full
    assert state.decomposition.aggregation.required == full
    assert state.decomposition_policy['temporal'] == full
    assert state.decomposition_policy['operations'] == full
    actual_prompt = Path(tiny_agent.decomposer.last_prompt['prompt_file']).read_text(encoding='utf-8')
    assert actual_prompt == prompts[0]
    prompt, guide = build_controller_prompt(tiny_agent, state)
    if not full:
        assert not guide
        assert all(token not in prompt for token in ('SENTINEL-TIMESERIES-RANGE', '- Temporal constraint:',
                                                     '- Aggregation:', '- 时间约束：', '- 聚合：'))
        assert state.decomposition.temporal.details == {} and state.decomposition.aggregation.conditions == []
    else:
        assert 'SENTINEL-TIMESERIES-RANGE' not in prompt and 'AVG' in prompt


def test_parallel_evaluation_fork_preserves_parent_full_modules(tiny_agent):
    from prompting import decomposition_policy
    tiny_agent.use_decomposer = True
    tiny_agent.decomposer = brick_decomposer.BrickQueryDecomposer()
    child = tiny_agent.fork_evaluation()
    assert decomposition_policy(child)['prompt_variant'] == 'sensors_only'
    assert decomposition_policy(tiny_agent)['prompt_variant'] == 'full'
    assert child.decomposer is not tiny_agent.decomposer


@pytest.mark.parametrize('profile,enabled', [('buildingqa', False), ('lbnl_fdd', True)])
def test_cli_explicit_module_profiles(monkeypatch, tmp_path, profile, enabled):
    import main
    import sys
    ttl = tmp_path / 'test.ttl'
    ttl.write_text('', encoding='utf-8')
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(**kwargs, initialize_graph=lambda **kw: None,
                               run=lambda *a, **kw: (None, None))
    monkeypatch.setattr(main, 'BrickAgent', create)
    monkeypatch.setattr(sys, 'argv', ['main.py', '--ttl', str(ttl), '--question', 'List sensors',
                                     '--experiment', profile])
    main.main()
    assert calls[0]['use_decomposer']
    assert calls[0]['use_temporal_handler'] == enabled
    assert calls[0]['use_aggregation'] == enabled


@pytest.mark.parametrize('flag', ['--no-temporal', '--no-decomposer'])
def test_cli_rejects_conflicting_module_profile(monkeypatch, flag):
    import main
    import sys
    monkeypatch.setattr(sys, 'argv', ['main.py', '--ttl', 'unused.ttl', '--experiment', 'lbnl_fdd', flag])
    with pytest.raises(SystemExit) as result:
        main.main()
    assert result.value.code == 2

@pytest.mark.parametrize('full', [False, True])
def test_display_language_does_not_change_any_model_prompt_or_observation(tiny_agent, monkeypatch, full):
    runs = []
    tiny_agent.use_decomposer = True
    tiny_agent.use_temporal_handler = full
    tiny_agent.use_aggregation = full
    tiny_agent.decomposer = brick_decomposer.BrickQueryDecomposer()
    question = 'Which temperature sensors are in each zone?'
    for display in ('zh', 'en'):
        captured = []
        answers = iter([json.dumps({'sensors': [], 'sensor_count': 0, 'query_intent': 'List sensors'}),
            'Thought: Retrieve sensors.\nAction: execute_sparql(SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor })',
            'Thought: Finished.\nAction: stop()'])
        def generate(prompt, **kwargs):
            captured.append(prompt)
            return next(answers)
        client = SimpleNamespace(generate_text=generate, last_usage=None, model='offline-test')
        monkeypatch.setattr(llm_client, 'get_client', lambda: client)
        monkeypatch.setattr(brick_decomposer, 'get_client', lambda: client)
        tiny_agent.language = display
        state, final = tiny_agent.run(question, verbose=False)
        assert state.language == 'en' and state.interface_language == display
        assert state.question == question and final.execution_result
        runs.append((captured, [a.observation for a in state.actions], final.sparql))
    assert runs[0] == runs[1]
    assert len(runs[0][0]) == 3
    assert all(not re.search('[一-鿿]', prompt) for prompt in runs[0][0])


@pytest.mark.parametrize('field', ['language', 'interface_language'])
def test_chinese_display_api_cannot_change_prompt_language(tiny_agent, monkeypatch, field):
    import time
    monkeypatch.setattr(tiny_agent, 'controller', lambda state: BrickAction('Finished', 'stop', ''))
    client = TestClient(app.app)
    response = client.post('/api/ask', json={'question': '保留这个问题原文', field: 'zh'})
    assert response.status_code == 200
    for _ in range(100):
        row = client.get('/api/task/' + response.json()['task_id']).json()
        if row['status'] != 'running':
            break
        time.sleep(.01)
    assert row['language'] == row['prompt_language'] == 'en'
    assert row['interface_language'] == 'zh' and row['question'] == '保留这个问题原文'
    assert client.post('/api/ask', json={'question': 'test', 'prompt_language': 'zh'}).status_code == 422
    assert client.post('/api/evaluate', json={'prompt_language': 'zh'}).status_code == 422
    assert client.get('/api/status').json()['prompt_language'] == 'en'


def test_example_display_labels_share_identical_model_questions(tiny_agent):
    client = TestClient(app.app)
    zh = client.get('/api/examples?language=zh').json()
    en = client.get('/api/examples?language=en').json()
    assert zh['questions'] != en['questions']
    assert zh['model_questions'] == en['model_questions'] == en['questions']
    assert len(zh['questions']) == len(zh['model_questions'])


def test_chinese_evaluation_display_is_recorded_separately(tiny_agent, monkeypatch, tmp_path):
    tiny_agent.use_decomposer = True
    tiny_agent.decomposer = brick_decomposer.BrickQueryDecomposer()
    before = tiny_agent.interface_language
    benchmark = tmp_path / 'display.jsonl'
    benchmark.write_text(json.dumps({'question': 'List sensors'}), encoding='utf-8')
    seen = []
    def evaluate(agent, item, **kwargs):
        seen.append((agent.language, agent.interface_language))
        return {'question':item['question'], 'status':'done', 'building':'test', **{k:1 for k in METRIC_KEYS}}
    monkeypatch.setattr(app, 'evaluate_question', evaluate)
    app.eval_tasks['display'] = {'status':'running','results':[],'summary':{},'error':None}
    app._run_eval('display', str(benchmark), language='zh', workers=2)
    report = app.eval_tasks['display']
    assert seen == [('en', 'zh')]
    assert report['configuration']['language'] == report['configuration']['prompt_language'] == 'en'
    assert report['configuration']['interface_language'] == 'zh'
    assert tiny_agent.interface_language == before
