"""Dispatch tools and evaluation acceptance to the pinned author implementation.

The vendored source is unchanged. Function globals are copied per graph, so its
constant BLDG/REF rules survive without sharing the upstream module's singleton.
There is one author implementation; language controls only presentation and prompts.
"""
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import FunctionType
from uuid import uuid4
import json
import math

from third_party.brickqa_upstream import brick_utils as author

UPSTREAM_COMMIT = '49d9e283c2a3958e9be110583be6575cbd40039b'
EVALUATION_ALIGNMENT = 'BrickQA-author-only-20261023-v6-prompt-and-bindings'


def evaluation_policy():
    return {'validation': 'diagnostic_only', 'final_query': 'last_generated',
            'stop': 'model_stop_or_duplicate_or_15_actions', 'sparql_timeout_seconds': 180}


def evaluation_timeout(configured=None):
    """The pinned Agent has no whole-question deadline; overrides are explicit."""
    if configured is None:
        return None
    value = float(configured)
    if value < 0 or not math.isfinite(value):
        raise ValueError('Evaluation timeout must be finite and nonnegative (0 disables the deadline)')
    return value or None




def policy_metadata(graph):
    from rdflib_execution import execution_metadata
    return {'implementation_mode': 'upstream',
            'rdflib_execution': execution_metadata(),
            'evaluation_alignment': EVALUATION_ALIGNMENT,
            'upstream_commit': UPSTREAM_COMMIT,
            'scope': ['search_brick', 'get_brick_entity', 'get_property_examples', 'csv_observations',
                      'diagnostic_validation', 'agent_stop_and_final_selection'],
            'evaluation_policy': evaluation_policy(),
            'controller_prompt_policy': 'upstream_template_without_local_suffix; module_ablation_and_empty_history_rendering',
            'scoring_input': 'full_typed_sparql_json_bindings',
            'query_prefix_policy': 'upstream_agent_preprocessor_and_fixed_executor_prefixes',
            'generation_parameters': {'temperature': 'provider_default', 'max_output_tokens': 'provider_default'},
            'execution_graph_policy': 'building_TTL_without_extra_ontology',
            'paper_environment_verified': False,
            'remaining_adaptations': ['selected_API_model', 'isolated_executor'],
            'diagnostic_log': getattr(graph, 'diagnostic_log', None)}


def record_event(graph, **event):
    if not hasattr(graph, 'diagnostic_log'):
        directory = Path(__file__).resolve().parent / 'logs'
        directory.mkdir(exist_ok=True)
        graph.diagnostic_log = str(directory / f'execution_policy_{uuid4().hex}.jsonl')
    event = {'time': datetime.now(timezone.utc).isoformat(),
             'implementation_mode': 'upstream',
             'upstream_commit': UPSTREAM_COMMIT, **event}
    with open(graph.diagnostic_log, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
    if event.get('status') in ('error', 'empty'):
        print(f"[{event['implementation_mode']}][{event.get('tool')}] {event.get('reason')} (diagnostics: {graph.diagnostic_log})")
    return event


class _ObservedGraph:
    def __init__(self, graph):
        self.graph = graph
        self.errors = []

    def __getattr__(self, name):
        return getattr(self.graph, name)

    def query(self, query):
        try:
            # Materialize in the original order and capture errors swallowed by
            # the author's tools. No query rewriting or URI repair is applied.
            return list(self.graph.query(query))
        except Exception as exc:
            self.errors.append({'query': query, 'reason': f'{type(exc).__name__}: {exc}'})
            raise


def call_author_tool(graph, name, *args):
    with graph._method_lock:
        return _call_author_tool(graph, name, *args)


def _call_author_tool(graph, name, *args):
    if not hasattr(graph, '_author_functions'):
        observed = _ObservedGraph(graph.get_graph())
        class BoundGraph:
            def get_graph(self):
                return observed
        namespace = {**vars(author), 'BrickGraph': BoundGraph}
        graph._author_functions = {}
        graph._author_observed = observed
        for tool in ('search_brick', 'get_brick_entity', 'get_property_examples'):
            fn = getattr(author, tool)
            fn = getattr(fn, '__wrapped__', fn)
            bound = FunctionType(fn.__code__, namespace, fn.__name__, fn.__defaults__)
            graph._author_functions[tool] = lru_cache(maxsize=1000)(bound) if tool != 'get_property_examples' else bound
    graph._author_observed.errors.clear()
    result = graph._author_functions[name](*args)
    details = {'tool': name, 'arguments': list(args), 'fallback_used': False}
    errors = list(graph._author_observed.errors)
    failed = not result or (name == 'get_brick_entity' and not result['properties'])
    if errors:
        cached = graph._author_functions[name]
        if hasattr(cached, 'cache_clear'):
            cached.cache_clear()
        details.update(status='error', reason='Original SPARQL evaluation failed', errors=errors)
    elif failed:
        details.update(status='empty', reason='No matches under the original URI/string matching rules')
    else:
        details['status'] = 'ok'
    if name == 'get_brick_entity':
        details['resolved_uri'] = result['uri']
        if failed:
            details['reason'] = 'No outgoing triples at the author-resolved URI; only strings starting with http bypass constant bldg-59# concatenation'
    elif name == 'get_property_examples':
        value = args[0]
        details['resolved_uri'] = value if value.startswith('http') or ':' in value else str(author.REF[value])
        if failed and not errors:
            details['reason'] = 'No triples for the literal property URI; colon values are not prefix-expanded, bare names use REF only (no BRICK fallback)'
    graph.last_tool_diagnostic = record_event(graph, **details)
    return result


def import_author_csv(graph, csv_file, max_rows, start_date, end_date):
    details = {'tool': 'csv_observations', 'csv': str(csv_file), 'max_rows': max_rows,
               'start_date': start_date, 'end_date': end_date, 'fallback_used': False,
               'point_uri_rule': 'bldg-59#<column>', 'observation_uri_rule': 'bldg-59#obs_<column>_<original_row_index>',
               'timestamp_datatype': str(author.XSD.dateTime), 'value_datatype': str(author.XSD.float),
               'selection': 'strict %m/%d/%Y %H:%M; inclusive dates; file-order tail(N); no sorting'}
    try:
        author.BrickGraph.add_timeseries_data(graph, csv_file, max_rows, start_date, end_date)
    except Exception as exc:
        record_event(graph, **details, status='error', reason=f'{type(exc).__name__}: {exc}')
        raise
    # Metadata only: the actual filtering, indexing and insertion above are
    # executed entirely by the unchanged upstream method.
    import pandas as pd
    from datetime import datetime
    frame = pd.read_csv(csv_file)
    frame['_parsed_dt'] = pd.to_datetime(frame['Datetime'], format='%m/%d/%Y %H:%M')
    if start_date:
        frame = frame[frame['_parsed_dt'] >= datetime.strptime(start_date, '%Y-%m-%d')]
    if end_date:
        frame = frame[frame['_parsed_dt'] <= datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)]
    selected = frame.tail(max_rows)
    graph.timeseries_meta = {'rows': len(selected), 'available_rows': len(frame), 'truncated': len(selected) < len(frame),
                             'start': selected['_parsed_dt'].iloc[0].isoformat(), 'end': selected['_parsed_dt'].iloc[-1].isoformat(),
                             'selected_row_indices': [int(i) for i in selected.index], 'unmatched_columns': [],
                             'uri_mapping': 'constant bldg-59# plus CSV column; no entity matching',
                             'value_datatype': str(author.XSD.float)}
    record_event(graph, **details, status='ok', selected_row_indices=graph.timeseries_meta['selected_row_indices'])


@lru_cache(maxsize=1)
def author_query_preprocessor():
    """Execute only the pinned author's method, without importing its SDK stack."""
    import ast
    import hashlib
    path = Path(__file__).resolve().parent / 'third_party/brickqa_upstream/brick_agent.py'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != 'f8d2ae2307c8614072e822320728da62bd27cb7a4d4d940f43f09a9315abcb35':
        raise RuntimeError('Pinned BrickQA agent checksum mismatch')
    tree = ast.parse(raw)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BrickAgent')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_validate_and_fix_sparql')
    namespace = {'BRICK_PREFIXES': author.BRICK_PREFIXES}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[method.name]
