"""One real-model, official BuildingQA pilot. This is not the full paper benchmark."""
import json
import os
import sys
import threading
import time
import hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('LLM_TIMEOUT', '20')
from brick_agent import BrickAgent, BrickSparqlQuery
from evaluation_metrics import score_rows
from llm_client import get_client


def main():
    item = json.loads((ROOT / 'benchmarks' / 'TUC_building_human.jsonl').read_text(encoding='utf-8').splitlines()[4])
    manifest = json.loads((ROOT / 'data' / 'source_manifest.json').read_text(encoding='utf-8'))
    # The only building payload is the public, checksum-verified official TUC graph.
    for relative in ('data/buildings/TUC_building.ttl', 'data/benchmarks/TUC_building_combined.json'):
        source = next(f for f in manifest['files'] if f['path'].replace('\\', '/') == relative)
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == source['sha256']
        print('Verified public source: https://github.com/INFERLab/BuildingQA/blob/' + manifest['commit'] + '/' + source['upstream'], flush=True)
    official = json.loads((ROOT / 'data' / 'benchmarks' / 'TUC_building_combined.json').read_text(encoding='utf-8'))
    assert any(q['sparql_query'] == item['gold_sparql'] and any(p['text'] == item['question'] for p in q['questions'])
               for b in official for q in b['queries'])
    # Do not load any user-provided building description or schema sample into the prompt.
    a = BrickAgent(use_temporal_handler=False, use_aggregation=False)
    a.initialize_graph(ttl_file=str(ROOT / 'data' / 'buildings' / 'TUC_building.ttl'))
    a.set_schema_context(0)
    gold = BrickSparqlQuery(item['gold_sparql'])
    gold.execute()
    record = {'question': item['question'], 'building': 'TUC_building', 'mode': 'paper', 'context': 0,
              'model': os.getenv('LLM_MODEL', 'qwen-plus'), 'gold_sparql': item['gold_sparql'],
              'gold_rows': len(gold.execution_result or [])}
    timer = threading.Timer(150, a.cancel_event.set)
    timer.daemon = True
    timer.start()
    started = time.monotonic()
    try:
        state, final = a.run(item['question'], verbose=True)
        record.update(score_rows(gold.execution_result or [], final.execution_result or []))
        record.update(pred_sparql=final.sparql, pred_rows=len(final.execution_result),
                      actions=len(state.actions), tokens=state.total_tokens, status='done')
    except Exception as exc:
        record.update(status='error', error=str(exc))
    finally:
        timer.cancel()
    record['elapsed_seconds'] = round(time.monotonic() - started, 2)
    out = ROOT / 'output' / 'validation'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'model_pilot.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k not in ('gold_sparql','pred_sparql')},ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
