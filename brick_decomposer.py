"""
Brick Query Decomposer
Decomposes natural language queries into structured components:
- Sensors mentioned (primary focus)
"""

import json
import os
from typing import Dict, List, Optional
from dataclasses import dataclass
import time

try:
    from llm_client import get_client
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    print("Warning: llm_client not available. Decomposer will run in mock mode.")


@dataclass
class SensorMention:
    """Represents a sensor mentioned in the query"""
    mention: str  # Original text from question
    sensor_id: str  # Mapped sensor ID (e.g., FCU_OAT)
    description: str  # What this sensor measures


@dataclass
class TemporalConstraint:
    """Represents temporal requirements in the query"""
    has_constraint: bool
    type: str  # latest, recent_n, oldest_n, range, specific, period, trend, none
    details: Dict  # Specific values (limit, dates, etc.)
    sparql_pattern: str  # How to express in SPARQL


@dataclass
class AggregationRequirement:
    """Represents aggregation/analysis requirements"""
    required: bool
    operations: List[str]  # MIN, MAX, AVG, COUNT, etc.
    conditions: List[str]  # Additional FILTER conditions


@dataclass
class QueryDecomposition:
    """Complete decomposition of a user query"""
    sensors: List[SensorMention]
    sensor_count: int
    temporal: TemporalConstraint  # Empty when the temporal module is disabled
    aggregation: AggregationRequirement  # Empty when the operations module is disabled
    query_intent: str
    raw_json: Dict  # Original JSON response


class BrickQueryDecomposer:
    """
    Decomposes natural language queries about building data into structured components.
    This preprocessing step helps the main agent generate better SPARQL queries.
    """

    def __init__(self, model: str = None, project: str = None):
        """
        Initialize the decomposer.

        Args:
            model: Model name. If None, read from LLM_MODEL env var (default: qwen-plus).
            project: Deprecated, kept for backward compatibility. Ignored.
        """
        import os
        self.model_name = model or os.getenv("LLM_MODEL", "qwen-plus")
        self.cooldown_seconds = 0
        self.last_usage = None

    def should_decompose(self, question: str) -> bool:
        """
        Determine if a question needs decomposition.
        Uses lightweight heuristics to avoid unnecessary LLM calls.

        Note: Focuses on sensor/entity detection for complex multi-sensor queries.
        Temporal constraints and aggregations are handled by other components.

        Args:
            question: Natural language question

        Returns:
            True if decomposition is needed, False otherwise
        """
        import re

        if any(k in question for k in ("昨天", "最近", "小时", "期间", "当前", "最新")):
            return True

        # 中文问题支持：基于中文字符数与中文关键词判断是否分解
        # （原逻辑依赖空格分词与英文关键词，对无空格的中文整句会误判为简单查询）
        if re.search(r'[一-鿿]', question):
            cjk_multi = ["和", "与", "以及", "各个", "每个", "各", "都", "同时", "所有", "两者", "分别"]
            cjk_compare = ["比较", "对比", "差异", "差值", "之比", "比率", "区别", "相对于"]
            cjk_complex = ["超过", "低于", "高于", "小于", "大于", "之间", "如果", "当", "哪些", "哪个",
                           "哪间", "哪里", "如何", "怎么", "为什么", "多少", "平均", "最大", "最小", "总计", "求和", "按"]
            if any(k in question for k in cjk_multi):
                return True
            if any(k in question for k in cjk_compare):
                return True
            if any(k in question for k in cjk_complex):
                return True
            if len(re.findall(r'[一-鿿]', question)) > 20:
                return True
            return False

        question_lower = question.lower()
        if any(k in question for k in ("平均", "最大", "最小", "比较", "超过", "昨天", "最近", "小时", "期间", "之间", "当前", "最新")):
            return True

        # Helper function to check for whole word matches
        def has_word(text: str, word: str) -> bool:
            """Check if word exists as a whole word in text"""
            return bool(re.search(r'\b' + re.escape(word) + r'\b', text))

        # Check for multiple sensor indicators (these can be substrings)
        multi_sensor_keywords = [
            " and ", " or ", ",",  # Conjunctions
            "all ", "both ", "each ",  # Quantifiers
        ]

        # Check for comparison keywords (whole words)
        comparison_keywords = [
            "compare", "versus", "vs", "between"
        ]

        # Check for complexity indicators
        complex_keywords = [
            "where", "which", "that",  # Conditional clauses
            "outside", "exceed", "below", "above",  # Comparisons
            "difference", "delta", "change"  # Calculations
        ]

        # Simple queries that DON'T need decomposition:
        # - "What is the [sensor]?"
        # - "Show me [sensor]"
        simple_patterns = [
            len(question.split()) <= 6 and not any(kw in question_lower for kw in multi_sensor_keywords)
        ]

        # If it matches a simple pattern, no decomposition needed
        if any(simple_patterns):
            # But only if no complexity indicators
            has_complexity = (
                any(kw in question_lower for kw in multi_sensor_keywords) or
                any(has_word(question_lower, kw) for kw in comparison_keywords) or
                any(has_word(question_lower, kw) for kw in complex_keywords)
            )
            if not has_complexity:
                return False

        # Decompose if:
        # 1. Mentions multiple sensors or comparisons
        if any(kw in question_lower for kw in multi_sensor_keywords):
            return True

        if any(has_word(question_lower, kw) for kw in comparison_keywords):
            return True

        # 2. Has complex conditions - use word boundaries
        if any(has_word(question_lower, kw) for kw in complex_keywords):
            return True

        # 3. Question is long and potentially complex
        if len(question.split()) > 12:
            return True

        # Otherwise, simple query - no decomposition needed
        return False

    def decompose(self, question: str, verbose: bool = True, cancel_event=None, context: str = "", language: str = "zh", *, use_temporal: bool = True, use_aggregation: bool = True) -> QueryDecomposition:
        """
        Decompose a natural language question into structured components.

        Args:
            question: Natural language question about building data
            verbose: If True, print decomposition results

        Returns:
            QueryDecomposition object with extracted components
        """
        from prompting import validate_language, MODEL_PROMPT_LANGUAGE
        validate_language(language)
        language = MODEL_PROMPT_LANGUAGE
        self.last_fallback = False
        self.last_usage = None
        self.last_prompt = None
        if not LLM_AVAILABLE:
            self.last_fallback = True
            return self._mock_decompose(question)

        try:
            # Rate limiting. Configurable via BRICK_DECOMP_COOLDOWN; default 6.5s.
            dc = float(os.getenv("BRICK_DECOMP_COOLDOWN", "0"))
            self.cooldown_seconds += dc
            if cancel_event is not None and cancel_event.wait(dc):
                raise RuntimeError("查询已取消")
            if cancel_event is None:
                time.sleep(dc)

            from prompting import build_decomposition_prompt, save_prompt_snapshot
            prompt = build_decomposition_prompt(question, language, context,
                                                use_temporal=use_temporal, use_aggregation=use_aggregation)

            # Call Qwen (or any configured OpenAI-compatible model)
            client = get_client()
            self.last_prompt = save_prompt_snapshot(prompt)
            response_text = client.generate_text(prompt, cancel_event=cancel_event)
            self.last_usage = client.last_usage

            # Parse JSON response
            # Extract JSON from markdown code blocks if present
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            decomp_json = json.loads(response_text)

            # Convert to structured objects
            decomposition = self._json_to_decomposition(decomp_json, use_temporal=use_temporal,
                                                         use_aggregation=use_aggregation)

            if verbose:
                self._print_decomposition(decomposition)

            return decomposition

        except Exception as e:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("查询已取消") from e
            print(f"[ERROR] Decomposition failed: {e}")
            print("[INFO] Falling back to mock decomposition")
            self.last_fallback = True
            return self._mock_decompose(question)

    def _json_to_decomposition(self, json_data: Dict, *, use_temporal=True, use_aggregation=True) -> QueryDecomposition:
        """Convert JSON response to QueryDecomposition object"""
        # Enforce the requested modules even if a model emits extra fields.
        json_data = dict(json_data)
        if not use_temporal:
            json_data.pop('temporal', None)
        if not use_aggregation:
            json_data.pop('aggregation', None)

        # Parse sensors
        sensors = [
            SensorMention(
                mention=s["mention"],
                sensor_id=s["sensor_id"],
                description=s["description"]
            )
            for s in json_data.get("sensors", [])
        ]

        # Parse temporal constraints from JSON
        temporal_data = json_data.get("temporal", {})
        temporal = TemporalConstraint(
            has_constraint=temporal_data.get("has_constraint", False),
            type=temporal_data.get("type", "none"),
            details=temporal_data.get("details", {}),
            sparql_pattern=temporal_data.get("sparql_pattern", "")
        )

        # Parse aggregation requirements from JSON
        agg_data = json_data.get("aggregation", {})
        aggregation = AggregationRequirement(
            required=agg_data.get("required", False),
            operations=agg_data.get("operations", []),
            conditions=agg_data.get("conditions", [])
        )

        return QueryDecomposition(
            sensors=sensors,
            sensor_count=json_data.get("sensor_count", len(sensors)),
            temporal=temporal,
            aggregation=aggregation,
            query_intent=json_data.get("query_intent", ""),
            raw_json=json_data
        )

    def _print_decomposition(self, decomp: QueryDecomposition):
        """Pretty print decomposition results"""
        print("\n" + "="*80)
        print("QUERY DECOMPOSITION")
        print("="*80)

        print(f"\n📊 Intent: {decomp.query_intent}")

        print(f"\n🔍 Sensors ({decomp.sensor_count}):")
        for sensor in decomp.sensors:
            print(f"  • {sensor.mention} → {sensor.sensor_id}")
            print(f"    ({sensor.description})")

        if decomp.temporal.has_constraint:
            print(f"\n⏰ Temporal: {decomp.temporal.type}")
            if decomp.temporal.details:
                print(f"    Details: {decomp.temporal.details}")
        else:
            print("\n⏰ Temporal: None")

        if decomp.aggregation.required:
            print(f"📈 Aggregation: {', '.join(decomp.aggregation.operations)}")
            if decomp.aggregation.conditions:
                print(f"    Conditions: {decomp.aggregation.conditions}")
        else:
            print("📈 Aggregation: None")

        print("="*80 + "\n")

    def _mock_decompose(self, question: str) -> QueryDecomposition:
        """Mock decomposition for testing without LLM"""

        # Simple keyword-based mock
        sensors = []
        if "room temperature" in question.lower() or "rm_temp" in question.lower():
            sensors.append(SensorMention(
                mention="room temperature",
                sensor_id="RM_TEMP",
                description="Room air temperature"
            ))

        if "outdoor" in question.lower() and "temperature" in question.lower():
            sensors.append(SensorMention(
                mention="outdoor temperature",
                sensor_id="FCU_OAT",
                description="Outdoor air temperature"
            ))

        # Temporal constraints are deactivated - always return no constraint
        temporal = TemporalConstraint(
            has_constraint=False,
            type="none",
            details={},
            sparql_pattern=""
        )

        # Aggregation is deactivated - always return not required
        aggregation = AggregationRequirement(
            required=False,
            operations=[],
            conditions=[]
        )

        return QueryDecomposition(
            sensors=sensors,
            sensor_count=len(sensors),
            temporal=temporal,
            aggregation=aggregation,
            query_intent=f"Mock decomposition of: {question}",
            raw_json={}
        )


# Simple test function
def test_decomposer():
    """Test the decomposer with sample questions"""
    decomposer = BrickQueryDecomposer()

    test_questions = [
        "What is the latest room temperature?",
        "Show me the cooling and heating valve positions on 12/15/2018",
        "What was the average outdoor temperature between 06/01/2018 and 06/30/2018?",
        "Show me room temperature over time"
    ]

    for question in test_questions:
        print(f"\n{'='*80}")
        print(f"Question: {question}")
        print('='*80)

        decomposition = decomposer.decompose(question, verbose=True)


if __name__ == "__main__":
    test_decomposer()
