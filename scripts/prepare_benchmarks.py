"""Convert official QA JSON into executable, building-specific JSONL benchmarks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'benchmarks'
    target.mkdir(exist_ok=True)
    for source in (ROOT / 'data' / 'benchmarks').glob('*_combined.json'):
        all_questions, human = [], []
        for building in json.loads(source.read_text(encoding='utf-8')):
            name = Path(building['building_id']).stem
            for query in building['queries']:
                for question in query['questions']:
                    record = {'ttl': f'data/buildings/{name}.ttl', 'query_id': query['query_id'],
                              'question': question['text'], 'source': question['source'],
                              'gold_sparql': query['sparql_query']}
                    all_questions.append(record)
                    if question['source'] == 'human':
                        human.append(record)
        for suffix, records in (('human', human), ('all', all_questions)):
            path = target / (source.stem.removesuffix('_combined') + '_' + suffix + '.jsonl')
            path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n', encoding='utf-8')
            print(path.name, len(records), 'questions')


if __name__ == '__main__':
    main()
