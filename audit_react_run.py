"""Offline verification of a saved ReAct run against the pinned author loop.

Replays saved model responses and saved execution observations. No model/network
calls or query repairs; this verifies workflow, not model quality or GraphDB.
"""
import argparse
import ast
import __future__
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

from evaluation_metrics import METRIC_KEYS, score_rows, to_bindings
from react_baseline import SparqlQuery, QueryCritique
from react_reference import ROOT, reference


def _author_loop():
    reference()  # Verify source hash before compiling the reviewed method.
    tree = ast.parse((ROOT / 'sparql_refinement_agent.py').read_bytes())
    method = next(m for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'SparqlRefinementAgent'
                  for m in c.body if isinstance(m, ast.FunctionDef) and m.name == 'refine_and_evaluate_query')
    namespace = {'json':json, 'os':os, 'SparqlQuery':SparqlQuery, 'QueryCritique':QueryCritique,
                 'get_arity_matching_f1':lambda *a:0, 'get_exact_match_f1':lambda **kw:0,
                 'get_entity_and_row_matching_f1':lambda **kw:{'entity_set_f1':0,'row_matching_f1':0}}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'pinned-author-loop', 'exec',
                 flags=__future__.annotations.compiler_flag), namespace)
    return namespace['refine_and_evaluate_query']


def audit_question(row, context, loop):
    events = [json.loads(line) for line in Path(row['prompt_log']).read_text(encoding='utf-8').splitlines()]
    requests = [event for event in events if event['event'] == 'model_request']
    responses = [event for event in events if event['event'] == 'model_response']
    if len(requests) != len(responses):
        raise ValueError('Saved calls are incomplete; cannot replay transport failures as model responses')
    observations = [action for action in row['actions'] if action['action_name'] == 'execute_sparql']
    cursor, executed, logged = 0, 0, []
    expected_stop = 'max_iterations'

    def call(messages, response_model):
        nonlocal cursor, expected_stop
        request = requests[cursor]
        role = 'writer' if response_model is SparqlQuery else 'critic'
        if request['role'] != role:
            raise ValueError(f'Author role mismatch at call {cursor + 1}')
        raw = Path(request['prompt_file']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != request['prompt_sha256']:
            raise ValueError(f'Prompt snapshot hash mismatch at call {cursor + 1}')
        if messages != json.loads(raw):
            raise ValueError(f'Author message mismatch at call {cursor + 1}')
        content = responses[cursor]['response']
        cursor += 1
        try:
            value = response_model.model_validate_json(content)
            if role == 'critic' and value.decision == 'FINAL':
                expected_stop = 'critic_final'
            return value
        except ValueError:
            expected_stop = role + '_failure'
            return None

    def execute(query):
        nonlocal executed
        if executed > len(observations):
            if query != row['gold_sparql']:
                raise ValueError('Author judge query mismatch')
            values, ok, summary = row['gold_rows'], True, 'Offline judge replay'
        else:
            action = observations[min(executed, len(observations) - 1)]
            if query != action['action_argument']:
                raise ValueError(f'Author query sequence mismatch at execution {executed + 1}')
            executed += 1
            ok = action['execution_status'] in ('success', 'empty_result')
            values = row.get('pred_rows', []) if query == row['pred_sparql'] else []
            summary = action['observation']
        return {'summary_string':summary, 'syntax_ok':ok, 'results':to_bindings(values),
                'row_count':len(values), 'col_count':len(values[0]) if values else 0}

    oracle = SimpleNamespace(max_iterations=3, model_name=row['model_configuration']['model'],
                             _get_structured_response=call, _run_sparql_query=execute)
    logger = SimpleNamespace(filename='offline.csv', log=logged.append)
    with redirect_stdout(io.StringIO()):
        loop(oracle, {'question':row['question'], 'query_id':row['query_id'], 'ground_truth_sparql':row['gold_sparql']},
             logger, '', context)
    if cursor != len(requests) or not logged or logged[0]['generated_sparql'] != row['pred_sparql']:
        raise ValueError('Author stop or final query selection mismatch')
    if row['stop_reason'] != expected_stop:
        raise ValueError('Saved stop reason mismatch')
    scores = score_rows(row.get('gold_bindings', row['gold_rows']),
                        row.get('pred_bindings', row.get('pred_rows', []))) if row['status'] == 'done' else {k:0 for k in METRIC_KEYS}
    if any(abs(scores[k] - row[k]) > 1e-10 for k in METRIC_KEYS):
        raise ValueError('Saved official score mismatch')
    return {'question_index':row['question_index'], 'query_id':row['query_id'], 'verified_calls':cursor,
            'messages_match':True, 'final_query_matches':True, 'stop_reason_matches':True,
            'official_scores_match':True}


def audit_run(path):
    path = Path(path)
    report = json.loads(path.read_text(encoding='utf-8'))
    if report['configuration']['method'] != 'react':
        raise ValueError('Only saved ReAct runs are supported')
    # This audit requires a frozen file, so it does not reconstruct a possibly
    # different context from current runtime state or from test gold queries.
    context_file = path.with_name('context.ttl')
    context = context_file.read_bytes().decode('utf-8-sig')
    loop = _author_loop()
    results = []
    for row in report['results']:
        try:
            results.append(audit_question(row, context, loop))
        except Exception as exc:
            results.append({'question_index':row['question_index'], 'error':f'{type(exc).__name__}: {exc}'})
    return {'kind':'offline_author_workflow_replay_not_model_rerun',
            'report':str(path), 'report_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'verified_questions':sum('error' not in row for row in results), 'total':len(results),
            'verified_calls':sum(row.get('verified_calls',0) for row in results),
            'actual_backend':report['configuration'].get('react_backend'),
            'actual_model':report['configuration'].get('model'),
            'feedback_adaptation':report['configuration']['baseline_reference'].get('feedback_policy'),
            'paper_environment_verified':False, 'results':results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.resolve() == Path(args.report).resolve():
        parser.error('Audit output must not overwrite the original report')
    result = audit_run(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'results'}, ensure_ascii=True))
    raise SystemExit(0 if result['verified_questions'] == result['total'] else 1)
