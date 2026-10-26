"""Full typed results remain available for scoring, outside Critic feedback."""
import json
import pytest
from rdflib import Graph
from brick_utils import query_graph, SparqlExecutionStatus
from sparql_worker import isolated_query_session
from test_language_and_metrics import tiny_agent
from test_react_baseline import raw_execution, scripted_client, WRITER, CRITIC
from react_baseline import ReActBaselineAgent
from evaluation_runner import evaluate_question
from evaluation_metrics import METRIC_KEYS


@pytest.mark.parametrize('isolated', [False, True])
def test_worker_preserves_real_term_types_and_unbound_columns(isolated):
    query='''SELECT ?iri ?number ?label ?blank ?missing WHERE {
      VALUES (?iri ?number ?label) { (<urn:preview> 12 "中文"@zh) }
      BIND(BNODE("preview") AS ?blank)
      OPTIONAL { ?iri <urn:absent> ?missing }
    }'''
    with isolated_query_session():
        data,status,error=query_graph(query,graph=Graph(),isolated=isolated,prepare_prefixes=False)
    assert error is None and status is SparqlExecutionStatus.SUCCESS
    assert data['vars']==['iri','number','label','blank','missing']
    binding=data['bindings_preview'][0]
    assert binding['iri']=={'type':'uri','value':'urn:preview'}
    assert binding['number']=={'type':'literal','value':'12','datatype':'http://www.w3.org/2001/XMLSchema#integer'}
    assert binding['label']=={'type':'literal','value':'中文','xml:lang':'zh'}
    assert binding['blank']['type']=='bnode'
    assert 'missing' not in binding and data['rows'][0]['missing'] is None


def test_critic_receives_only_row_count_but_scoring_uses_all_rows(tiny_agent,monkeypatch,raw_execution):
    query='SELECT ?x WHERE { VALUES ?x { '+ ' '.join(str(n) for n in range(15)) +' } } ORDER BY ?x'
    _,requests=scripted_client(monkeypatch,[WRITER(query),CRITIC()])
    row=evaluate_question(ReActBaselineAgent(tiny_agent, backend='rdflib'),{'question':'List values','gold_sparql':query})
    assert row['gold_count']==row['pred_count']==15
    assert all(row[key]==1 for key in METRIC_KEYS)
    summary=requests[1][0][1]['content'].split('Execution Results Summary:\n',1)[1]
    assert summary=='Query executed successfully on local graph. Found 15 results.'


def test_preview_cap_never_truncates_execution_rows():
    query='SELECT ?x WHERE { VALUES ?x { '+ ' '.join(str(n) for n in range(15)) +' } } ORDER BY ?x'
    with isolated_query_session():
        data,_,error=query_graph(query,graph=Graph(),prepare_prefixes=False)
    assert error is None and len(data['rows'])==15 and data['total']==15
    assert len(data['bindings_preview'])==10


@pytest.mark.parametrize('isolated', [False, True])
def test_full_typed_bindings_are_opt_in_and_never_capped(isolated):
    query='SELECT ?x WHERE { VALUES ?x { '+ ' '.join(str(n) for n in range(15)) +' } } ORDER BY ?x'
    with isolated_query_session():
        data,_,error=query_graph(query,graph=Graph(),isolated=isolated,prepare_prefixes=False,include_bindings=True)
        ordinary,_,_=query_graph(query,graph=Graph(),isolated=isolated,prepare_prefixes=False)
    assert error is None and len(data['bindings'])==15
    assert [row['x']['value'] for row in data['bindings']]==[str(n) for n in range(15)]
    assert data['bindings_preview']==data['bindings'][:10]
    assert 'bindings' not in ordinary


@pytest.mark.parametrize('query', [
    'SELECT ?x ?unbound WHERE { VALUES ?x { 12 } }',
    'SELECT ?x WHERE { VALUES ?x { "A" } FILTER(false) }',
    'SELECT {',
    'ASK { ?s ?p ?o }',
])
def test_structured_execution_matches_user_document(tiny_agent, raw_execution, query):
    import ast
    import __future__
    from pathlib import Path
    from rdflib import URIRef, Literal, BNode
    from pyparsing import ParseException
    source=Path(__file__).resolve().parents[1]/'third_party/user_react_baseline/sparql_refinement_agent.py'
    tree=ast.parse(source.read_bytes())
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='SparqlRefinementAgent')
    methods=[node for node in cls.body if isinstance(node,ast.FunctionDef)
             and node.name in ('_format_rdflib_results','_run_sparql_query')]
    namespace={'URIRef':URIRef,'Literal':Literal,'BNode':BNode,'ParseException':ParseException}
    exec(compile(ast.Module(body=methods,type_ignores=[]),'provided-reference-query','exec',
                 flags=__future__.annotations.compiler_flag),namespace)
    from types import SimpleNamespace
    oracle=SimpleNamespace(is_remote=False,graph=tiny_agent.brick_graph.source_graph)
    oracle._format_rdflib_results=lambda result:namespace['_format_rdflib_results'](oracle,result)
    expected=namespace['_run_sparql_query'](oracle,query)
    _,actual=ReActBaselineAgent(tiny_agent, backend='rdflib')._run_sparql_query(query)
    assert actual==expected


def test_both_gold_and_predictions_use_document_source_graph(tiny_agent,monkeypatch,raw_execution):
    from rdflib import URIRef
    from rdflib.namespace import RDF
    from brick_utils import BRICK
    tiny_agent.brick_graph.get_graph().add((URIRef('urn:merged-only'),RDF.type,BRICK.Zone_Air_Temperature_Sensor))
    query='SELECT ?s WHERE { ?s a brick:Zone_Air_Temperature_Sensor }'
    scripted_client(monkeypatch,[WRITER(query),CRITIC()])
    agent=ReActBaselineAgent(tiny_agent, backend='rdflib')
    row=evaluate_question(agent,{'question':'List sensors','gold_sparql':query})
    assert row['gold_count']==row['pred_count']==1
    assert all(row[key]==1 for key in METRIC_KEYS)
    assert row['gt_num_cols']==row['gen_num_cols']==1
    assert row['syntax_ok'] and row['returns_results'] and row['perfect_match']
    assert row['arity_matching_f1']==1 and not row['less_columns_flag']
    assert row['gold_bindings']==row['pred_bindings']
    assert agent.evaluation_graph is tiny_agent.brick_graph.source_graph
    assert (URIRef('urn:merged-only'),RDF.type,BRICK.Zone_Air_Temperature_Sensor) in tiny_agent.brick_graph.get_graph()


def test_empty_result_keeps_declared_column_count(tiny_agent,monkeypatch,raw_execution):
    gold='SELECT ?a ?b WHERE { VALUES (?a ?b) { ("A" "B") } }'
    pred='SELECT ?a WHERE { VALUES ?a { "A" } FILTER(?a = "B") }'
    scripted_client(monkeypatch,[WRITER(pred),CRITIC()])
    row=evaluate_question(ReActBaselineAgent(tiny_agent, backend='rdflib'),{'question':'List values','gold_sparql':gold})
    assert row['syntax_ok'] and not row['returns_results']
    assert row['gen_num_rows']==0 and row['gen_num_cols']==1 and row['gt_num_cols']==2
    assert row['less_columns_flag'] and row['arity_matching_f1']==pytest.approx(2/3)


def test_missing_document_graph_does_not_fall_back_to_workbench_graph(tiny_agent):
    agent=ReActBaselineAgent(tiny_agent, backend='rdflib')
    agent.evaluation_graph=None
    _,result=agent._run_sparql_query('SELECT ?s WHERE { ?s ?p ?o }')
    assert result=={'summary_string':'SPARQL query failed: The local RDF graph is not loaded.',
                    'results':[], 'row_count':0, 'col_count':0, 'syntax_ok':False,
                    'error_message':'Graph not loaded.'}


def test_rdflib_error_text_is_not_translated_for_critic(tiny_agent, monkeypatch, raw_execution):
    # A quoted data value can coincide with a controlled UI translation key.
    # The original local branch sends str(e) without any substitutions.
    message = 'Unknown term: 未找到结果。'
    def fail(*args, **kwargs):
        raise ValueError(message)
    monkeypatch.setattr(tiny_agent.brick_graph.source_graph, 'query', fail)
    _, result = ReActBaselineAgent(tiny_agent, backend='rdflib')._run_sparql_query('SELECT ?x WHERE {}')
    assert result['error_message'] == message
    assert result['summary_string'] == 'The query failed to parse with the following error: ' + message


def test_reference_scorer_receives_full_typed_bindings(tiny_agent, monkeypatch, raw_execution):
    import evaluation_runner
    from third_party.buildingqa.metrics import get_entity_and_row_matching_f1, get_exact_match_f1
    query = 'SELECT ?n ?label ?missing WHERE { VALUES (?n ?label) { (12 "中文"@zh) (12 "中文"@zh) } }'
    scripted_client(monkeypatch, [WRITER(query), CRITIC()])
    score = evaluation_runner.score_rows
    received = []
    def capture(gold, pred):
        received.append((gold, pred))
        return score(gold, pred)
    monkeypatch.setattr(evaluation_runner, 'score_rows', capture)
    row = evaluate_question(ReActBaselineAgent(tiny_agent, backend='rdflib'), {'question':'List values', 'gold_sparql':query})
    assert row['status'] == 'done'
    gold, pred = received[0]
    assert gold == row['gold_bindings'] and pred == row['pred_bindings']
    assert len(pred) == 2 and 'missing' not in pred[0]
    assert pred[0]['n']['datatype'].endswith('#integer')
    assert pred[0]['label']['xml:lang'] == 'zh'
    expected = get_entity_and_row_matching_f1(gold, pred)
    expected['exact_match_f1'] = get_exact_match_f1(gold, pred)
    assert {key:row[key] for key in METRIC_KEYS} == expected
