"""
Brick Schema Utilities
Provides Brick-specific operations analogous to SPINACH's Wikidata utilities.
"""

from enum import Enum
from typing import List, Dict, Tuple, Optional
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD, OWL
import json
import os
import threading
from implementation_policy import call_author_tool, import_author_csv, record_event

_query_parse_lock = threading.RLock()


# --- Official Brick ontology (class hierarchy) for rdfs:subClassOf* reasoning ---
# The sampled building TTLs only contain instance data and concrete types, but NOT
# the Brick class inheritance chain. Merging the official ontology makes queries
# like `?s rdf:type/rdfs:subClassOf* brick:Temperature_Sensor` resolve in one shot.
def _locate_brick_ontology() -> str | None:
    """
    Locate the official brick.ttl to merge into the graph.
    Search order:
      1. $BRICK_ONTOLOGY_PATH (explicit override)
      2. <module_dir>/ontology/brick.ttl   (recommended, shipped with repo)
      3. <module_dir>/brick.ttl
    Returns the absolute path or None if not found.
    """
    candidates = [
        os.environ.get("BRICK_ONTOLOGY_PATH"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ontology", "brick.ttl"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "brick.ttl"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def _merge_brick_ontology(graph: Graph) -> bool:
    """Parse the official Brick ontology into `graph` in-place. Returns True if merged."""
    onto = _locate_brick_ontology()
    if not onto:
        print("Warning: Brick ontology (brick.ttl) not found; "
              "rdfs:subClassOf* reasoning may return empty results. "
              "Set $BRICK_ONTOLOGY_PATH or place brick.ttl under ontology/.")
        return False
    before = len(graph)
    graph.parse(onto, format="turtle")
    print(f"Merged Brick ontology from {onto} "
          f"(+{len(graph) - before} triples, {len(graph)} total)")
    return True


# Brick Schema Namespaces
BRICK = Namespace("https://brickschema.org/schema/Brick#")
BLDG = Namespace("bldg-59#")
REF = Namespace("https://brickschema.org/schema/Brick/ref#")

# Standard prefixes for Brick SPARQL queries
BRICK_PREFIXES = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bldg: <bldg-59#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""


class SparqlExecutionStatus(Enum):
    """Status codes for SPARQL execution"""
    SUCCESS = "success"
    EMPTY_RESULT = "empty_result"
    SYNTAX_ERROR = "syntax_error"
    TIMED_OUT = "timed_out"
    OTHER_ERROR = "other_error"

    def get_message(self) -> str:
        messages = {
            self.SUCCESS: "查询执行成功",
            self.EMPTY_RESULT: "查询未返回任何结果",
            self.SYNTAX_ERROR: "查询存在语法错误",
            self.TIMED_OUT: "查询执行超时",
            self.OTHER_ERROR: "查询执行出错"
        }
        return messages.get(self, "未知状态")


class BrickGraph:
    """
    Manages the Brick schema graph and provides query capabilities.
    Singleton pattern to maintain one graph instance.
    """
    _instance = None
    _graph = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BrickGraph, cls).__new__(cls)
        return cls._instance

    @property
    def implementation_mode(self):
        return 'upstream'

    @property
    def last_tool_diagnostic(self):
        return getattr(getattr(self, '_tool_diagnostics', None), 'value', None)

    @last_tool_diagnostic.setter
    def last_tool_diagnostic(self, value):
        if not hasattr(self, '_tool_diagnostics'):
            self._tool_diagnostics = threading.local()
        self._tool_diagnostics.value = value

    def initialize(self, ttl_file: str = None, graph: Graph = None):
        """
        Initialize the Brick graph from TTL file or existing graph.

        Args:
            ttl_file: Path to Turtle file containing Brick schema
            graph: Existing rdflib Graph object
        """
        if self._graph is not None:
            print("Warning: BrickGraph already initialized. Skipping.")
            return

        self._method_lock = _query_parse_lock
        self._tool_diagnostics = threading.local()
        search_brick.cache_clear()
        get_brick_entity.cache_clear()
        for attribute in ('_author_functions', '_author_observed', 'diagnostic_log', 'last_tool_diagnostic'):
            self.__dict__.pop(attribute, None)

        if graph is not None:
            self._graph = graph
        elif ttl_file:
            from building_data import load_building_graph
            self._graph, self.data_warnings = load_building_graph(ttl_file)
            print(f"Loaded {len(self._graph)} triples from {ttl_file}")
        else:
            self._graph = Graph()
            print("Initialized empty Brick graph")

        self.source_graph = Graph()
        for triple in self._graph:
            self.source_graph.add(triple)
        for prefix, uri in self._graph.namespaces():
            self.source_graph.bind(prefix, uri, replace=True)
        self.source_triples = len(self.source_graph)
        self.timeseries_meta = {"rows": 0, "available_rows": 0, "truncated": False, "unmatched_columns": []}

        # Merge the official Brick ontology so rdfs:subClassOf* reasoning works
        # in a single query (sampled building TTLs lack the class hierarchy).
        _merge_brick_ontology(self._graph)

        # Bind common namespaces
        self._graph.bind("brick", BRICK)
        # Preserve the building namespace parsed from its TTL.
        ns = dict(self._graph.namespaces())
        if "bldg" not in ns:
            building_ns = ns.get("ns2")
            if building_ns:
                self._graph.bind("bldg", building_ns)
        self._graph.bind("ref", REF)

    def get_graph(self) -> Graph:
        """Get the underlying RDFLib graph"""
        if self._graph is None:
            raise RuntimeError("BrickGraph not initialized. Call initialize() first.")
        return self._graph

    def add_timeseries_data(self, csv_file: str, max_rows: int = 100,
                            start_date: str = None, end_date: str = None):
        return import_author_csv(self, csv_file, max_rows, start_date, end_date)


    def save_graph(self, output_file: str = "brick_graph_cache.ttl"):
        """
        Save the graph to a file for quick reloading.

        Args:
            output_file: Path to save the graph (default: brick_graph_cache.ttl)
        """
        if self._graph is None:
            raise RuntimeError("BrickGraph not initialized. Nothing to save.")

        print(f"💾 Saving graph with {len(self._graph)} triples to {output_file}...")
        self._graph.serialize(destination=output_file, format='turtle')
        from pathlib import Path
        from implementation_policy import policy_metadata
        Path(str(output_file) + '.policy.json').write_text(json.dumps(policy_metadata(self), indent=2), encoding='utf-8')
        print(f"✅ Graph saved successfully!")


    @classmethod
    def reset_singleton(cls):
        """Reset the graph singleton (useful for rebuilding cache)"""
        if cls._instance is not None:
            cls._instance._graph = None
            cls._graph = None
            print("🔄 Graph singleton reset")
        search_brick.cache_clear()
        get_brick_entity.cache_clear()

    def reset(self):
        """Reset the graph (useful for rebuilding cache)"""
        BrickGraph._graph = None
        self._graph = None
        search_brick.cache_clear()
        get_brick_entity.cache_clear()
        print("🔄 Graph reset")

    def get_date_range(self) -> tuple:
        """
        Get the date range of the timeseries data in the graph.

        Returns:
            Tuple of (min_date, max_date) as strings in YYYY-MM-DD format, or (None, None) if no data
        """
        if self._graph is None:
            return (None, None)

        query = f"""
        {BRICK_PREFIXES}
        SELECT (MIN(?timestamp) AS ?min_date) (MAX(?timestamp) AS ?max_date)
        WHERE {{
            ?obs ref:hasTimestamp ?timestamp .
        }}
        """

        try:
            results = list(self._graph.query(query))
            if results and results[0]:
                min_date = results[0][0]
                max_date = results[0][1]

                if min_date and max_date:
                    # Extract just the date part (YYYY-MM-DD)
                    min_str = str(min_date)[:10] if len(str(min_date)) >= 10 else str(min_date)
                    max_str = str(max_date)[:10] if len(str(max_date)) >= 10 else str(max_date)
                    return (min_str, max_str)
        except Exception as e:
            print(f"Warning: Could not determine date range: {e}")

        return (None, None)


def local_name(uri):
    text = str(uri)
    if '#' in text or '/' in text:
        return text.rsplit('#', 1)[-1].rsplit('/', 1)[-1]
    return text.rsplit(':', 1)[-1]


def namespace_map(graph=None):
    graph = graph if graph is not None else BrickGraph().get_graph()
    ns = {p: str(u) for p, u in graph.namespaces() if p}
    ns.update(brick=str(BRICK), ref=str(REF), rdf=str(RDF), rdfs=str(RDFS), xsd=str(XSD), owl=str(OWL))
    return ns


def graph_prefixes(graph=None):
    return '\n'.join(f'PREFIX {p}: <{u}>' for p, u in namespace_map(graph).items())


def prepare_query(query, graph=None):
    """Complete prefixes from the loaded graph without guessing a building URI."""
    import re
    query = query.strip().removesuffix(';')
    ns = namespace_map(graph)
    query = re.sub(r'PREFIX\s+(\w+):\s+(https?://[^\s<>]+)', r'PREFIX \1: <\2>', query, flags=re.I)
    declared = set(re.findall(r'PREFIX\s+([\w-]+):', query, flags=re.I))
    # The loaded graph is authoritative for known namespace aliases.
    for p, uri in ns.items():
        query = re.sub(rf'PREFIX\s+{re.escape(p)}:\s*<[^>]+>',
                       lambda m, p=p, uri=uri: f'PREFIX {p}: <{uri}>', query, flags=re.I)
    missing = '\n'.join(f'PREFIX {p}: <{u}>' for p, u in ns.items() if p not in declared)
    return missing + '\n' + query


def query_graph(query, graph=None, timeout=30, display_limit=None, isolated=True):
    """Read-only execution; parsing AND lazy result materialization share one deadline."""
    import threading
    import re
    graph = graph if graph is not None else BrickGraph().get_graph()
    query = prepare_query(query, graph)
    holder = {}

    def run():
        try:
            from rdflib.plugins.sparql.parser import parseQuery
            # Parent-process validation shares the author tools' parser lock.
            with _query_parse_lock:
                parsed = parseQuery(query)
            if parsed[1].name not in ('SelectQuery', 'AskQuery'):
                raise ValueError('仅支持 SELECT 和 ASK 只读查询')
            if re.search(r'\bSERVICE\b', query, re.I):
                raise ValueError('本地图谱查询不支持远程 SERVICE')
            if isolated and isinstance(graph, Graph):
                from sparql_worker import run_isolated
                kind, payload = run_isolated(graph, query, display_limit, timeout)
                if kind == 'timeout':
                    holder['timeout'] = True
                elif kind == 'error':
                    holder['error'] = payload
                else:
                    holder['data'] = payload
                return
            with _query_parse_lock:
                result = graph.query(query)
                if result.type == 'ASK':
                    holder['data'] = {"ask": True, "value": bool(result.askAnswer),
                                      "rows": [{"ASK": bool(result.askAnswer)}], "vars": ['ASK'], "total": 1}
                else:
                    rows = [{str(v): str(row[v]) if row[v] is not None else None
                             for v in result.vars} for row in result]
                    holder['data'] = {"ask": False, "rows": rows if display_limit is None else rows[:display_limit],
                                      "vars": [str(v) for v in result.vars], "total": len(rows)}
        except Exception as exc:
            holder['error'] = str(exc)

    # Carry the per-question RDF worker session into the timeout wrapper thread.
    from contextvars import copy_context
    query_context = copy_context()
    worker = threading.Thread(target=lambda: query_context.run(run), daemon=True)
    worker.start()
    # Process startup/pickling is separate from the execution budget.
    worker.join(timeout + (10 if isolated and isinstance(graph, Graph) else 0))
    if worker.is_alive() or holder.get('timeout'):
        return None, SparqlExecutionStatus.TIMED_OUT, f'查询超过 {timeout} 秒'
    if 'error' in holder:
        return None, SparqlExecutionStatus.SYNTAX_ERROR, holder['error']
    data = holder['data']
    status = SparqlExecutionStatus.SUCCESS if data['total'] else SparqlExecutionStatus.EMPTY_RESULT
    return data, status, None


def execute_sparql(query: str, return_status: bool = False, timeout: int = 30, result_limit: int = None):
    import re
    if result_limit and not re.search(r'LIMIT\s+\d+', query, re.I) and re.search(r'\bSELECT\b', query, re.I):
        query = query.rstrip().rstrip(';') + f' LIMIT {int(result_limit)}'
    data, status, error = query_graph(query, timeout=timeout)
    rows = data['rows'] if data else []
    if error:
        print(f'[SPARQL] {error}')
    return (rows, status) if return_status else rows


def search_brick(search_term: str, limit: int = 8, search_type: str = "all") -> List[Dict]:
    return call_author_tool(BrickGraph(), 'search_brick', search_term, limit, search_type)


def get_brick_entity(entity_id: str, compact: bool = True) -> Dict:
    return call_author_tool(BrickGraph(), 'get_brick_entity', entity_id, compact)


def get_property_examples(property_name: str, limit: int = 5) -> List[Tuple[str, str, str]]:
    return call_author_tool(BrickGraph(), 'get_property_examples', property_name, limit)


def _clear_author_caches():
    for tool in getattr(BrickGraph(), '_author_functions', {}).values():
        if hasattr(tool, 'cache_clear'):
            tool.cache_clear()


search_brick.cache_clear = _clear_author_caches
get_brick_entity.cache_clear = _clear_author_caches


def get_all_sensor_types() -> List[str]:
    """
    Get all sensor types available in the Brick schema.

    Returns:
        List of sensor type names
    """
    graph = BrickGraph().get_graph()

    query = """
    SELECT DISTINCT ?sensorType
    WHERE {
        ?sensor rdf:type ?sensorType .
        FILTER(CONTAINS(STR(?sensorType), "Sensor") || CONTAINS(STR(?sensorType), "Point"))
    }
    """

    sensor_types = []
    results = graph.query(BRICK_PREFIXES + query)

    for row in results:
        sensor_type = str(row.sensorType).split('#')[-1]
        sensor_types.append(sensor_type)

    return sorted(sensor_types)


def format_search_results(results: List[Dict], language: str = "zh") -> str:
    """
    Format search results for display to LLM.

    Args:
        results: List of search result dicts

    Returns:
        Formatted string
    """
    if not results:
        return "No results found." if language == "en" else "未找到结果。"

    lines = []
    for item in results:
        label = item.get("label", item.get("id", ""))
        id_ = item.get("uri", item.get("id", ""))
        type_ = item.get("type", "")
        desc = item.get("description", "")
        lines.append(f"{label} ({id_}): {desc}")
        if type_:
            lines.append(f"  {'Type' if language == 'en' else '类型'}: {type_}")

    return "\n".join(lines)


def format_entity_info(entity_info: Dict, language: str = "zh") -> str:
    """
    Format entity information for display to LLM.

    Args:
        entity_info: Entity info dict from get_brick_entity()

    Returns:
        Formatted string
    """
    if entity_info.get("error"):
        from prompting import feedback
        return feedback(entity_info["error"], language)
    lines = [f"Entity: {entity_info['entity']} ({entity_info.get('uri', '')})"]

    if entity_info.get('types'):
        lines.append(f"{'Types' if language == 'en' else '类型'}: {', '.join(entity_info['types'])}")

    lines.append("\nProperties:" if language == "en" else "\n属性:")
    for prop_name, values in entity_info.get('properties', {}).items():
        lines.append(f"  {prop_name}:")
        for val in values[:3]:  # Limit to first 3 values
            if val.get('type') == 'uri':
                lines.append(f"    -> {val['value']}")
            else:
                lines.append(f"    = {val['value']}")

    return "\n".join(lines)
