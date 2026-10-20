"""Shared per-question evaluation for the CLI and the web application."""
from dataclasses import asdict
from pathlib import Path
import threading
import time

from brick_agent import BrickSparqlQuery
from brick_utils import SparqlExecutionStatus
from evaluation_metrics import METRIC_KEYS, extract_predicates, score_rows
from implementation_policy import policy_metadata

VALID_STATUSES = (SparqlExecutionStatus.SUCCESS, SparqlExecutionStatus.EMPTY_RESULT)


def evaluate_question(agent, item, timeout=None, on_progress=None, cancel_event=None):
    record = {
        'question': item['question'], 'query_id': item.get('query_id'),
        'question_source': item.get('source'),
        'building': Path(item.get('ttl') or 'unknown').stem,
        'language': agent.language, 'mode': 'paper',
        'method_policy': policy_metadata(agent.brick_graph),
        'implementation_mode': agent.implementation_mode,
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
        gold = BrickSparqlQuery(record['gold_sparql'])
        gold.execute()
        check_cancelled()
        if gold.execution_status not in VALID_STATUSES:
            raise ValueError('Gold SPARQL failed: ' + str(gold.error))
        gold_rows = gold.execution_result or []
        record.update(gold_count=len(gold_rows), gold_rows=gold_rows)
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
                          pred_rows=final.execution_result or [],
                          execution_status=final.execution_status.value if final.execution_status else None,
                          execution_error=final.error, validation_warnings=list(final.validation_warnings),
                          diagnostic_warnings=list(final.diagnostic_warnings))
        if final is None or final.execution_status not in VALID_STATUSES:
            raise ValueError('No executable final answer' + (': ' + str(final.error) if final and final.error else ''))
        pred_rows = final.execution_result or []
        record.update(score_rows(gold_rows, pred_rows))
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
        state = getattr(agent, '_current_state', None) if stage == 'model' else None
        if state:
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
        record['method_policy'] = policy_metadata(agent.brick_graph)
    return record
