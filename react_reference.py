"""Pinned BuildingQA ReAct prompts; never import its notebook or SDK setup."""
import ast
import hashlib
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'third_party/buildingqa/react'
COMMIT = 'b792a627419dfb679ad1f26e4d3dc325a758e95b'
SOURCE_SHA256 = '91f3409b15df57d652895fa0b94b7668cc6cdafaeb0cecb1c17784e4bbdcd52e'
MAX_ITERATIONS = 3  # Explicit runner setting in the pinned ReAct_demo.ipynb.
IMPLEMENTATION = 'buildingqa_react_rdflib_author_v1'
DOCUMENT_ROOT = Path(__file__).resolve().parent / 'third_party/user_react_baseline'
DOCUMENT_SHA256 = 'a13be7714b5700b176a09e12447edf7595db305744c6ddd26c19f2e655aaa51e'
DOCUMENT_CODE_SHA256 = '306793307fa3dc98ace33ad84c429b9c43fa90ec362d8f5b795115da1f8fcdae'


@lru_cache(maxsize=1)
def _expressions():
    raw = (ROOT / 'sparql_refinement_agent.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise RuntimeError('Pinned BuildingQA ReAct source hash mismatch')
    tree = ast.parse(raw)
    method = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'SparqlRefinementAgent'
                  for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'refine_and_evaluate_query')
    names = {'system_prompt', 'query_writer_messages', 'critique_prompt', 'feedback_for_writer'}
    result = {}
    for node in ast.walk(method):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in names:
                result[name] = compile(ast.Expression(node.value), str(ROOT / 'sparql_refinement_agent.py'), 'eval')
    if set(result) != names:
        raise RuntimeError('Pinned BuildingQA prompt expressions are incomplete')
    return result


def expression(name, **values):
    # Expressions come only from the hash-checked source reviewed above, not
    # from model output. No module imports, credentials or notebook cells run.
    return eval(_expressions()[name], {'__builtins__':{}}, values)


@lru_cache(maxsize=1)
def document_reference():
    paths = ((DOCUMENT_ROOT / 'react_baseline_implementation.md', DOCUMENT_SHA256),
             (DOCUMENT_ROOT / 'sparql_refinement_agent.py', DOCUMENT_CODE_SHA256))
    for path, digest in paths:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Provided ReAct document/source hash mismatch')
    def prompt_expressions(path):
        tree = ast.parse(path.read_bytes())
        method = next(m for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'SparqlRefinementAgent'
                      for m in c.body if isinstance(m, ast.FunctionDef) and m.name == 'refine_and_evaluate_query')
        names = {'system_prompt', 'query_writer_messages', 'critique_prompt', 'feedback_for_writer'}
        return {node.targets[0].id:ast.dump(node.value, include_attributes=False)
                for node in ast.walk(method) if isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names}
    if prompt_expressions(paths[1][0]) != prompt_expressions(ROOT / 'sparql_refinement_agent.py'):
        raise RuntimeError('Provided document and pinned upstream prompts differ')
    return {'document':'react_baseline_implementation.md', 'sha256':DOCUMENT_SHA256,
            'extracted_source_sha256':DOCUMENT_CODE_SHA256,
            'prompt_expressions_match_pinned_source':True,
            'class_default_max_iterations':5, 'class_default_model':'openai/o4-mini'}


def reference(backend='graphdb', endpoint=None):
    from llm_client import llm_timeout_seconds
    from rdflib_execution import execution_metadata
    _expressions()
    result = {'repository':'https://github.com/INFERLab/BuildingQA', 'commit':COMMIT,
            'provided_document':document_reference(),
            'document_overrides':{'max_iterations':3, 'feedback':'upstream_rdflib_row_count_only',
                                  'model':'user_configured_fixed_model'},
            'implementation_mode':IMPLEMENTATION,
            'model_policy':'caller_selected_model; current user reproduction fixes qwen-plus-2025-12-01',
            'brickqa_paper_reported_model':'gemini-2.5-flash',
            'reproduction_scope':'author_local_rdflib_workflow_with_model_and_runtime_adaptations',
            'source':'ReAct_agent/sparql_refinement_agent.py', 'sha256':SOURCE_SHA256,
            'max_iterations':MAX_ITERATIONS, 'iteration_source':'ReAct_demo.ipynb (explicit 3; class default 5)',
            'workflow':'writer_execute_critic', 'temperature':0, 'response_format':{'type':'json_object'},
            'max_output_tokens':None, 'model_attempts_per_call':1, 'prompt_language':'en',
            'sdk_max_retries':2, 'upstream_sdk_retries':'OpenAI client default; notebook does not override it',
            'model_timeout_seconds':llm_timeout_seconds(),
            'execution_mode':'local_rdflib', 'query_rewriting':False,
            'rdflib_execution':execution_metadata() if backend == 'rdflib' else None,
            'execution_graph_scope':'raw_building_ttl', 'ontology_merge':False,
            'alignment_target':'BuildingQA_RDFLib_branch',
            'feedback_policy':'upstream_rdflib_row_count_only_v1',
            'critic_result_preview_limit':0,
            'critic_receives_columns':False,
            'notebook_default_execution_mode':'remote_GraphDB',
            'critic_receives_ttl_context':False,
            'paper_environment_verified':False,
            'local_critic_observation':'upstream RDFLib success/empty/error summary; row count only on success',
            'gold_execution_policy':'buildingqa_shared_raw_judge_v1',
            'scoring_input':'full_typed_sparql_json_bindings',
            'execution_error_feedback':'verbatim_rdflib_error_without_display_translation',
            'worker_numerical_threads':1,
            'adaptations':['shared configured API/model; original building TTL source graph without ontology merge',
                           'upstream RDFLib row-count-only feedback; not a GraphDB backend',
                           'per-question isolated SPARQL worker; child BLAS/OMP threads=1; 180 second execution budget; cancellation',
                           'shared SDK timeout/retry wrapper; no extra application retries',
                           'shared official three-F1 scorer and invalid-gold precheck',
                           'same frozen TTL context as BrickQA; context is not independently resampled']}
    if backend == 'graphdb':
        from react_graphdb import ENDPOINTS
        result.update(implementation_mode='buildingqa_react_graphdb_author_v1',
                      execution_mode='remote_GraphDB', endpoint=endpoint,
                      execution_graph_scope='graphdb_repository', ontology_merge=None,
                      feedback_policy='upstream_graphdb_first_10_bindings_v1',
                      critic_result_preview_limit=10, critic_receives_columns=False,
                      alignment_target='BuildingQA_GraphDB_branch',
                      reproduction_scope='author_remote_graphdb_workflow_with_model_and_runtime_adaptations',
                      local_critic_observation=None,
                      gold_execution_policy='same_graphdb_repository_as_prediction_v1',
                      graphdb_inference='repository_default_unverified',
                      transport='stdlib_http_get_sparql_json_no_proxy',
                      configured_endpoints=dict(ENDPOINTS),
                      execution_error_feedback='verbatim_remote_error_without_display_translation')
        result['document_overrides']['feedback'] = 'upstream_graphdb_first_10_bindings'
        result['adaptations'] = [
            'shared configured API/model and frozen local TTL prompt context',
            'stdlib HTTP GET/JSON replaces SPARQLWrapper; intranet proxy bypass; 180 second execution budget',
            'repository dataset and inference depend on server configuration; no local fallback',
            'shared SDK timeout/retry wrapper; same official scorer and invalid-gold precheck']
    elif backend != 'rdflib':
        raise ValueError('Unknown ReAct execution backend')
    return result

