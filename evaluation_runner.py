"""Shared per-question evaluation for the CLI and the web application."""
from dataclasses import asdict
from pathlib import Path
import threading
import time

from brick_agent import BrickSparqlQuery
from brick_utils import SparqlExecutionStatus
from evaluation_metrics import METRIC_KEYS, extract_predicates, score_rows
from implementation_policy import policy_metadata
from prompting import decomposition_policy, LANGUAGE_POLICY
from evaluation_methods import method_metadata

VALID_STATUSES = (SparqlExecutionStatus.SUCCESS, SparqlExecutionStatus.EMPTY_RESULT)


class GoldSparqlQuery(BrickSparqlQuery):
    """One raw judge for both methods; never apply model-specific repairs."""
    def __init__(self, sparql, graph=None):
        super().__init__(sparql)
        self.graph = graph

    def execute(self, isolated=True):
        from brick_utils import query_graph
        from implementation_policy import evaluation_policy
        data, self.execution_status, self.error = query_graph(
            self.sparql, graph=self.graph, isolated=isolated, prepare_prefixes=False,
            include_bindings=True,
            timeout=evaluation_policy()['sparql_timeout_seconds'])
        self.execution_result = data['rows'] if data else []
        self.execution_variables = list(data['vars']) if data else []
        self.bindings = data.get('bindings', []) if data else []


def gold_query_text(query, ttl):
    # Pinned ReAct_demo.ipynb runner + utils.extract_prefixes_from_ttl:
    # only prepend the source TTL's declarations when no 'prefix' occurs.
    # Preserve existing declarations, including incorrect ones, for diagnosis.
    if 'prefix' in query.lower() or not ttl:
        return query
    prefixes = []
    for line in Path(ttl).read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if stripped.lower().startswith('@prefix'):
            parts = stripped.split()
            if len(parts) >= 3:
                prefixes.append(f'PREFIX {parts[1]} {parts[2]}')
    return '\n'.join(prefixes) + '\n\n' + query


def evaluate_question(agent, item, timeout=None, on_progress=None, cancel_event=None):
    from llm_client import llm_timeout_seconds
    method = getattr(agent, 'method', 'brickqa')
    record = {
        'question': item['question'], 'query_id': item.get('query_id'),
        'question_source': item.get('source'),
        'building': Path(item.get('ttl') or 'unknown').stem,
        'language': agent.language, 'mode': 'react' if method == 'react' else 'paper',
        'prompt_language': agent.language, 'interface_language': agent.interface_language,
        'language_policy': LANGUAGE_POLICY,
        'model_timeout_seconds': llm_timeout_seconds(),
        **method_metadata(method, agent.brick_graph, getattr(agent, 'baseline_reference', None)),
        'implementation_mode': agent.implementation_mode,
        'decomposition_policy': decomposition_policy(agent),
        'gold_sparql': item.get('gold_sparql'), 'pred_sparql': None,
        'gold_count': None, 'pred_count': None,
        **{key: 0.0 for key in METRIC_KEYS}, 'execution_accuracy_binary': 0,
        'steps': None, 'elapsed_sec': None, 'error': None, 'status': 'running',
        'relation_mismatch': None,
    }
    started = time.monotonic()
    agent._current_state = None
    stage = 'gold'
    timer = None
    def check_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError('Evaluation cancelled by user')
    try:
        check_cancelled()
        if on_progress:
            on_progress('gold')
        check_cancelled()
        agent._assert_graph()
        if not record['gold_sparql']:
            raise ValueError('Missing gold_sparql')
        judge_text = gold_query_text(record['gold_sparql'], item.get('ttl'))
        record.update(gold_execution_sparql=judge_text,
                      gold_execution_policy=(agent.baseline_reference['gold_execution_policy']
                                             if method == 'react' else 'buildingqa_shared_raw_judge_v1'))
        if method == 'react':
            # The judge and Writer share the same executor and repository.
            gold, _ = agent._run_sparql_query(judge_text)
        else:
            gold = GoldSparqlQuery(judge_text, graph=getattr(agent, 'evaluation_graph', None))
            gold.execute()
        record.update(gold_execution_status=gold.execution_status.value if gold.execution_status else None,
                      gold_execution_error=gold.error)
        check_cancelled()
        if gold.execution_status not in VALID_STATUSES:
            raise ValueError('Gold SPARQL failed: ' + str(gold.error))
        gold_rows = gold.execution_result or []
        record.update(gold_count=len(gold_rows), gold_rows=gold_rows, gold_bindings=gold.bindings)
        if method == 'react':
            record.update(gold_bindings=gold.bindings, gt_num_rows=len(gold_rows),
                          gt_num_cols=len(gold.execution_variables), arity_matching_f1=0.0,
                          syntax_ok=False, returns_results=False, perfect_match=False,
                          gen_num_rows=0, gen_num_cols=0, less_columns_flag=False)
        stage = 'model'
        if on_progress:
            on_progress('model')
        if cancel_event is None or not cancel_event.is_set():
            agent.cancel_event.clear()
        check_cancelled()
        if timeout is not None:
            timer = threading.Timer(timeout, agent.cancel_event.set)
            timer.daemon = True
            timer.start()
        state, final = agent.run(item['question'], verbose=False)
        check_cancelled()
        if final is not None:
            record.update(pred_sparql=final.sparql, pred_count=len(final.execution_result or []),
                          pred_rows=final.execution_result or [], pred_bindings=final.bindings,
                          execution_status=final.execution_status.value if final.execution_status else None,
                          execution_error=final.error, validation_warnings=list(final.validation_warnings),
                          diagnostic_warnings=list(final.diagnostic_warnings))
            if method == 'react':
                valid = final.execution_status in VALID_STATUSES
                record.update(pred_bindings=final.bindings, syntax_ok=valid,
                              returns_results=bool(final.execution_result),
                              gen_num_rows=len(final.execution_result or []),
                              gen_num_cols=len(final.execution_variables) if valid else 0)
        if final is None or final.execution_status not in VALID_STATUSES:
            details = final.error if final and final.error else getattr(state, 'model_diagnostics', None)
            raise ValueError('No executable final answer' + (': ' + str(details) if details else ''))
        pred_rows = final.execution_result or []
        stage = 'scoring'
        state.phase = '计算官方 F1'
        if on_progress:
            on_progress('scoring')
        check_cancelled()
        # ReAct's reference scores the formatter's full SPARQL JSON bindings,
        # not the workbench's display rows. Keep absent variables absent and
        # preserve RDF terms and projection order through the scoring boundary.
        record.update(score_rows(gold.bindings, final.bindings))
        check_cancelled()
        if method == 'react':
            from third_party.buildingqa.metrics import get_arity_matching_f1
            record.update(arity_matching_f1=get_arity_matching_f1(final.sparql, judge_text),
                          perfect_match=record['row_matching_f1'] == 1.0,
                          less_columns_flag=record['gen_num_cols'] < record['gt_num_cols'])
        record.update(pred_sparql=final.sparql, pred_count=len(pred_rows), pred_rows=pred_rows,
                      status='done')
        gp, pp = extract_predicates(record['gold_sparql']), extract_predicates(final.sparql)
        record['relation_mismatch'] = bool(gp and pp and not gp & pp)
    except Exception as exc:
        cancelled = cancel_event is not None and cancel_event.is_set()
        record.update(status='cancelled' if cancelled else ('gold_error' if stage == 'gold' else 'error'),
                      error=f'{type(exc).__name__}: {exc}')
        if stage == 'gold' or cancelled:
            record.update({key: None for key in METRIC_KEYS})
            record['execution_accuracy_binary'] = None
    finally:
        if timer:
            timer.cancel()
        state = getattr(agent, '_current_state', None) if stage in ('model', 'scoring') else None
        if state:
            if method == 'react':
                record.update(react_iterations=state.react_iterations, model_diagnostics=state.model_diagnostics)
            record.update(model_configuration=state.model_configuration, response_models=state.response_models)
            record.update(steps=len(state.actions), tokens={'prompt': state.prompt_tokens,
                          'completion': state.completion_tokens, 'total': state.total_tokens},
                          decomposition=asdict(state.decomposition) if state.decomposition else None,
                          decomposition_fallback=getattr(state, 'decomposition_fallback', False),
                          actions=[{'thought': a.thought, 'action_name': a.action_name,
                                    'action_argument': a.action_argument, 'observation': a.observation,
                                    'execution_status': (a.observation_raw.execution_status.value
                                        if isinstance(a.observation_raw, BrickSparqlQuery) and a.observation_raw.execution_status else None),
                                    'execution_error': (a.observation_raw.error if isinstance(a.observation_raw, BrickSparqlQuery) else None),
                                    'result_count': (len(a.observation_raw.execution_result or []) if isinstance(a.observation_raw, BrickSparqlQuery) else None)}
                                   for a in state.actions],
                          stop_reason=state.stop_reason or (state.actions[-1].action_name if state.actions else None))
        record['elapsed_sec'] = round(time.monotonic() - started, 3)
        record['prompt_log'] = getattr(agent, 'log_file', None)
        if state and state.decomposition:
            record['decomposition_prompt'] = getattr(agent.decomposer, 'last_prompt', None)
        if state:
            record['tool_diagnostics'] = [a.diagnostics for a in state.actions if a.diagnostics]
        record.update(method_metadata(method, agent.brick_graph, getattr(agent, 'baseline_reference', None)))
    return record
