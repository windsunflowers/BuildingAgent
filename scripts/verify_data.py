"""Real graph and CSV cross-checks, without model calls."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import app
from brick_utils import query_graph, SparqlExecutionStatus

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = {'gold_queries': []}
    for name in ('bldg11', 'TUC_building', 'dflexlibs_multizone'):
        meta = app._do_load(str(ROOT / 'data' / 'buildings' / (name + '.ttl')))
        items = [json.loads(line) for line in (ROOT / 'benchmarks' / (name + '_human.jsonl')).read_text(encoding='utf-8').splitlines()]
        for item in items:
            print(name, item['query_id'], flush=True)
            data, status, error = query_graph(item['gold_sparql'], timeout=5)
            report['gold_queries'].append({'building': name, 'query_id': item['query_id'],
                                           'status': status.value, 'rows': data['total'] if data else None, 'error': error})
    source = ROOT / 'prompts' / 'lbnl_fdd_fcu_hourly.csv'
    meta = app._do_load(str(ROOT / 'prompts' / 'lbnl_fdd_fcu.ttl'), csv_file=str(source), max_rows=72)
    report['csv_import'] = meta['timeseries']
    errors = [r for r in report['gold_queries'] if r['error']]
    report['summary'] = {'gold_queries': len(report['gold_queries']), 'gold_errors': len(errors)}
    out = ROOT / 'output' / 'validation'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'data_checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary']))
    if errors:
        print(errors)


if __name__ == '__main__':
    main()
