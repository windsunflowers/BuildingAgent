"""Offline checks against the executable pinned BuildingQA ReAct workflow."""
import ast
import __future__
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app
import brick_utils
import llm_client
import react_baseline
import react_reference
from evaluation_methods import evaluation_agent, method_metadata
from evaluation_metrics import METRIC_KEYS, to_bindings
from evaluation_runner import evaluate_question
from react_baseline import ReActBaselineAgent, ReActSparqlQuery, SparqlQuery, QueryCritique
from test_language_and_metrics import tiny_agent

ROOT = Path(__file__).resolve().parents[1]
QUERY = 'SELECT ?x WHERE { VALUES ?x { "A" } }'
WRITER = lambda query=QUERY: json.dumps({'sparql_query': query})
CRITIC = lambda decision='FINAL', feedback='Approved': json.dumps({'decision':decision, 'feedback':feedback})


@pytest.fixture
def raw_execution(monkeypatch):
    execute = ReActSparqlQuery.execute
    monkeypatch.setattr(ReActSparqlQuery, 'execute', lambda self, isolated=True: execute(self, isolated=False))


def scripted_client(monkeypatch, responses):
    remaining = iter(responses)
    requests = []
    client = SimpleNamespace(model='same-selected-model', provider='same-provider', base_url='https://example.com/v1',
        api_key='offline-private-key', last_usage={'prompt_tokens':7,'completion_tokens':3,'total_tokens':10},
        last_response_model='same-selected-model')
    def generate(messages, **kwargs):
        requests.append((deepcopy(messages), kwargs))
        result = next(remaining)
        if isinstance(result, Exception):
            raise result
        return result
    client.generate_messages = generate
    monkeypatch.setattr(react_baseline, 'get_client', lambda: client)
    return client, requests


def original_workflow(source, responses):
    """Execute only the reviewed reference loop with offline model/SQL seams."""
    tree = ast.parse((react_reference.ROOT / 'sparql_refinement_agent.py').read_bytes())
    method = next(m for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='SparqlRefinementAgent'
                  for m in c.body if isinstance(m,ast.FunctionDef) and m.name=='refine_and_evaluate_query')
    namespace={'json':json,'os':os,'SparqlQuery':SparqlQuery,'QueryCritique':QueryCritique,
        'get_arity_matching_f1':lambda *a:0,'get_exact_match_f1':lambda **kw:0,
        'get_entity_and_row_matching_f1':lambda **kw:{'entity_set_f1':0,'row_matching_f1':0}}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'pinned-reference-loop','exec',
                 flags=__future__.annotations.compiler_flag), namespace)
    remaining=iter(responses)
    requests=[]
    def call(messages, cls):
        requests.append(deepcopy(messages))
        response=next(remaining)
        if isinstance(response,Exception):
            return None
        try:
            return cls.model_validate_json(response)
        except Exception:
            return None
    def execute(query):
        result, summary=source._run_sparql_query(query)
        return {**summary, 'results':to_bindings(result.execution_result), 'row_count':len(result.execution_result),
                'col_count':len(result.execution_result[0]) if result.execution_result else 0,
                'syntax_ok':result.error is None,'error_message':result.error}
    oracle=SimpleNamespace(max_iterations=3,prompt_tokens=0,completion_tokens=0,total_tokens=0,
                           _get_structured_response=call,_run_sparql_query=execute,model_name='same-selected-model')
    logger=SimpleNamespace(filename='offline.csv',log=Mock())
    source._current_state=react_baseline.ReActState('List values')
    namespace['refine_and_evaluate_query'](oracle, {'question':'List values','ground_truth_sparql':QUERY,'query_id':'offline'},
                                          logger,'unused prefixes',source.ttl_schema_content or '')
    return requests, logger


@pytest.mark.parametrize('responses', [
    [WRITER(),CRITIC()],
    [WRITER('BAD QUERY'),CRITIC('IMPROVE','Fix syntax'),WRITER(),CRITIC()],
    [WRITER(),'{"invalid":true}'],
    [WRITER(),CRITIC('IMPROVE','Change query'),'not json'],
    [WRITER(),CRITIC('IMPROVE','Again')]*3,
    [WRITER(),CRITIC('IMPROVE','Again'),RuntimeError('offline transport failure')],
])
def test_messages_and_final_selection_match_executable_original(tiny_agent, monkeypatch, raw_execution, responses):
    tiny_agent.ttl_schema_content='# Frozen shared context\n<urn:s> <urn:p> <urn:o> .'
    agent=ReActBaselineAgent(tiny_agent, backend='rdflib')
    expected, logger=original_workflow(agent,responses)
    client, requests=scripted_client(monkeypatch,responses)
    state, final=agent.run('List values')
    assert [request[0] for request in requests]==expected
    assert final.sparql==logger.log.call_args.args[0]['generated_sparql']
    assert state.react_iterations<=3 and state.decomposition is None
    assert all(options['temperature']==0 and options['response_format']=={'type':'json_object'}
               and options['max_retries']==1 and options['sdk_max_retries']==2 and 'max_tokens' not in options for _,options in requests)
    assert state.model_configuration['model']==client.model and state.response_models==[client.model]
    assert state.total_tokens==len(requests)*10
    events=[json.loads(line) for line in Path(agent.log_file).read_text(encoding='utf-8').splitlines()]
    snapshots=[e for e in events if e['event']=='model_request']
    assert len(snapshots)==len(expected)
    for event, messages in zip(snapshots,expected):
        raw=Path(event['prompt_file']).read_bytes()
        assert json.loads(raw)==messages and hashlib.sha256(raw).hexdigest()==event['prompt_sha256']


def test_nokg_has_no_graph_tools_decomposition_or_gold_leakage(tiny_agent, monkeypatch, raw_execution):
    agent=ReActBaselineAgent(tiny_agent, backend='rdflib')
    _,requests=scripted_client(monkeypatch,[WRITER(),CRITIC()])
    gold='SELECT ?x WHERE { VALUES ?x { "A" } FILTER("GOLD_SENTINEL"="GOLD_SENTINEL") }'
    row=evaluate_question(agent,{'question':'List values','gold_sparql':gold})
    assert row['status']=='done' and all(row[k]==1 for k in METRIC_KEYS)
    joined=json.dumps([m for m,_ in requests])
    assert all(token not in joined for token in ('GOLD_SENTINEL','search_brick','get_brick_entity','Namespaces:', 'Query Decomposition'))
    assert '```turtle\n\n```' in requests[0][0][0]['content']
    assert row['method']=='react' and row['mode']=='react' and not row['decomposition_policy']['sensors']
    assert row['baseline_reference']['max_iterations']==3


@pytest.mark.parametrize('phase', ['writer','critic'])
def test_invalid_initial_model_response_has_explicit_failure(tiny_agent, monkeypatch, raw_execution, phase):
    agent=ReActBaselineAgent(tiny_agent, backend='rdflib')
    scripted_client(monkeypatch,['bad json'] if phase=='writer' else [WRITER(),'bad json'])
    row=evaluate_question(agent,{'question':'List values','gold_sparql':QUERY})
    assert row['stop_reason']==phase+'_failure' and row['model_diagnostics'][0]['role']==phase
    if phase=='writer':
        assert row['status']=='error' and all(row[k]==0 for k in METRIC_KEYS)
    else:
        assert row['status']=='done' and all(row[k]==1 for k in METRIC_KEYS)


def test_raw_query_does_not_repair_wrong_prefix_or_semicolon(tiny_agent, raw_execution):
    query='PREFIX brick: <urn:wrong:> SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }'
    agent=ReActBaselineAgent(tiny_agent, backend='rdflib')
    result, summary=agent._run_sparql_query(query)
    assert result.sparql==query and result.execution_result==[]
    assert summary['summary_string']=='The query executed successfully on the local graph but returned no results.'
    broken,summary=agent._run_sparql_query(QUERY+';')
    assert broken.error and 'failed to parse' in summary['summary_string']
    assert broken.sparql.endswith(';')


def test_reference_local_ask_formatter_failure_is_preserved(tiny_agent, raw_execution):
    result,_=ReActBaselineAgent(tiny_agent, backend='rdflib')._run_sparql_query('ASK { }')
    assert result.error=="'NoneType' object is not iterable"


def test_critic_gets_author_row_count_without_result_values(tiny_agent, monkeypatch, raw_execution):
    from rdflib import URIRef, Literal
    tiny_agent.brick_graph.source_graph.add((URIRef('urn:preview'),URIRef('urn:p'),Literal('PRIVATE_RESULT_SENTINEL')))
    _, requests=scripted_client(monkeypatch,[WRITER('SELECT ?x WHERE { <urn:preview> <urn:p> ?x }'),CRITIC()])
    ReActBaselineAgent(tiny_agent, backend='rdflib').run('List values')
    critique=requests[1][0][1]['content']
    assert 'Query executed successfully on local graph. Found 1 results.' in critique
    assert 'Columns:' not in critique and '"type": "literal"' not in critique
    assert 'PRIVATE_RESULT_SENTINEL' not in critique


def test_cancellation_does_not_trigger_more_model_calls(tiny_agent, monkeypatch, raw_execution):
    agent=ReActBaselineAgent(tiny_agent, backend='rdflib')
    _, requests=scripted_client(monkeypatch,[WRITER(),CRITIC()])
    agent.cancel_event.set()
    with pytest.raises(RuntimeError,match='cancelled'):
        agent.run('List values')
    assert not requests


def test_forks_share_context_but_not_run_state_and_logs(tiny_agent):
    tiny_agent.ttl_schema_content='exact context'
    root=ReActBaselineAgent(tiny_agent, backend='rdflib')
    first,second=root.fork_evaluation(),root.fork_evaluation()
    assert first.brick_graph is second.brick_graph is root.brick_graph
    assert first.ttl_schema_content==second.ttl_schema_content=='exact context'
    assert first.cancel_event is not second.cancel_event
    assert first.log_file!=second.log_file!=root.log_file
    assert tiny_agent.decomposer is None and root.use_decomposer is False


def test_message_client_preserves_roles_json_mode_and_selected_model(monkeypatch):
    client=llm_client.LLMClient.__new__(llm_client.LLMClient)
    client.model='selected-model'; client.api_key='offline'; client.base_url='https://example.com'
    create=Mock(return_value=SimpleNamespace(model='selected-model',usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"decision":"FINAL","feedback":"OK"}'))]))
    client.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    messages=[{'role':'system','content':'Original system'},{'role':'user','content':'Original question'}]
    client.generate_messages(messages,response_format={'type':'json_object'})
    assert create.call_args.kwargs=={'model':'selected-model','messages':messages,'temperature':0.0,'response_format':{'type':'json_object'}}


def test_web_react_evaluation_uses_same_official_scores_and_metadata(tiny_agent, monkeypatch, tmp_path, raw_execution):
    _, requests=scripted_client(monkeypatch,[WRITER(),CRITIC()])
    benchmark=tmp_path/'react.jsonl'
    benchmark.write_text(json.dumps({'question':'List values','gold_sparql':QUERY}),encoding='utf-8')
    app.eval_tasks['react-web']={'status':'running','results':[],'summary':{},'error':None}
    app._run_eval('react-web',str(benchmark),workers=2,method='react',react_backend='rdflib')
    report=app.eval_tasks['react-web']
    assert report['status']=='done' and report['configuration']['method']=='react'
    assert report['configuration']['mode']=='react' and report['configuration']['baseline_reference']['max_iterations']==3
    assert report['configuration']['implementation_mode']=='buildingqa_react_rdflib_author_v1'
    assert not report['configuration']['decomposition_policy']['sensors']
    assert all(report['summary'][key]==1 for key in METRIC_KEYS)
    assert len(requests)==2 and report['results'][0]['method']=='react'
    assert report['results'][0]['prompt_language']=='en'
    assert report['results'][0]['implementation_mode']=='buildingqa_react_rdflib_author_v1'


def test_api_accepts_only_explicit_baselines(tiny_agent, monkeypatch, tmp_path):
    captured=[]
    class OfflineThread:
        def __init__(self, target,args,**kwargs): captured.append(args)
        def start(self): pass
    benchmark=tmp_path/'react-api.jsonl'; benchmark.write_text(json.dumps({'question':'test'}),encoding='utf-8')
    monkeypatch.setattr(app.threading,'Thread',OfflineThread)
    response=TestClient(app.app).post('/api/evaluate',json={'benchmark':str(benchmark),'method':'react','react_backend':'rdflib'})
    assert response.status_code==200 and captured[-1][-1]=='react'
    assert TestClient(app.app).post('/api/evaluate',json={'method':'local_fix'}).status_code==422


def test_vendored_react_sources_and_runner_setting_are_pinned():
    manifest=json.loads((react_reference.ROOT/'source_manifest.json').read_text(encoding='utf-8'))
    for name, entry in manifest['files'].items():
        assert hashlib.sha256((react_reference.ROOT/name).read_bytes()).hexdigest()==entry['sha256']
    notebook=json.loads((react_reference.ROOT/'ReAct_demo.ipynb').read_text(encoding='utf-8'))
    cells='\n'.join(''.join(c.get('source',[])) for c in notebook['cells'] if c['cell_type']=='code')
    assert 'max_iterations=3' in cells and react_reference.MAX_ITERATIONS==3
    assert method_metadata('react')['upstream_commit']==manifest['commit']


def test_cli_react_records_baseline_and_does_not_call_model_for_invalid_gold(tmp_path):
    import subprocess
    benchmark=tmp_path/'invalid.jsonl'
    ttl=tmp_path/'tiny.ttl'
    report=tmp_path/'report.json'
    ttl.write_text('<urn:s> <urn:p> <urn:o> .',encoding='utf-8')
    benchmark.write_text(json.dumps({'question':'Do not call model','ttl':str(ttl),'gold_sparql':'SELECT {'}),encoding='utf-8')
    run=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'evaluate.py','--method','react','--react-backend','rdflib',
        '--benchmark',str(benchmark),'--report',str(report),'--workers','1'],cwd=ROOT,capture_output=True,timeout=60)
    assert run.returncode==0,run.stderr.decode(errors='replace')
    data=json.loads(report.read_text(encoding='utf-8'))
    assert data['configuration']['method']=='react' and data['configuration']['baseline_reference']['max_iterations']==3
    assert data['results'][0]['status']=='gold_error' and data['results'][0]['method']=='react'
    assert data['summary']['gold_errors']==1
    assert not data['results'][0].get('model_configuration')


def test_reference_integrity_failure_does_not_run_modified_prompt(monkeypatch,tmp_path):
    (tmp_path/'sparql_refinement_agent.py').write_text('raise RuntimeError("do not execute")',encoding='utf-8')
    react_reference._expressions.cache_clear()
    monkeypatch.setattr(react_reference,'ROOT',tmp_path)
    try:
        with pytest.raises(RuntimeError,match='hash mismatch'):
            react_reference.reference()
    finally:
        react_reference._expressions.cache_clear()


def test_query_failure_is_scored_by_same_official_metrics(tiny_agent,monkeypatch,raw_execution):
    agent=ReActBaselineAgent(tiny_agent, backend='rdflib')
    scripted_client(monkeypatch,[WRITER('BAD QUERY'),CRITIC()])
    row=evaluate_question(agent,{'question':'List values','gold_sparql':QUERY})
    assert row['status']=='error' and row['stop_reason']=='critic_final'
    assert row['execution_error'] and all(row[key]==0 for key in METRIC_KEYS)


def test_same_model_credentials_registry_is_used_by_both_methods():
    # Import binding is the shared production client; no separate key/model path.
    assert react_baseline.get_client is llm_client.get_client
    assert evaluation_agent.__module__=='evaluation_methods'


@pytest.mark.parametrize('query', [
    'SELECT ?x WHERE { VALUES ?x { "A" "B" } }',
    'SELECT ?x WHERE { VALUES ?x { "A" } FILTER(false) }',
    'SELECT ?x ?unbound WHERE { VALUES ?x { 12 } }',
    'SELECT {',
    'ASK { ?s ?p ?o }',
])
def test_execution_summary_matches_independent_upstream_local_executor(tiny_agent, raw_execution, query):
    from rdflib import URIRef, Literal, BNode
    from pyparsing import ParseException
    tree=ast.parse((react_reference.ROOT/'sparql_refinement_agent.py').read_bytes())
    cls=next(c for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='SparqlRefinementAgent')
    methods=[m for m in cls.body if isinstance(m,ast.FunctionDef)
             and m.name in ('_format_rdflib_results','_run_sparql_query')]
    namespace={'URIRef':URIRef,'Literal':Literal,'BNode':BNode,'ParseException':ParseException}
    exec(compile(ast.Module(body=methods,type_ignores=[]),'pinned-local-execution','exec',
                 flags=__future__.annotations.compiler_flag),namespace)
    oracle=SimpleNamespace(is_remote=False,graph=tiny_agent.brick_graph.source_graph)
    oracle._format_rdflib_results=lambda result:namespace['_format_rdflib_results'](oracle,result)
    expected=namespace['_run_sparql_query'](oracle,query)
    result,actual=ReActBaselineAgent(tiny_agent, backend='rdflib')._run_sparql_query(query)
    assert len(result.execution_result)==expected['row_count']
    assert actual==expected


def test_reference_metadata_distinguishes_local_branch_from_paper_backend():
    metadata=react_reference.reference('rdflib')
    assert metadata['alignment_target']=='BuildingQA_RDFLib_branch'
    assert metadata['feedback_policy']=='upstream_rdflib_row_count_only_v1'
    assert metadata['critic_result_preview_limit']==0 and metadata['critic_receives_columns'] is False
    assert metadata['notebook_default_execution_mode']=='remote_GraphDB'
    assert metadata['critic_receives_ttl_context'] is False
    assert metadata['paper_environment_verified'] is False
