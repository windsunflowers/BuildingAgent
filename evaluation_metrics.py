"""Adapter for the versioned, unmodified BuildingQA reference metrics."""
from collections import Counter, defaultdict
import re
import hashlib
from pathlib import Path
from third_party.buildingqa.metrics import (
    get_entity_and_row_matching_f1, get_exact_match_f1, normalize_value,
)

METRIC_PROTOCOL = 'BuildingQA@b792a627419dfb679ad1f26e4d3dc325a758e95b'
METRIC_KEYS = ('entity_set_f1', 'row_matching_f1', 'exact_match_f1')
REFERENCE_SHA256 = 'd7d982fe1f9eaa020d00615ec8ab48ed6f0b6117cd4963a53f8e39473447010b'


def metric_reference():
    """Pin executable scoring code, not just a human-readable protocol label."""
    source = Path(__file__).resolve().parent / 'third_party/buildingqa/metrics.py'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != REFERENCE_SHA256:
        raise RuntimeError('BuildingQA reference metrics checksum mismatch; restore the pinned source before evaluation')
    return {'protocol': METRIC_PROTOCOL, 'sha256': digest, 'source': str(source),
            'metrics': list(METRIC_KEYS), 'duplicates': 'preserved',
            'column_mapping': 'one global mapping, optimized for Row Matching F1',
            'exact_match_f1': 'fixed column positions, one-to-one row matching; not binary EM',
            'aggregation': 'question mean and separate building macro average',
            'model_failure': 'zero', 'gold_failure': 'invalid comparable summary',
            'cancelled_question': 'not scored; incomplete run'}


def columns(rows):
    return list(dict.fromkeys(key for row in rows for key in row))


def norm_rows(rows, order=None):
    """Legacy diagnostics only; official scoring must preserve duplicate rows."""
    order = columns(rows) if order is None else order
    return {tuple(str(row.get(key)) if row.get(key) is not None else None for key in order)
            for row in rows}


def f1(gold, pred):
    if not gold and not pred:
        return 1.0
    if not gold or not pred:
        return 0.0
    return 2 * len(gold & pred) / (len(gold) + len(pred))


def to_bindings(rows):
    """Keep row multiplicity and column insertion order in SPARQL JSON bindings."""
    return [{key: value if isinstance(value, dict) else {'value': str(value)}
             for key, value in row.items() if value is not None} for row in rows or []]


def score_rows(gold_rows, pred_rows):
    gold, pred = to_bindings(gold_rows), to_bindings(pred_rows)
    scores = {key: float(value) for key, value in get_entity_and_row_matching_f1(gold, pred).items()}
    scores['exact_match_f1'] = float(get_exact_match_f1(gold, pred))
    def positional_bag(rows):
        order = list(rows[0]) if rows else []
        return len(order), Counter(tuple(normalize_value(row.get(k, {}).get('value', ''))
                                        for k in order) for row in rows)
    binary = int(positional_bag(gold) == positional_bag(pred))
    # Legacy aliases remain for external callers; the UI/report use METRIC_KEYS.
    return {**scores, 'execution_accuracy_binary': binary,
            'exact_match': binary, 'f1': scores['row_matching_f1']}


def summarize_results(results, total=None):
    """Model failures count as zero; invalid gold blocks comparable scores.

    Top-level metrics are question means. building_macro matches Table 2's
    equal weighting of buildings and is explicit to distinguish the two.
    """
    done = len(results)
    total = done if total is None else total
    gold_errors = sum(row.get('status') == 'gold_error' for row in results)
    errors = sum(row.get('status') in ('error', 'gold_error') for row in results)
    groups = defaultdict(list)
    for row in results:
        groups[row.get('building') or 'unknown'].append(row)
    def means(rows):
        if not rows or any(r.get('status') == 'gold_error' for r in rows):
            return {k: None for k in METRIC_KEYS}
        return {k: sum(float(r.get(k) or 0) for r in rows) / len(rows) for k in METRIC_KEYS}
    by_building = {building: {'total': len(rows), **means(rows)} for building, rows in groups.items()}
    macro = {key: (sum(group[key] for group in by_building.values()) / len(by_building)
                   if by_building and not gold_errors else None) for key in METRIC_KEYS}
    return {'total': total, 'done': done, 'errors': errors, 'gold_errors': gold_errors,
            'model_errors': errors - gold_errors, 'valid': not gold_errors,
            'complete': done == total, 'metric_protocol': METRIC_PROTOCOL,
            **means(results), 'by_building': by_building, 'building_macro': macro}


def extract_predicates(sparql):
    return set(re.findall(r'\b(?:brick|ref|rdf|rdfs):[A-Za-z_]\w*', sparql or ''))
