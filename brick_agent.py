import threading
from prompting import build_controller_prompt, validate_language, feedback, MODEL_PROMPT_LANGUAGE
"""
Brick Agent
An iterative framework for converting natural language questions to Brick SPARQL queries.
Uses a part-to-whole approach to build queries incrementally.
"""

import sys
import io
import time

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    try:
        if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except (AttributeError, ValueError):
        pass  # stdout already configured or not available

import json
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from implementation_policy import policy_metadata, evaluation_policy
from third_party.brickqa_upstream import brick_temporal_handler as author_validation
import pandas as pd

from brick_utils import (
    BrickGraph,
    execute_sparql,
    search_brick,
    get_brick_entity,
    get_property_examples,
    format_search_results,
    format_entity_info,
    SparqlExecutionStatus,
    BRICK_PREFIXES, graph_prefixes, prepare_query, namespace_map, query_graph
)
from brick_decomposer import BrickQueryDecomposer, QueryDecomposition
from brick_temporal_handler import (
    BrickTemporalHandler,
    TemporalApplication,
    should_use_temporal_guide
)



@dataclass
class BrickAction:
    """
    Represents a single action in the reasoning chain.
    Follows the Thought-Action-Observation pattern.
    """
    thought: str
    action_name: str
    action_argument: str
    observation: Optional[str] = None
    observation_raw: Optional[any] = None
    diagnostics: Optional[dict] = None

    POSSIBLE_ACTIONS = [
        "search_brick",           # Search for entities/sensors
        "get_brick_entity",       # Explore entity properties
        "get_property_examples",  # See how properties are used
        "execute_sparql",         # Test SPARQL query
        "stop",                   # Finalize answer
        "error"                   # Internal error handling (retry logic)
    ]

    def __post_init__(self):
        if self.action_name not in self.POSSIBLE_ACTIONS:
            raise ValueError(f"Invalid action: {self.action_name}. Must be one of {self.POSSIBLE_ACTIONS}")

    def to_string(self, include_observation: bool = True) -> str:
        """Format action for display"""
        result = f"Thought: {self.thought}\n"
        result += f"Action: {self.action_name}({self.action_argument})\n"
        if include_observation and self.observation:
            result += f"Observation: {self.observation}\n"
        return result

    def __eq__(self, other):
        """Check if two actions are duplicates"""
        if not isinstance(other, BrickAction):
            return False
        return (self.action_name == other.action_name and
                self.action_argument == other.action_argument)

    def __hash__(self):
        return hash((self.action_name, self.action_argument))


@dataclass
class BrickSparqlQuery:
    """Represents a SPARQL query with its execution results"""
    sparql: str
    execution_result: Optional[List[Dict]] = None
    execution_status: Optional[SparqlExecutionStatus] = None
    result_limit: Optional[int] = None  # Limit results during execution
    validation_warnings: List[str] = field(default_factory=list)
    diagnostic_warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    bindings: List[Dict] = field(default_factory=list)
    execution_variables: List[str] = field(default_factory=list)

    def execute(self, isolated=True):
        """Execute the SPARQL query"""
        timeout = evaluation_policy()['sparql_timeout_seconds']
        from third_party.brickqa_upstream.brick_utils import BRICK_PREFIXES
        # Author executor only prepends its fixed defaults when no PREFIX occurs.
        query = self.sparql if 'PREFIX' in self.sparql.upper() else BRICK_PREFIXES + self.sparql
        data, self.execution_status, self.error = query_graph(
            query, isolated=isolated, timeout=timeout, include_bindings=True, prepare_prefixes=False)
        self.execution_result = data['rows'] if data else []
        self.bindings = data.get('bindings', []) if data else []
        self.execution_variables = list(data['vars']) if data else []

    def has_results(self) -> bool:
        """Check if query returned results"""
        return bool(self.execution_result)

    def results_as_table(self, max_rows: int = 10) -> str:
        """Format results as a text table"""
        if not self.execution_result:
            return "No results"

        # Results are already in simple dict format, convert directly to DataFrame
        df = pd.DataFrame(self.execution_result)

        if len(df) > max_rows:
            # Show first and last rows
            half = max_rows // 2
            top = df.head(half)
            bottom = df.tail(max_rows - half)
            result = top.to_string(index=False) + f"\n... ({len(df) - max_rows} rows omitted) ...\n" + bottom.to_string(index=False, header=False)
        else:
            result = df.to_string(index=False)

        return result


@dataclass
class AgentState:
    """Maintains the state of the Brick agent"""
    question: str
    actions: List[BrickAction] = field(default_factory=list)
    generated_sparqls: List[BrickSparqlQuery] = field(default_factory=list)
    final_sparql: Optional[BrickSparqlQuery] = None
    max_iterations: int = 15
    decomposition: Optional[QueryDecomposition] = None  # Query decomposition results
    decomposition_fallback: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cooldown_seconds: float = 0
    mode: str = "paper"
    language: str = "en"
    implementation_mode: str = 'upstream'
    phase: str = "准备查询"
    warnings: List[str] = field(default_factory=list)
    stop_reason: Optional[str] = None
    model_configuration: dict = field(default_factory=dict)
    response_models: List[str] = field(default_factory=list)
    decomposition_policy: dict = field(default_factory=dict)
    interface_language: str = 'zh'

    def get_action_history(self, last_n: int = 10, include_observation: bool = True) -> str:
        """Get formatted action history for context"""
        recent_actions = self.actions[-last_n:] if len(self.actions) > last_n else self.actions

        history = []
        for i, action in enumerate(recent_actions):
            # Skip observations for search/get actions in the middle
            should_include_obs = include_observation
            if i < len(recent_actions) - 2 and action.action_name in ["search_brick", "get_brick_entity"]:
                should_include_obs = False

            history.append(action.to_string(include_observation=should_include_obs))

        return "\n".join(history)

    def is_duplicate_action(self, action: BrickAction) -> bool:
        """Check if action is a duplicate of recent actions"""
        return action in self.actions[-5:]

    def should_stop(self) -> bool:
        """Check if agent should stop (max iterations or stop action)"""
        if len(self.actions) >= self.max_iterations:
            return True
        if self.actions and self.actions[-1].action_name == "stop":
            return True
        return False


class BrickAgent:
    """
    Main agent class that implements the iterative approach for Brick SPARQL generation.
    """

    @property
    def language(self):
        """Actual model language is fixed; legacy assignments set display only."""
        return MODEL_PROMPT_LANGUAGE

    @language.setter
    def language(self, value):
        self.interface_language = validate_language(value)

    def __init__(self, engine: str = "gemini-flash", use_decomposer: bool = True, use_temporal_handler: bool = True, use_aggregation: bool = True, use_fewshot: bool = False, ttl_schema_file: str = None, schema_description_file: str = None, result_limit: int = None, language: str = "zh"):
        """
        Initialize the agent.

        Args:
            engine: LLM engine to use (e.g., 'gemini-flash', 'gemini-pro', 'gemini-flash-lite')
            use_decomposer: If True, use query decomposer as preprocessing step
            use_temporal_handler: If True, apply temporal constraints separately after SPARQL generation
            use_aggregation: If True, include aggregation info in prompt and validate aggregation
            use_fewshot: If True, include few-shot examples in the controller prompt
            ttl_schema_file: Path to .ttl schema file to include in prompt (optional)
            schema_description_file: Path to schema description .txt file (optional)
            result_limit: Limit results during query iterations (None = no limit)
            language: Display preference only; model prompts always use upstream English.
        """
        self.engine = engine
        self.language = validate_language(language)
        self.brick_graph = BrickGraph()
        self.implementation_mode = 'upstream'
        self.use_decomposer = use_decomposer
        self.use_temporal_handler = use_temporal_handler
        self.use_aggregation = use_aggregation
        self.use_fewshot = use_fewshot
        self.ttl_schema_file = ttl_schema_file
        self.ttl_schema_content = None
        self.schema_description = None
        self.result_limit = result_limit
        self.cancel_event = threading.Event()

        # Initialize decomposer
        if use_decomposer:
            self.decomposer = BrickQueryDecomposer()
            print("✅ Query decomposer initialized")
        else:
            self.decomposer = None
            print("⚠️ Running without query decomposer")

        # Initialize temporal handler
        if use_temporal_handler:
            self.temporal_handler = BrickTemporalHandler()
            print("✅ Temporal handler initialized")
        else:
            self.temporal_handler = None
            print("⚠️ Running without temporal handler")

        # Load few-shot examples if enabled
        if use_fewshot:
            try:
                with open("prompts/brick_controller_fewshot_examples.txt", "r", encoding="utf-8") as f:
                    self.fewshot_examples = f.read()
                print("✅ Few-shot examples loaded")
            except Exception as e:
                print(f"⚠️ Failed to load few-shot examples: {e}")
                self.fewshot_examples = None
        else:
            self.fewshot_examples = None
            print("⚠️ Running without few-shot examples")

        # Load TTL schema content if provided
        if ttl_schema_file:
            try:
                with open(ttl_schema_file, "r", encoding="utf-8") as f:
                    self.ttl_schema_content = f.read()
                print(f"✅ TTL schema loaded from {ttl_schema_file} ({len(self.ttl_schema_content)} chars)")
            except Exception as e:
                print(f"⚠️ Failed to load TTL schema: {e}")
                self.ttl_schema_content = None
        else:
            print("⚠️ Running without TTL schema in prompt")

        # Load schema description if provided
        if schema_description_file:
            try:
                with open(schema_description_file, "r", encoding="utf-8") as f:
                    self.schema_description = f.read()
                print(f"✅ Schema description loaded from {schema_description_file} ({len(self.schema_description)} chars)")
            except Exception as e:
                print(f"⚠️ Failed to load schema description: {e}")
                self.schema_description = None
        else:
            print("⚠️ Running without schema description")

        # Create timestamped log file for this agent instance
        from datetime import datetime
        import os
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create logs directory if it doesn't exist
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)

        from uuid import uuid4
        self.log_file = os.path.join(log_dir, f"prompt_logs_{timestamp}_{self.implementation_mode}_{uuid4().hex[:8]}.jsonl")
        print(f"📝 LLM logs will be saved to: {self.log_file}")

        # Dataset metadata (populated during initialization)
        self.dataset_date_range = (None, None)
        self.dataset_year = None

    def initialize_graph(self, ttl_file: str = None, csv_file: str = None, max_csv_rows: int = 100,
                         start_date: str = None, end_date: str = None):
        """
        Initialize the Brick graph with data.

        Args:
            ttl_file: Path to Turtle file with Brick schema
            csv_file: Path to CSV file with timeseries data
            max_csv_rows: Maximum rows to load from CSV
            start_date: Optional start date filter for timeseries (format: "YYYY-MM-DD")
            end_date: Optional end date filter for timeseries (format: "YYYY-MM-DD")
        """
        self.brick_graph.initialize(ttl_file=ttl_file)

        if csv_file:
            self.brick_graph.add_timeseries_data(csv_file, max_rows=max_csv_rows,
                                                  start_date=start_date, end_date=end_date)

        # Get date range after building
        self._extract_date_metadata()

        print(f"✅ Graph built successfully with {max_csv_rows} rows of data")

    def _extract_date_metadata(self):
        self.dataset_date_range = self.brick_graph.get_date_range()
        self.dataset_year = self.dataset_date_range[1][:4] if self.dataset_date_range[1] else None
        if self.temporal_handler:
            self.temporal_handler.default_year = self.dataset_year

    def _check_cancelled(self):
        if self.cancel_event.is_set():
            raise RuntimeError("查询已取消")

    def fork_evaluation(self):
        """Independent per-question state; the loaded graph stays read-only."""
        from copy import copy, deepcopy
        from uuid import uuid4
        from pathlib import Path
        worker = copy(self)
        worker.decomposer = deepcopy(self.decomposer)
        worker.temporal_handler = None
        worker.use_temporal_handler = False
        worker.use_aggregation = False
        worker.cancel_event = threading.Event()
        worker._current_state = None
        worker.log_file = str(Path(self.log_file).with_name('eval_prompt_' + uuid4().hex + '.jsonl'))
        return worker

    def _assert_graph(self):
        if self.brick_graph is not BrickGraph():
            raise RuntimeError('Agent graph is no longer active; reload the graph before running')

    def set_schema_context(self, size=0):
        """Context size never changes the execution graph. Serialization is deterministic."""
        if size not in (0, 100, 5000):
            raise ValueError('上下文必须为 0、100 或 5000 triples')
        if not size:
            self.ttl_schema_content = None
            return
        from rdflib import Graph
        source = self.brick_graph.source_graph
        subset = Graph()
        for prefix, uri in source.namespaces():
            subset.bind(prefix, uri)
        for triple in sorted(source, key=lambda t: tuple(map(str, t)))[:size]:
            subset.add(triple)
        self.ttl_schema_content = subset.serialize(format='turtle')

    def controller(self, state: AgentState) -> BrickAction:
        """
        The controller decides the next action based on the question and history.
        This is the "brain" of the agent.

        Args:
            state: Current agent state

        Returns:
            Next action to take
        """

        try:
            # Use OpenAI-compatible API (Qwen via DashScope by default) instead of Vertex AI
            from llm_client import get_client
            from datetime import datetime
            import time
            import os as _os

            # Rate limiting: Add delay to avoid 429 errors.
            # Cooldown is configurable via BRICK_COOLDOWN_PRE so the UI can run
            # snappily; the default preserves the original 6s behavior.
            pre_cd = float(_os.getenv("BRICK_COOLDOWN_PRE", "0"))
            state.cooldown_seconds += pre_cd
            if self.cancel_event.wait(pre_cd):
                self._check_cancelled()

            # Initialize shared LLM client (reads LLM_BASE_URL / LLM_API_KEY / LLM_MODEL)
            client = get_client()
            if not state.model_configuration:
                state.model_configuration = {'model':client.model,
                    'provider':getattr(client, 'provider', None), 'base_url':getattr(client, 'base_url', None)}

            prompt, self._using_temporal_guide = build_controller_prompt(self, state)
            from prompting import save_prompt_snapshot
            prompt_reference = save_prompt_snapshot(prompt)
            self._log_to_jsonl(self.log_file, {'event':'model_request', 'language':self.language,
                                              'model':client.model, **prompt_reference})
            self._current_state.phase = '模型正在选择下一步'
            self._check_cancelled()
            controller_output = client.generate_text(prompt, cancel_event=self.cancel_event)
            response_model = getattr(client, 'last_response_model', None) or client.model
            if response_model not in state.response_models:
                state.response_models.append(response_model)
            self._check_cancelled()

            # Accumulate token usage
            if client.last_usage:
                um = client.last_usage
                state.prompt_tokens += um.get("prompt_tokens", 0) or 0
                state.completion_tokens += um.get("completion_tokens", 0) or 0
                state.total_tokens += um.get("total_tokens", 0) or 0

            # Cooldown to avoid API quota limits (tracked separately from computation time).
            # Configurable via BRICK_COOLDOWN_POST; the default preserves the original 60s.
            post_cd = float(_os.getenv("BRICK_COOLDOWN_POST", "0"))
            state.cooldown_seconds += post_cd
            if self.cancel_event.wait(post_cd):
                self._check_cancelled()

            # Log to timestamped prompt_logs file
            self._log_to_jsonl(self.log_file, {
                "timestamp": datetime.now().isoformat(),
                "model": client.model,
                "response_model": response_model,
                "language": self.language,
                **prompt_reference,
                "prompt": prompt[:500] + "..." if len(prompt) > 500 else prompt,
                "response": controller_output
            })

            # Parse the response into BrickAction
            # Improved parsing to handle multiple formats and edge cases
            import re

            # Clean up the response - remove markdown code blocks
            cleaned_output = controller_output

            # Remove markdown code blocks (```sparql ... ```)
            cleaned_output = re.sub(r'```sparql\s*', '', cleaned_output)
            cleaned_output = re.sub(r'```', '', cleaned_output)

            # Stop at "Observation:" or "Output one" if present (LLM echoing prompt)
            stop_markers = ['Observation:', 'Output one "Thought"', 'Output one Thought']
            for marker in stop_markers:
                if marker in cleaned_output:
                    cleaned_output = cleaned_output.split(marker)[0]

            # Extract FIRST Thought and Action only (ignore multiple pairs)
            thought_match = re.search(r'Thought:\s*(.+?)(?=Action:|$)', cleaned_output, re.DOTALL)

            if thought_match:
                thought = thought_match.group(1).strip()
            else:
                # No explicit thought - check if output starts with Action directly
                if cleaned_output.strip().startswith('Action:'):
                    thought = "Continue with the next action"
                else:
                    # Try to extract any text before "Action:" as implicit thought
                    action_pos = cleaned_output.find('Action:')
                    if action_pos > 0:
                        thought = cleaned_output[:action_pos].strip()
                        if not thought:
                            thought = "Continue with the next action"
                    else:
                        raise ValueError(f"Could not find Thought or Action in output: {controller_output[:200]}...")
            # Try to extract action name and argument
            # Pattern 1: Action: action_name(argument)
            action_with_parens = re.search(r'Action:\s*(\w+)\s*\(', cleaned_output)

            if action_with_parens:
                action_name = action_with_parens.group(1).strip()

                # Find the argument by matching parentheses
                action_start = action_with_parens.end() - 1  # Position of opening (
                argument = self._extract_balanced_parens(cleaned_output[action_start:])

                if argument is None:
                    raise ValueError("Could not find matching parentheses for action argument")

                return BrickAction(
                    thought=thought,
                    action_name=action_name,
                    action_argument=argument.strip()
                )

            # Pattern 2: Action: just the SPARQL query (multiline, no action_name wrapper)
            action_content_match = re.search(r'Action:\s*(.+?)(?=\n\n|$)', cleaned_output, re.DOTALL)

            if action_content_match:
                action_content = action_content_match.group(1).strip()

                # If it starts with PREFIX, it's a SPARQL query
                if action_content.startswith('PREFIX') or action_content.startswith('SELECT'):
                    return BrickAction(
                        thought=thought,
                        action_name="execute_sparql",
                        action_argument=action_content
                    )

            # Fallback 1: Check if entire output (ignoring Thought) looks like a SPARQL query
            # This handles cases where LLM forgot to write "Action:" but output a query
            remaining_text = cleaned_output
            if thought_match:
                # Remove the thought part we already extracted
                remaining_text = cleaned_output[thought_match.end():].strip()

            if remaining_text.startswith('PREFIX') or remaining_text.startswith('SELECT'):
                print("[WARNING] LLM forgot 'Action:' label, but output looks like SPARQL - using it anyway")
                return BrickAction(
                    thought=thought if thought_match else "Executing query",
                    action_name="execute_sparql",
                    action_argument=remaining_text
                )

            # Fallback 2: Check if output contains "finish" anywhere
            if 'finish' in cleaned_output.lower():
                print("[WARNING] LLM output mentions 'finish' but format unclear - calling finish action")
                # Try to extract any answer after finish
                finish_match = re.search(r'finish\s*\((.+?)\)', cleaned_output, re.IGNORECASE | re.DOTALL)
                if finish_match:
                    answer = finish_match.group(1).strip().strip('"\'')
                else:
                    # Use the thought or remaining text as answer
                    answer = thought if thought_match else "Unable to determine answer"

                return BrickAction(
                    thought=thought if thought_match else "Concluding analysis",
                    action_name="stop",
                    action_argument=answer
                )

            # Could not parse - provide more context in error
            print(f"[ERROR] Failed to parse LLM output. Cleaned output:\n{cleaned_output[:800]}")
            raise ValueError(f"Could not parse LLM output. Output: {controller_output[:500]}...")

        except Exception as e:
            print(f"[ERROR] LLM controller failed: {e}")
            raise

    def _validate_and_fix_sparql(self, sparql: str) -> str:
        from implementation_policy import author_query_preprocessor
        return author_query_preprocessor()(self, sparql)

    def _extract_balanced_parens(self, text: str) -> Optional[str]:
        """
        Extract content between balanced parentheses.
        Handles nested parentheses like in SPARQL: DESC(?timestamp)

        Args:
            text: String starting with opening parenthesis

        Returns:
            Content between balanced parentheses (without outer parens), or None if unbalanced
        """
        if not text or text[0] != '(':
            return None

        depth = 0
        for i, char in enumerate(text):
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    # Found matching closing paren
                    return text[1:i]  # Return content without outer parens

        return None  # Unbalanced parentheses

    def _log_to_jsonl(self, filename: str, data: dict):
        """Log data to a JSONL file"""
        import json
        data = {**data, 'method_policy': policy_metadata(self.brick_graph)}
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        print(f"📝 Logged to {filename}")

    def execute_action(self, action: BrickAction) -> BrickAction:
        """
        Execute an action and populate its observation.

        Args:
            action: Action to execute

        Returns:
            Action with observation filled
        """
        self._assert_graph()
        self.brick_graph.last_tool_diagnostic = None
        # Preserve model-authored text and tool output verbatim in history.
        # All framework-owned feedback is English; localization belongs to the UI.
        try:
            if action.action_name == "search_brick":
                results = search_brick(action.action_argument)
                action.observation_raw = results
                action.observation = format_search_results(results, language='en')

            elif action.action_name == "get_brick_entity":
                entity_info = get_brick_entity(action.action_argument)
                action.observation_raw = entity_info
                action.observation = format_entity_info(entity_info, language='en')

            elif action.action_name == "get_property_examples":
                examples = get_property_examples(action.action_argument)
                action.observation_raw = examples
                if examples:
                    lines = [f"{subj} -- {prop} --> {obj}" for subj, prop, obj in examples]
                    action.observation = "\n".join(lines)
                else:
                    action.observation = "No examples found"

            elif action.action_name == "execute_sparql":
                print(f"\n[EXECUTE_SPARQL] Starting SPARQL query execution...")

                # Validate and fix SPARQL before execution
                corrected_sparql = self._validate_and_fix_sparql(action.action_argument)

                warnings = []
                decomp = getattr(getattr(self, '_current_state', None), 'decomposition', None)
                if decomp:
                    checks = []
                    if decomp.sensors:
                        checks.append(author_validation.validate_sensor_coverage(corrected_sparql, decomp))
                    if self.use_aggregation and decomp.aggregation.required:
                        checks.append(author_validation.validate_aggregation(corrected_sparql, decomp))
                    if len(decomp.sensors) > 1:
                        checks.append(author_validation.validate_multi_sensor_joins(corrected_sparql, decomp))
                    warnings = [feedback(msg, self.language) for valid, msg in checks if not valid]

                sparql_query = BrickSparqlQuery(sparql=corrected_sparql, result_limit=self.result_limit)

                try:
                    sparql_query.execute()
                except Exception as exec_error:
                    # Catch execution errors and provide helpful feedback
                    error_msg = str(exec_error).lower()
                    if "prefix" in error_msg or "namespace" in error_msg:
                        action.observation = f"PREFIX error: {exec_error}\n\nWrite every PREFIX URI inside angle brackets.\nRequired prefixes: brick:, bldg:, ref:, xsd:"
                    else:
                        action.observation = f"SPARQL execution error: {exec_error}"
                    return action, None

                sparql_query.diagnostic_warnings = warnings
                if warnings:
                    self._log_to_jsonl(self.log_file, {'event':'validation_diagnostic', 'warnings':warnings,
                                                      'blocking':False, 'sparql':corrected_sparql})
                action.observation_raw = sparql_query

                if sparql_query.has_results():
                    action.observation = sparql_query.results_as_table()
                else:
                    prefix = 'No results. Status: '
                    action.observation = prefix + sparql_query.execution_status.value

                if sparql_query.error:
                    label = '\nExecution error: '
                    action.observation += label + sparql_query.error
                # Store the SPARQL query
                return action, sparql_query

            elif action.action_name == "stop":
                action.observation = "Stopping execution"

            elif action.action_name == "error":
                # Error action for retry logic - observation already set
                # Just return the action without modification
                pass

            else:
                action.observation = f"Unknown action: {action.action_name}"

        except Exception as e:
            action.observation = f"Error executing action: {e}"

        action.diagnostics = self.brick_graph.last_tool_diagnostic
        if action.diagnostics:
            self._log_to_jsonl(self.log_file, {'event': 'tool_diagnostic', 'diagnostic': action.diagnostics})
        return action, None

    def run(self, question: str, verbose: bool = True) -> Tuple[AgentState, Optional[BrickSparqlQuery]]:
        """
        Run the agent on a question.

        Args:
            question: Natural language question
            verbose: If True, print progress

        Returns:
            (final_state, final_sparql) tuple
        """
        self._assert_graph()
        state = AgentState(question=question, mode='paper', language=self.language, implementation_mode='upstream')
        state.interface_language = self.interface_language
        from prompting import decomposition_policy
        state.decomposition_policy = decomposition_policy(self)

        # Store state reference for temporal handler access
        self._current_state = state

        if verbose:
            print(f"\n{'='*80}")
            print(f"Question: {question}")
            print(f"{'='*80}\n")

        self._check_cancelled()
        state.phase = '分解查询'

        # Step 1: Decompose the query (if enabled and needed)
        if self.use_decomposer and self.decomposer:
            # Check if decomposition is actually needed
            should_decompose = self.decomposer.should_decompose(question)

            if should_decompose:
                if verbose:
                    print("🔍 Step 1: Decomposing query (complex query detected)...\n")

                context = ''  # Upstream decomposition receives the question only.
                decomposition = self.decomposer.decompose(question, verbose=verbose, cancel_event=self.cancel_event,
                    context=context, language=self.language, use_temporal=self.use_temporal_handler,
                    use_aggregation=self.use_aggregation)
                state.decomposition = decomposition
                state.decomposition_fallback = getattr(self.decomposer, 'last_fallback', False)
                if self.decomposer.last_usage:
                    state.prompt_tokens += self.decomposer.last_usage.get('prompt_tokens', 0)
                    state.completion_tokens += self.decomposer.last_usage.get('completion_tokens', 0)
                    state.total_tokens += self.decomposer.last_usage.get('total_tokens', 0)
                state.cooldown_seconds += self.decomposer.cooldown_seconds
                self.decomposer.cooldown_seconds = 0

                if verbose:
                    print()  # Add spacing after decomposition output
            else:
                if verbose:
                    print("⚡ Step 1: Skipping decomposition (simple query)...\n")

        # Step 2: Iterative SPARQL generation
        if verbose and self.use_decomposer:
            if state.decomposition:
                print("🔧 Step 2: Iterative SPARQL generation (using decomposition)...\n")
            else:
                print("🔧 Step 1: Iterative SPARQL generation...\n")

        max_parse_retries = 1  # Allow 1 retry on parse error
        parse_retry_count = 0

        while not state.should_stop():
            self._check_cancelled()
            # Get next action from controller
            try:
                action = self.controller(state)
                parse_retry_count = 0  # Reset on successful parse
            except ValueError as e:
                if "Could not parse LLM output" in str(e):
                    parse_retry_count += 1
                    if parse_retry_count <= max_parse_retries:
                        # Add observation to help LLM understand the error
                        print(f"[WARNING] Parse error (attempt {parse_retry_count}/{max_parse_retries + 1}): {e}")
                        print("[WARNING] Retrying with clarification...")

                        error_action = BrickAction(
                            thought="The previous output had an invalid format",
                            action_name="error",
                            action_argument="Parse error"
                        )
                        error_action.observation = (
                            'ERROR: Reply with exactly one Thought: and one Action: label. '
                            'Use Action: execute_sparql(query) or stop(). Do not include Observation:.')
                        state.actions.append(error_action)

                        if verbose:
                            print(error_action.to_string(include_observation=True))
                            print()

                        continue  # Retry with error in history
                    else:
                        # Max retries exceeded, force stop
                        print(f"[ERROR] Max parse retries exceeded. Stopping agent.")
                        action = BrickAction(
                            thought="Unable to generate a valid output format",
                            action_name="stop",
                            action_argument=""
                        )
                        action.observation = "Agent stopped after repeated output parsing errors"
                else:
                    raise  # Re-raise if not a parse error

            # Check for duplicates
            if state.is_duplicate_action(action):
                state.stop_reason = 'duplicate_action'
                if verbose:
                    print(f"[WARNING] Duplicate action detected: {action.action_name}({action.action_argument})")
                    print("   Skipping...\n")
                # Force stop if repeating
                action = BrickAction(
                    thought="Duplicate action detected; stopping",
                    action_name="stop",
                    action_argument=""
                )

            self._check_cancelled()
            state.phase = "执行 " + action.action_name
            # Execute action
            action, sparql_query = self.execute_action(action)

            # Store action
            state.actions.append(action)

            # Store SPARQL if generated
            if sparql_query:
                state.generated_sparqls.append(sparql_query)

            # Print progress
            if verbose:
                print(action.to_string(include_observation=True))
                print()



        # Set final SPARQL
        if state.generated_sparqls:
            latest = state.generated_sparqls[-1]
            state.final_sparql = latest
        state.stop_reason = state.stop_reason or ('model_stop' if state.actions and state.actions[-1].action_name == 'stop' else 'max_iterations')
        state.phase = '完成'

        if verbose:
            print(f"{'='*80}")
            print(f"Completed in {len(state.actions)} actions")

            # Show decomposition summary
            if state.decomposition:
                print(f"\n📊 Decomposition Summary:")
                print(f"  - Sensors: {', '.join([s.sensor_id for s in state.decomposition.sensors])}")
                print(f"  - Temporal: {state.decomposition.temporal.type}")
                if self.use_aggregation:
                    print(f"  - Aggregation: {', '.join(state.decomposition.aggregation.operations) if state.decomposition.aggregation.required else 'None'}")

            if state.final_sparql:
                print(f"\nFinal SPARQL:\n{state.final_sparql.sparql}")
                print(f"\nFinal Results:\n{state.final_sparql.results_as_table()}")
            print(f"{'='*80}\n")

        return state, state.final_sparql


# Simple helper function for quick testing
def ask_brick(question: str, ttl_file: str = None, csv_file: str = None, verbose: bool = True):
    """
    Quick helper to ask a question about Brick data.

    Args:
        question: Natural language question
        ttl_file: Path to Brick TTL file
        csv_file: Path to timeseries CSV file
        verbose: Print progress

    Returns:
        Final SPARQL query results
    """
    agent = BrickAgent()
    agent.initialize_graph(ttl_file=ttl_file, csv_file=csv_file)

    state, final_sparql = agent.run(question, verbose=verbose)

    if final_sparql and final_sparql.has_results():
        return final_sparql.execution_result
    return None


if __name__ == "__main__":
    # Interactive session with Brick Agent
    print("Brick Agent - Iterative framework for Brick SPARQL generation")
    print("="*80)

    # Initialize with your data files
    agent = BrickAgent(
        engine="gemini-flash",
        ttl_schema_file="LBNL_FDD_Data_Sets_FCU_ttl.ttl"  # Include TTL schema in prompt
    )

    # Load Brick schema and timeseries data
    print("\nLoading Brick schema and timeseries data...")
    agent.initialize_graph(
        ttl_file="LBNL_FDD_Data_Sets_FCU_ttl.ttl",
        csv_file="LBNL_FDD_Dataset_FCU/FCU_FaultFree_hourly.csv",  # Using 1-hour interval data
        max_csv_rows=8760  # Load all hourly data (8760 hours in a year)
    )
    print("Data loaded successfully!\n")

    # Interactive loop
    print("Ask questions about the building data.")
    print("Type 'exit', 'quit', or 'q' to end the session.\n")

    while True:
        # Get question from user
        try:
            question = input("Your question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nExiting session...")
            break

        # Check for exit commands
        if question.lower() in ['exit', 'quit', 'q', '']:
            print("\nExiting session...")
            break

        # Process the question
        state, final_sparql = agent.run(question, verbose=True)

        # Optionally show summary
        print("\n" + "-"*80)
        print("Ready for next question!\n")
