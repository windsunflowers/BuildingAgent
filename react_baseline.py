"""BuildingQA's writer/critic baseline, independent of BrickQA planning/tools."""
from copy import copy
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from uuid import uuid4

from pydantic import BaseModel, Field
from brick_agent import AgentState, BrickSparqlQuery
from brick_utils import BrickGraph, SparqlExecutionStatus, query_graph
from implementation_policy import evaluation_policy
from llm_client import get_client
from prompting import save_prompt_snapshot
from react_reference import MAX_ITERATIONS, IMPLEMENTATION, expression, reference


class SparqlQuery(BaseModel):
    sparql_query: str = Field(..., description="The generated or revised SPARQL query.")


class QueryCritique(BaseModel):
    decision: str = Field(..., description="The decision, either 'IMPROVE' or 'FINAL'.")
    feedback: str = Field(..., description="Natural language feedback explaining the decision.")


class ReActSparqlQuery(BrickSparqlQuery):
    def __init__(self, sparql, graph=None, endpoint=None):
        super().__init__(sparql)
        self.graph = graph
        self.endpoint = endpoint

    def execute(self, isolated=True):
        if self.endpoint:
            from react_graphdb import execute_json
            self.execution_result = self.execution_variables = self.bindings = self.bindings_preview = []
            try:
                self.execution_variables, self.bindings = execute_json(
                    self.endpoint, self.sparql, evaluation_policy()['sparql_timeout_seconds'])
                self.bindings_preview = self.bindings[:10]
                self.execution_result = [{key:value.get('value', '') for key,value in row.items()}
                                         for row in self.bindings]
                self.execution_status = (SparqlExecutionStatus.SUCCESS if self.bindings
                                         else SparqlExecutionStatus.EMPTY_RESULT)
                self.error = None
            except Exception as exc:
                self.error = str(exc) or f'{type(exc).__name__}: no exception message'
                self.execution_status = SparqlExecutionStatus.OTHER_ERROR
            return
        data, self.execution_status, self.error = query_graph(
            self.sparql, graph=self.graph if self.graph is not None else BrickGraph().source_graph,
            isolated=isolated, timeout=evaluation_policy()['sparql_timeout_seconds'],
            prepare_prefixes=False, include_bindings=True)
        self.execution_result = data['rows'] if data else []
        self.execution_variables = list(data['vars']) if data else []
        self.bindings_preview = data.get('bindings_preview', []) if data else []
        self.bindings = data.get('bindings', []) if data else []
        if data and data['ask']:
            # The pinned local formatter iterates qres.vars (None for ASK).
            # Preserve that inherited failure rather than adding a local fix.
            self.execution_status = SparqlExecutionStatus.SYNTAX_ERROR
            self.error = "'NoneType' object is not iterable"
            self.execution_result = []
            self.execution_variables = []
            self.bindings_preview = self.bindings = []


@dataclass
class ReActAction:
    thought: str
    action_name: str
    action_argument: str
    observation: str = ''
    observation_raw: object = None
    diagnostics: dict = None


@dataclass
class ReActState(AgentState):
    method: str = 'react'
    react_iterations: int = 0
    model_diagnostics: list = field(default_factory=list)


class ReActBaselineAgent:
    method = 'react'
    language = 'en'
    implementation_mode = IMPLEMENTATION
    query_type = ReActSparqlQuery
    use_decomposer = use_temporal_handler = use_aggregation = False
    decomposer = temporal_handler = None

    def __init__(self, source, backend='graphdb', building=None):
        from react_graphdb import endpoint_for
        if backend not in ('rdflib', 'graphdb'):
            raise ValueError('Unknown ReAct execution backend')
        self.execution_backend = backend
        self.endpoint = endpoint_for(building) if backend == 'graphdb' else None
        self.baseline_reference = reference(backend, self.endpoint)
        self.implementation_mode = self.baseline_reference['implementation_mode']
        self.brick_graph = source.brick_graph
        # The provided local constructor parses only the building TTL, without
        # the workbench's ontology merge. Use that same graph for the judge.
        self.evaluation_graph = source.brick_graph.source_graph
        self.ttl_schema_content = source.ttl_schema_content
        self.interface_language = source.interface_language
        self.cancel_event = threading.Event()
        self._current_state = None
        self.log_file = str(Path(source.log_file).with_name('react_prompt_' + uuid4().hex + '.jsonl'))

    def fork_evaluation(self):
        worker = copy(self)
        worker.cancel_event = threading.Event()
        worker._current_state = None
        worker.log_file = str(Path(self.log_file).with_name('react_prompt_' + uuid4().hex + '.jsonl'))
        return worker

    def _assert_graph(self):
        if self.brick_graph is not BrickGraph():
            raise RuntimeError('Agent graph is no longer active; reload before evaluation')

    def _check_cancelled(self):
        if self.cancel_event.is_set():
            raise RuntimeError('Query cancelled')

    def _log(self, event):
        with open(self.log_file, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')

    def _get_structured_response(self, messages, response_model, role, state):
        self._check_cancelled()
        client = get_client()  # Same registry, provider, API key and model as BrickQA.
        state.model_configuration = {'model':client.model, 'provider':client.provider, 'base_url':client.base_url}
        snapshot = save_prompt_snapshot(json.dumps(messages, ensure_ascii=False, indent=2))
        self._log({'event':'model_request', 'method':'react', 'role':role,
                   'round':state.react_iterations, 'model':client.model, 'prompt_language':'en',
                   'prompt_format':'chat_messages', 'temperature':0, 'max_output_tokens':None,
                   'sdk_max_retries':2, 'application_attempts':1,
                   'response_format':{'type':'json_object'}, **snapshot})
        try:
            content = client.generate_messages(messages, temperature=0, response_format={'type':'json_object'},
                                               max_retries=1, cancel_event=self.cancel_event, sdk_max_retries=2)
            self._check_cancelled()
            self._log({'event':'model_response', 'role':role, 'response':content,
                       'response_model':client.last_response_model, **snapshot})
            return response_model.model_validate_json(content)
        except Exception as exc:
            self._check_cancelled()
            message = str(exc)
            if getattr(client, 'api_key', None):
                message = message.replace(client.api_key, '[redacted]')
            state.model_diagnostics.append({'role':role, 'round':state.react_iterations, 'error':message})
            self._log({'event':'model_failure', 'role':role, 'error':message, **snapshot})
            return None  # Author behavior: end the loop, keeping any last query.
        finally:
            model = getattr(client, 'last_response_model', None)
            if model and model not in state.response_models:
                state.response_models.append(model)
            usage = client.last_usage or {}
            state.prompt_tokens += usage.get('prompt_tokens', 0)
            state.completion_tokens += usage.get('completion_tokens', 0)
            state.total_tokens += usage.get('total_tokens', 0)

    def _run_sparql_query(self, query):
        self._check_cancelled()
        result = ReActSparqlQuery(query, graph=self.evaluation_graph, endpoint=self.endpoint)
        if self.evaluation_graph is None and not self.endpoint:
            result.execution_result = result.execution_variables = []
            result.bindings = result.bindings_preview = []
            result.execution_status = SparqlExecutionStatus.OTHER_ERROR
            result.error = 'Graph not loaded.'
            return result, {'summary_string':'SPARQL query failed: The local RDF graph is not loaded.',
                            'results':[], 'row_count':0, 'col_count':0, 'syntax_ok':False,
                            'error_message':'Graph not loaded.'}
        result.execute()
        self._check_cancelled()
        valid = result.execution_status in (SparqlExecutionStatus.SUCCESS, SparqlExecutionStatus.EMPTY_RESULT)
        count = len(result.execution_result)
        if self.endpoint:
            if valid:
                summary = 'Query executed successfully. Here are the first 10 results:\n' + json.dumps(result.bindings[:10], indent=2)
                if not count:
                    summary = 'The query executed successfully but returned no results.'
            else:
                summary = f'The query failed to execute with the following error: {result.error}'
        elif valid:
            summary = f'Query executed successfully on local graph. Found {count} results.'
            if not count:
                summary = 'The query executed successfully on the local graph but returned no results.'
        else:
            # The author passes str(e) verbatim. Display translation must not
            # rewrite quoted names or data inside the RDFLib exception.
            summary = f"The query failed to parse with the following error: {result.error}"
        return result, {'summary_string':summary, 'results':result.bindings,
                        'row_count':count, 'col_count':len(result.execution_variables) if valid else 0,
                        'syntax_ok':valid, 'error_message':result.error}

    def run(self, question, verbose=False):
        self._assert_graph()
        state = ReActState(question, mode='react', language='en', interface_language=self.interface_language,
                           max_iterations=MAX_ITERATIONS)
        self._current_state = state
        from prompting import decomposition_policy
        state.decomposition_policy = decomposition_policy(self)
        system_prompt = expression('system_prompt', knowledge_graph_content=self.ttl_schema_content or '')
        messages = expression('query_writer_messages', system_prompt=system_prompt, nl_question=question)
        final_query = None
        state.stop_reason = 'max_iterations'
        for index in range(MAX_ITERATIONS):
            state.react_iterations = index + 1
            state.phase = f'ReAct Writer ({index + 1}/{MAX_ITERATIONS})'
            writer = self._get_structured_response(messages, SparqlQuery, 'writer', state)
            if not writer or not writer.sparql_query:
                state.stop_reason = 'writer_failure'
                break
            messages.append({'role':'assistant', 'content':json.dumps(writer.model_dump())})
            state.actions.append(ReActAction('Generate or revise the query.', 'react_writer', writer.sparql_query))
            state.phase = f'ReAct SPARQL ({index + 1}/{MAX_ITERATIONS})'
            final_query, results = self._run_sparql_query(writer.sparql_query)
            state.generated_sparqls.append(final_query)
            state.actions.append(ReActAction('Execute the writer query.', 'execute_sparql', writer.sparql_query,
                                             results['summary_string'], final_query))
            critique_messages = expression('critique_prompt', nl_question=question,
                                          final_generated_query=writer.sparql_query, results_obj=results)
            state.phase = f'ReAct Critic ({index + 1}/{MAX_ITERATIONS})'
            critique = self._get_structured_response(critique_messages, QueryCritique, 'critic', state)
            if not critique:
                state.stop_reason = 'critic_failure'
                break
            state.actions.append(ReActAction('Review the query and execution summary.', 'react_critic',
                                             json.dumps(critique.model_dump()), critique.feedback))
            if critique.decision == 'FINAL':
                state.stop_reason = 'critic_final'
                break
            feedback = expression('feedback_for_writer', critique=SimpleNamespace(feedback=critique.feedback))
            messages.append({'role':'user', 'content':feedback})
        if final_query is not None:
            # The reference executes the last generated query again for judging,
            # including when a subsequent writer/critic call failed.
            final_query, _ = self._run_sparql_query(final_query.sparql)
        state.final_sparql = final_query
        state.phase = 'Done'
        return state, final_query
