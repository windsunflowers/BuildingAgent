"""Read-only GraphDB transport; GET/JSON match SPARQLWrapper defaults."""
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError


class GraphDBUnavailableError(ConnectionError):
    """Transport failure, distinct from an invalid SPARQL query."""

ENDPOINTS = {
    'TUC_building': 'http://CHINAMI-42UOT9U:7200/repositories/TUC_building_test',
    'dflexlibs_multizone': 'http://CHINAMI-42UOT9U:7200/repositories/DFLEX',
    'bldg11': 'http://CHINAMI-42UOT9U:7200/repositories/bldg11',
}


def endpoint_for(building):
    name = Path(building or '').stem
    if name not in ENDPOINTS:
        raise ValueError(f'No GraphDB repository configured for building: {name}')
    return ENDPOINTS[name]


def execute_json(endpoint, query, timeout):
    # Never send updates, change LIMIT, add prefixes or modify infer settings.
    from rdflib.plugins.sparql.parser import parseQuery
    from brick_utils import _query_parse_lock
    with _query_parse_lock:
        parsed = parseQuery(query)
    if parsed[1].name not in ('SelectQuery', 'AskQuery'):
        raise ValueError('Only read-only SELECT and ASK queries are supported')
    request = Request(endpoint + '?' + urlencode({'query': query}),
                      headers={'Accept': 'application/sparql-results+json'})
    # Explicit intranet endpoints; do not route through ambient proxies.
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        # Preserve the endpoint's diagnostic body for Critic, as the reference
        # SPARQLWrapper exception does, instead of reducing it to "HTTP 400".
        body = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'HTTP {exc.code} {exc.reason}: {body}') from exc
    except (URLError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise GraphDBUnavailableError(
            f'GraphDB repository unavailable: {endpoint}. '
            f'Check that GraphDB is running and its host/port are reachable. '
            f'Connection error: {reason}') from exc
    # Preserve the author's handling of ASK (no SELECT bindings).
    return payload.get('head', {}).get('vars', []), payload.get('results', {}).get('bindings', [])


def check_repository(endpoint, timeout=5):
    """Read-only readiness probe; no dataset changes or alternative backend."""
    execute_json(endpoint, 'SELECT (1 AS ?ready) WHERE {}', timeout)
