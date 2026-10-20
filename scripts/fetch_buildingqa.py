"""Fetch versioned official BuildingQA assets; preserve existing paper context samples."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = 'INFERLab/BuildingQA'


def read(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'BrickQA-reproduction'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    sha = json.loads(read(f'https://api.github.com/repos/{REPO}/commits/main'))['sha']
    tree = json.loads(read(f'https://api.github.com/repos/{REPO}/git/trees/{sha}?recursive=1'))['tree']
    graphs = ['bldg11', 'TUC_building', 'dflexlibs_multizone']
    manifest = {'repository': f'https://github.com/{REPO}', 'commit': sha, 'files': []}
    for name in graphs:
        source = f'eval_buildings/{name}.ttl'
        data = read(f'https://raw.githubusercontent.com/{REPO}/{sha}/{source}')
        target = ROOT / 'data' / 'buildings' / f'{name}.ttl'
        target.parent.mkdir(parents=True, exist_ok=True)
        # Validate before replacing any local copy.
        from rdflib import Graph
        graph = Graph().parse(data=data.decode('utf-8'), format='turtle')
        target.write_bytes(data)
        manifest['files'].append({'path': str(target.relative_to(ROOT)), 'upstream': source,
                                 'sha256': hashlib.sha256(data).hexdigest(), 'triples': len(graph)})
        print(name, len(graph), 'triples')
    for entry in tree:
        path = entry['path']
        if path.startswith('Benchmark_QA_pairs/') and path.endswith('.json') and any(n.lower() in path.lower() for n in graphs):
            data = read(f'https://raw.githubusercontent.com/{REPO}/{sha}/{path}')
            target = ROOT / 'data' / 'benchmarks' / Path(path).name
            target.parent.mkdir(parents=True, exist_ok=True)
            json.loads(data)
            target.write_bytes(data)
            manifest['files'].append({'path': str(target.relative_to(ROOT)), 'upstream': path,
                                     'sha256': hashlib.sha256(data).hexdigest()})
            print(Path(path).name)
    (ROOT / 'data' / 'source_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
