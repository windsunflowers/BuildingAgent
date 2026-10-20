"""Evaluate the paper Agent using the pinned official BuildingQA metrics."""
import argparse
from datetime import datetime
import json
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent
os.chdir(HERE)

from brick_utils import BrickGraph
from brick_agent import BrickAgent
from evaluation_metrics import METRIC_KEYS, METRIC_PROTOCOL, metric_reference, summarize_results
from evaluation_runner import evaluate_question
from implementation_policy import evaluation_timeout, evaluation_policy
from model_settings import get_registry


def evaluate_item(item, args):
    ttl = item.get('ttl') or args.ttl
    item = {**item, 'ttl': ttl}
    try:
        if not ttl:
            raise ValueError('Missing building TTL')
        BrickGraph.reset_singleton()
        BrickGraph().initialize(ttl_file=ttl)
    except Exception as exc:
        return {'question': item['question'], 'building': Path(ttl or 'unknown').stem,
                'status': 'gold_error', 'error': f'{type(exc).__name__}: {exc}',
                **{k: None for k in METRIC_KEYS}}
    agent = BrickAgent(use_temporal_handler=False, use_aggregation=False, language=args.language)
    agent._extract_date_metadata()
    agent.set_schema_context(args.context)
    return evaluate_question(agent, item, timeout=args.timeout)


def main():
    ap = argparse.ArgumentParser(description='BrickQA official BuildingQA evaluation')
    ap.add_argument('--benchmark', default='benchmark_sample.jsonl')
    ap.add_argument('--ttl', default=None)
    ap.add_argument('--only', default=None, help='Comma-separated question indices')
    ap.add_argument('--report', default=None, help='JSON report path; defaults to a new run directory')
    ap.add_argument('--language', choices=('zh', 'en'), default='en', help='Agent prompt language')
    ap.add_argument('--context', type=int, choices=(0, 100, 5000), default=0,
                    help='Initial model context only; the execution graph remains complete')
    ap.add_argument('--timeout', type=float, default=None, help='Optional whole-question deadline; defaults to none; 0 disables it')
    ap.add_argument('--workers', type=int, choices=range(1, 9), default=3,
                    help='Concurrent questions (default 3); 1 runs sequentially')
    args = ap.parse_args()
    try:
        args.timeout = evaluation_timeout(args.timeout)
    except ValueError as exc:
        ap.error(str(exc))
    items = [json.loads(line) for line in Path(args.benchmark).read_text(encoding='utf-8').splitlines() if line.strip()]
    if args.only is not None:
        items = [items[int(i)] for i in args.only.split(',') if i.strip()]
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8]
    target = Path(args.report) if args.report else HERE / 'output/evaluations' / run_id / 'report.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {'run_id': run_id, 'metric_protocol': METRIC_PROTOCOL,
              'metric_reference': metric_reference(),
              'configuration': {'implementation_mode': 'upstream', 'evaluation_policy':evaluation_policy(), 'upstream_commit': '49d9e283c2a3958e9be110583be6575cbd40039b', 'language': args.language, 'context': args.context, 'mode': 'paper',
                                'model': get_registry().current().model, 'benchmark': args.benchmark,
                                'model_configuration':get_registry().current().public(),
                                'temporal': False, 'operations': False, 'timeout': args.timeout,
                                'workers': args.workers, 'scheduling': 'isolated_process_pool'},
              'results': []}
    def save():
        report['summary'] = summarize_results(report['results'], total=len(items))
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    completed = {}
    def accept(index, record):
        record['question_index'] = index + 1
        completed[index] = record
        report['results'] = [completed[i] for i in sorted(completed)]
        save()
        print(f'[{len(completed)}/{len(items)}] #{index + 1} {items[index]["question"]}', flush=True)
        print('  ' + record['status'] + '  ' + '  '.join(f'{key}={record.get(key)}' for key in METRIC_KEYS))
        if record.get('error'):
            print('  ' + record['error'])
    if args.workers == 1:
        for index, item in enumerate(items):
            accept(index, evaluate_item(item, args))
    elif items:
        # Each process owns its graph singleton and model client. Bound the queue
        # to the worker count rather than submitting the complete benchmark.
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
            pending, next_index = {}, 0
            while pending or next_index < len(items):
                while len(pending) < args.workers and next_index < len(items):
                    pending[pool.submit(evaluate_item, items[next_index], args)] = next_index
                    next_index += 1
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    index = pending.pop(future)
                    accept(index, future.result())
    label = '评测汇总' if args.language == 'zh' else 'Evaluation summary'
    print(label + ':\n' + json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(('报告：' if args.language == 'zh' else 'Report: ') + str(target.resolve()))


if __name__ == '__main__':
    main()
