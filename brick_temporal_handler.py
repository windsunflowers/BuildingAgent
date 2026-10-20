"""
Brick Temporal Handler
Handles temporal constraints separately after decomposition.
Applies temporal patterns (ORDER BY, FILTER, LIMIT) to SPARQL queries.
Also provides validation functions for sensor coverage and aggregations.
"""

import re
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass
from brick_decomposer import QueryDecomposition


@dataclass
class TemporalApplication:
    """Result of applying temporal constraints to a SPARQL query"""
    original_sparql: str
    modified_sparql: str
    temporal_type: str
    pattern_applied: str
    was_modified: bool


class BrickTemporalHandler:
    """
    Handles temporal constraints for Brick SPARQL queries.
    Applies ORDER BY, FILTER, and LIMIT clauses based on temporal type.
    """

    def __init__(self, default_year: Optional[str] = None):
        """
        Initialize the temporal handler.

        Args:
            default_year: Default year to use when dates don't specify a year (e.g., "2018")
        """
        self.default_year = default_year

    def apply_temporal_constraint(
        self,
        sparql: str,
        decomposition: Optional[QueryDecomposition] = None,
        temporal_type: Optional[str] = None,
        details: Optional[Dict] = None
    ) -> TemporalApplication:
        """
        Apply temporal constraints to a SPARQL query.

        Args:
            sparql: Base SPARQL query (without temporal constraints)
            decomposition: Query decomposition object (if available)
            temporal_type: Temporal type (if decomposition not provided)
            details: Temporal details (if decomposition not provided)

        Returns:
            TemporalApplication object with modified query
        """
        # Extract temporal info from decomposition or parameters
        if decomposition and decomposition.temporal.has_constraint:
            temporal_type = decomposition.temporal.type
            details = decomposition.temporal.details
            pattern = decomposition.temporal.sparql_pattern
        elif temporal_type and details:
            pattern = self._generate_pattern(temporal_type, details)
        else:
            # No temporal constraint
            return TemporalApplication(
                original_sparql=sparql,
                modified_sparql=sparql,
                temporal_type="none",
                pattern_applied="",
                was_modified=False
            )

        # Apply the temporal pattern
        modified_sparql = self._apply_pattern(sparql, temporal_type, pattern, details)

        return TemporalApplication(
            original_sparql=sparql,
            modified_sparql=modified_sparql,
            temporal_type=temporal_type,
            pattern_applied=pattern,
            was_modified=(sparql != modified_sparql)
        )

    def _generate_pattern(self, temporal_type: str, details: Dict) -> str:
        """Generate SPARQL pattern from temporal type and details"""
        if temporal_type == "latest":
            return "ORDER BY DESC(?timestamp) LIMIT 1"
        elif temporal_type == "recent_n":
            limit = details.get("limit", 10)
            return f"ORDER BY DESC(?timestamp) LIMIT {limit}"
        elif temporal_type == "oldest_n":
            limit = details.get("limit", 10)
            return f"ORDER BY ?timestamp LIMIT {limit}"
        elif temporal_type == "trend":
            limit = details.get("limit", 100)
            return f"ORDER BY ?timestamp LIMIT {limit}"
        elif temporal_type == "range":
            start = details.get("start_date", "")
            end = details.get("end_date", "")
            return f'FILTER(?timestamp >= "{start}" && ?timestamp <= "{end}")'
        elif temporal_type == "specific":
            specific = details.get("specific_time", "")
            return f'FILTER(CONTAINS(?timestamp, "{specific}"))'
        else:
            return ""

    def _apply_pattern(
        self,
        sparql: str,
        temporal_type: str,
        pattern: str,
        details: Dict
    ) -> str:
        """
        Apply temporal pattern to SPARQL query.
        Handles both ORDER BY and FILTER patterns.
        """
        # Check if query already has this temporal constraint
        if self._has_temporal_constraint(sparql, temporal_type):
            print(f"[INFO] Query already has {temporal_type} constraint, skipping")
            return sparql

        # Remove existing ORDER BY and LIMIT if we're adding new ones
        if "ORDER BY" in pattern:
            sparql = self._remove_existing_order_limit(sparql)

        # Apply FILTER pattern
        if pattern.startswith("FILTER"):
            sparql = self._add_filter(sparql, pattern)

        # Apply ORDER BY pattern
        elif "ORDER BY" in pattern:
            sparql = self._add_order_by(sparql, pattern)

        return sparql

    def _has_temporal_constraint(self, sparql: str, temporal_type: str) -> bool:
        """Check if query already has the temporal constraint"""
        sparql_upper = sparql.upper()

        if temporal_type in ["latest", "recent_n", "oldest_n", "trend"]:
            # Check for ORDER BY
            return "ORDER BY" in sparql_upper
        elif temporal_type in ["range", "specific"]:
            # Check for FILTER on timestamp
            return bool(re.search(r'FILTER.*\?timestamp', sparql, re.IGNORECASE))

        return False

    def _remove_existing_order_limit(self, sparql: str) -> str:
        """Remove existing ORDER BY and LIMIT clauses"""
        # Remove ORDER BY clause
        sparql = re.sub(r'\s*ORDER\s+BY\s+(?:DESC|ASC)?\s*\([^\)]+\)', '', sparql, flags=re.IGNORECASE)
        sparql = re.sub(r'\s*ORDER\s+BY\s+\S+', '', sparql, flags=re.IGNORECASE)

        # Remove LIMIT clause
        sparql = re.sub(r'\s*LIMIT\s+\d+', '', sparql, flags=re.IGNORECASE)

        return sparql.strip()

    def _add_filter(self, sparql: str, filter_clause: str) -> str:
        """Add FILTER clause to WHERE block"""
        # Find the closing brace of WHERE block
        where_match = re.search(r'WHERE\s*\{', sparql, re.IGNORECASE)
        if not where_match:
            print("[WARNING] No WHERE clause found, cannot add FILTER")
            return sparql

        # Find the matching closing brace
        start_pos = where_match.end()
        brace_depth = 1
        pos = start_pos

        while pos < len(sparql) and brace_depth > 0:
            if sparql[pos] == '{':
                brace_depth += 1
            elif sparql[pos] == '}':
                brace_depth -= 1
            pos += 1

        if brace_depth == 0:
            # Insert FILTER before closing brace
            insert_pos = pos - 1
            # Add newline and indent
            filter_with_formatting = f"\n  {filter_clause}\n"
            modified = sparql[:insert_pos] + filter_with_formatting + sparql[insert_pos:]
            return modified
        else:
            print("[WARNING] Could not find matching brace for WHERE clause")
            return sparql

    def _add_order_by(self, sparql: str, order_pattern: str) -> str:
        """Add ORDER BY and LIMIT after WHERE block"""
        # Simply append to end of query
        sparql = sparql.rstrip()

        # Extract ORDER BY and LIMIT from pattern
        order_by_match = re.search(r'ORDER BY\s+(?:DESC|ASC)?\s*\([^\)]+\)', order_pattern, re.IGNORECASE)
        if not order_by_match:
            order_by_match = re.search(r'ORDER BY\s+\S+', order_pattern, re.IGNORECASE)

        limit_match = re.search(r'LIMIT\s+\d+', order_pattern, re.IGNORECASE)

        result = sparql

        if order_by_match:
            result += f"\n{order_by_match.group(0)}"

        if limit_match:
            result += f"\n{limit_match.group(0)}"

        return result

    def validate_temporal_query(
        self,
        sparql: str,
        decomposition: Optional[QueryDecomposition] = None
    ) -> Tuple[bool, str]:
        """
        Validate that temporal constraints are correctly applied.
        If decomposition is provided, validates against expected temporal type.

        Args:
            sparql: SPARQL query to validate
            decomposition: Optional QueryDecomposition with expected temporal constraints

        Returns:
            (is_valid, message) tuple
        """
        if not decomposition or not decomposition.temporal.has_constraint:
            return True, "No temporal constraint requested"
        kind = decomposition.temporal.type
        timestamp_vars = re.findall(r'(?:ref:hasTimestamp|<https://brickschema.org/schema/Brick/ref#hasTimestamp>)\s+(\?\w+)', sparql, re.I)
        if not timestamp_vars:
            return False, '缺少观测时间戳，无法验证时间约束'
        if kind in ('latest', 'recent_n', 'oldest_n', 'trend'):
            ordered = bool(re.search(r'ORDER\s+BY[\s\S]*?\?\w+', sparql, re.I))
            latest_filter = bool(re.search(r'FILTER\s+NOT\s+EXISTS', sparql, re.I))
            extremum = bool(re.search(r'MAX\s*\(\s*\?\w+', sparql, re.I))
            limited = bool(re.search(r'LIMIT\s+\d+', sparql, re.I))
            if not ((ordered and limited) or latest_filter or extremum):
                return False, f'时间约束 {kind} 需要时间排序与 LIMIT，或按测点筛选最新时间戳'
        elif kind in ('range', 'specific', 'date_range', 'specific_date', 'yesterday', 'last_n_hours', 'period'):
            if not re.search(r'FILTER[\s\S]*(?:' + '|'.join(re.escape(v) for v in timestamp_vars) + ')', sparql, re.I):
                return False, f'时间约束 {kind} 缺少时间戳 FILTER'
            details = decomposition.temporal.details
            dates = [str(details.get(k, '')) for k in ('date', 'start', 'end', 'start_date', 'end_date')]
            for date in dates:
                if re.match(r'^\d{4}-\d{2}-\d{2}', date) and date[:10] not in sparql:
                    return False, f'查询未包含请求的日期 {date[:10]}'
        return True, "Temporal constraints pass structural checks"








def should_use_temporal_guide(decomposition: QueryDecomposition) -> bool:
    """
    Decide whether to inject temporal guide based on complexity.

    Simple patterns (latest, trend) → Skip guide, use handler directly (faster)
    Complex patterns (range, relative dates) → Use guide (more flexible)

    Args:
        decomposition: QueryDecomposition with temporal information

    Returns:
        True if guide should be used, False otherwise
    """
    if not decomposition or not decomposition.temporal.has_constraint:
        return False

    temporal_type = decomposition.temporal.type

    # Simple patterns - handler can apply directly (fast, deterministic)
    # These have well-defined SPARQL patterns that don't need LLM interpretation
    SIMPLE_PATTERNS = ["latest", "recent_n", "oldest_n", "trend"]

    # Complex patterns - LLM with guide is better (flexible, contextual)
    # These may require date parsing, relative time calculations, etc.
    COMPLEX_PATTERNS = ["range", "specific", "relative", "period"]

    if temporal_type in SIMPLE_PATTERNS:
        return False  # Skip guide - handler will apply pattern directly
    elif temporal_type in COMPLEX_PATTERNS:
        return True  # Use guide - LLM can handle complexity better
    else:
        # Unknown type - use guide to be safe
        return True


def test_temporal_handler():
    """Test the temporal handler"""
    handler = BrickTemporalHandler()

    # Base query without temporal constraints
    base_query = """SELECT ?timestamp ?temperature
WHERE {
  bldg:RM_TEMP ref:hasObservation ?obs .
  ?obs ref:hasTimestamp ?timestamp .
  ?obs ref:hasValue ?temperature .
}"""

    print("="*80)
    print("TEMPORAL HANDLER TEST")
    print("="*80)

    # Test 1: Latest
    print("\nTest 1: Apply 'latest' pattern")
    print("-"*80)
    result = handler.apply_temporal_constraint(
        base_query,
        temporal_type="latest",
        details={"limit": 1}
    )
    print(f"Temporal type: {result.temporal_type}")
    print(f"Pattern: {result.pattern_applied}")
    print(f"Modified: {result.was_modified}")
    print(f"\nResult:\n{result.modified_sparql}")

    # Test 2: Date range
    print("\n" + "="*80)
    print("Test 2: Apply 'range' pattern")
    print("-"*80)
    result = handler.apply_temporal_constraint(
        base_query,
        temporal_type="range",
        details={"start_date": "06/01/2018 00:00", "end_date": "06/30/2018 23:59"}
    )
    print(f"Temporal type: {result.temporal_type}")
    print(f"Pattern: {result.pattern_applied}")
    print(f"Modified: {result.was_modified}")
    print(f"\nResult:\n{result.modified_sparql}")

    # Test 3: Validation without decomposition
    print("\n" + "="*80)
    print("Test 3: Validate temporal query (without decomposition)")
    print("-"*80)
    valid, message = handler.validate_temporal_query(result.modified_sparql)
    print(f"Valid: {valid}")
    print(f"Message: {message}")

    # Test 4: Validation with decomposition
    print("\n" + "="*80)
    print("Test 4: Validate query missing temporal constraint")
    print("-"*80)
    # Create a mock decomposition
    from brick_decomposer import TemporalConstraint, SensorMention, AggregationRequirement
    mock_temporal = TemporalConstraint(
        has_constraint=True,
        type="latest",
        details={"limit": 1},
        sparql_pattern="ORDER BY DESC(?timestamp) LIMIT 1"
    )

    class MockDecomposition:
        def __init__(self):
            self.temporal = mock_temporal

    # Test with query missing temporal constraint
    invalid_query = base_query  # Base query without temporal constraints
    valid, message = handler.validate_temporal_query(invalid_query, MockDecomposition())
    print(f"Valid: {valid}")
    print(f"Message: {message}")


if __name__ == "__main__":
    test_temporal_handler()

# Author validation is diagnostic only.
from third_party.brickqa_upstream.brick_temporal_handler import (
    validate_sensor_coverage, validate_aggregation, validate_multi_sensor_joins,
)
