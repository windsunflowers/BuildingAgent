"""Explicit local RDFLib execution adaptation; never edits SPARQL or RDF data."""
from contextlib import contextmanager
from contextvars import ContextVar
import os

from rdflib import Graph, __version__
from rdflib.plugins.sparql import CUSTOM_EVALS, prepareQuery
from rdflib.plugins.sparql.evaluate import evalBGP
from rdflib.plugins.sparql.parserutils import CompValue

_enabled = ContextVar('brickqa_connected_bgp', default=False)
_NAME = 'brickqa_connected_bgp_v1'


def execution_metadata():
    mode = os.getenv('BRICK_RDFLIB_OPTIMIZER', 'connected_bgp')
    if mode not in ('native', 'connected_bgp'):
        raise ValueError('BRICK_RDFLIB_OPTIMIZER must be native or connected_bgp')
    return {'engine': 'rdflib', 'version': __version__, 'optimizer': mode,
            'adaptation': 'query_local_connected_bgp_v1' if mode != 'native' else None,
            'eligible_algebra': ['SelectQuery', 'Project', 'Distinct', 'BGP'],
            'query_text_modified': False, 'graph_modified': False,
            'unordered_result_sequence_may_change': mode != 'native'}


def _eligible(node):
    # Slice/LIMIT/OFFSET, ORDER BY, aggregation, BIND, OPTIONAL, UNION and
    # subqueries keep RDFLib's original evaluator and ordering behavior.
    if isinstance(node, CompValue):
        if node.name not in ('SelectQuery', 'Project', 'Distinct', 'BGP'):
            return False
        if node.name == 'SelectQuery' and node['datasetClause']:
            return False
        return all(_eligible(value) for value in node.values())
    if isinstance(node, (list, tuple)):
        return all(_eligible(value) for value in node)
    return True


def _connected(ctx, triples):
    if not triples:
        yield ctx.solution()
        return
    first = min(range(len(triples)),
                key=lambda i: sum(ctx[term] is None for term in triples[i]))
    rest = triples[:first] + triples[first + 1:]
    # All matching, RDF terms, path semantics and bindings remain RDFLib's.
    for row in evalBGP(ctx, [triples[first]]):
        yield from _connected(ctx.thaw(row), rest)


def _custom(ctx, part):
    if not _enabled.get() or part.name != 'BGP':
        raise NotImplementedError
    return _connected(ctx, list(part.triples))


CUSTOM_EVALS[_NAME] = _custom


@contextmanager
def query_execution(graph, query):
    if execution_metadata()['optimizer'] == 'native' or not isinstance(graph, Graph):
        yield query
        return
    prepared = prepareQuery(query, initNs=dict(graph.namespaces()))
    enabled = prepared.algebra.name == 'SelectQuery' and _eligible(prepared.algebra)
    token = _enabled.set(enabled)
    try:
        # Keep the context active during lazy result materialization as well.
        yield prepared
    finally:
        _enabled.reset(token)
