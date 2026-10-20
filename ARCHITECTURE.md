# BrickQA 项目流程讲解（基于当前代码 + 论文）

> 本文以**仓库当前实际代码**为准梳理整体流程，并在末尾标注与论文（BuildSys'26）的差异。
> 核心结论先行：这是一个 **schema 引导的 LLM ReAct agent**，把楼宇自然语言问题转成可执行 SPARQL，
> 通过「查询分解 → 迭代生成 → 内联校验」三段式降低幻觉。LLM 后端已从论文的 Gemini/Vertex AI
> 改造为 **OpenAI 兼容接口（默认 Qwen/DashScope）**。

---

## 1. 文件结构

| 文件 | 角色 |
|---|---|
| `main.py` | 简单 CLI 入口（交互 / 单问），只加载 TTL |
| `main_temporal.py` | 时序 CLI 入口，加载 TTL+CSV，输出 JSON 报告 |
| `brick_agent.py` | **编排核心** `BrickAgent`（ReAct agent） |
| `brick_decomposer.py` | Step1 查询分解 `BrickQueryDecomposer` |
| `brick_temporal_handler.py` | 时序约束应用/校验 `BrickTemporalHandler` + 3 个校验函数 |
| `brick_utils.py` | 数据层 `BrickGraph`（rdflib 单例）+ 4 个探索工具 + `execute_sparql` |
| `llm_client.py` | 统一 LLM 客户端 `LLMClient`（OpenAI 兼容，替代 Vertex） |
| `prompts/` | prompt 模板 + 示例 TTL/CSV/描述文件 |

---

## 2. 入口文件与启动过程

### 2.1 `main.py`（日常使用）
执行顺序：
1. `argparse` 解析：`--ttl`(必填)、`--schema-in-prompt`、`--question/-q`、`--no-decomposer`、`--no-temporal`、`--project`、`--quiet`。
2. （遗留）`--project` 会 `os.environ["GOOGLE_CLOUD_PROJECT"]=...`，**Vertex 时代残留，当前 llm_client 不读它**。
3. 建 `BrickAgent(engine="gemini-flash", use_decomposer=…, use_temporal_handler=…, ttl_schema_file=args.schema_in_prompt)`。
   注意：`engine="gemini-flash"` 只是标签，真正模型由 `llm_client` 的 `LLM_MODEL` 决定。
4. `agent.initialize_graph(ttl_file=args.ttl)` —— **只加载 TTL，不加载 CSV**。
5. 有 `--question` → 单问后退出；否则进入交互 `while` 循环，反复调 `agent.run(question, verbose)`。

### 2.2 `main_temporal.py`（时序/评估）
执行顺序：
1. 解析：`--building-id`、`--ttl`、`--csv`、`--schema-in-prompt`(描述 txt)、`--question`、`--start-date/--end-date`、`--max-rows`(默认 2000)、`--use-fewshot`、`--no-decomposer`、`--no-temporal-handler`、`--result-limit`。
2. 建 `BrickAgent(..., ttl_schema_file=args.ttl, schema_description_file=args.schema_in_prompt, result_limit=…)`。
   与 main.py 不同：这里把**完整 TTL** 和 **schema 描述**都注入 prompt。
3. `agent.initialize_graph(ttl_file, csv_file, max_csv_rows, use_cache=False, start_date, end_date)`。
4. `run_single_question()` 包装 `agent.run()`，把分解/动作轨迹/中间 SPARQL 序列化。
5. 写 JSON 到 `buildingqa_results/<building-id>_temporal/result_<ts>.json`。

---

## 3. 核心模块及职责

### 3.1 `BrickAgent`（brick_agent.py）—— 编排核心
- `__init__`：建 `BrickGraph` 单例；按需建 `BrickQueryDecomposer`、`BrickTemporalHandler`；
  可选加载 few-shot 示例、`ttl_schema_content`、`schema_description`；创建 `logs/prompt_logs_<ts>.jsonl`。
- `initialize_graph`：(可选读缓存) → `BrickGraph.initialize(ttl)`（内部合并官方本体）→
  若有 CSV 则 `add_timeseries_data` → `_extract_date_metadata()`（**硬编码 2018 年**）。
- `controller(state) -> BrickAction`：决策"大脑"。拼 prompt → 调 LLM → 解析出下一个动作。
- `execute_action(action)`：执行动作并填 `observation`；`execute_sparql` 前做内联校验。
- `run(question, verbose)`：主循环（见第 5 节）。
- `_validate_and_fix_sparql(sparql)`：SPARQL 语法**自动修正**（补 PREFIX、纠正命名空间 URI、去时间戳 `Z`、`ORDER BY DESC` 自动补 `LIMIT 1`）。

### 3.2 `BrickQueryDecomposer`（brick_decomposer.py）—— Step1
- `should_decompose(question)`：**启发式**，>12 词 / 含 "and/or/,/all/both/each" / 含比较词 / 含条件词 → 需分解；否则跳过（省一次 LLM 调用）。
- `decompose(question)`：读 `prompts/brick_decomposition.prompt` → 调 LLM → 解析 JSON 成 `QueryDecomposition`（sensors、temporal、aggregation、query_intent）。失败降级 `_mock_decompose`。

### 3.3 `BrickTemporalHandler`（brick_temporal_handler.py）
- `apply_temporal_constraint(sparql, decomposition)`：按 temporal type（latest/recent_n/oldest_n/trend/range/specific）给 SPARQL 加 `ORDER BY/FILTER/LIMIT`。
- `validate_temporal_query(sparql, decomposition)`：校验时序约束是否正确落地。
- 模块级校验函数：`validate_sensor_coverage`、`validate_aggregation`、`validate_multi_sensor_joins`。
- `should_use_temporal_guide(decomposition)`：简单型（latest/recent_n/oldest_n/trend）→ 跳过 guide 由 handler 直接套模板；复杂型（range/specific/relative/period）→ 注入 `prompts/brick_temporal_patterns.txt` 引导 LLM。

### 3.4 `brick_utils.py` —— 数据层
- `BrickGraph`（单例）：
  - `initialize(ttl)`：`rdflib` 解析 TTL → `_merge_brick_ontology` **合并官方 `brick.ttl` 本体**（让 `rdfs:subClassOf*` 推理生效；找不到会告警）→ 绑定命名空间。
  - `add_timeseries_data(csv, max_rows, start, end)`：CSV→每行每列生成 `ref:hasObservation/hasTimestamp/hasValue` 三元组（默认取**最后** max_rows 行）。
  - `save_graph / load_from_cache / get_date_range`。
- `execute_sparql(query, timeout=180, result_limit)`：**子线程+超时**执行；自动补 PREFIX/LIMIT；返回 `list[dict]` 或 `(results, SparqlExecutionStatus)`。
- 探索工具（供 agent 调用）：`search_brick`、`get_brick_entity`、`get_property_examples`、`get_all_sensor_types`；配套 `format_search_results`、`format_entity_info`。

### 3.5 `LLMClient`（llm_client.py）—— 统一 LLM 调用
- 环境变量：`LLM_BASE_URL`(默认 DashScope)、`LLM_API_KEY`、`LLM_MODEL`(默认 `qwen-plus`)；兼容 aihubmix / Ollama / vLLM。
- `generate_text(prompt)`：单轮 user prompt → assistant 文本；**指数退避重试 3 次**；记录 `last_usage` token 数。
- `get_client()`：共享单例。controller 与 decomposer 都经它调 LLM。

---

## 4. 模块调用关系与数据流转

```
用户问题
  └─ main.py / main_temporal.py
       └─ BrickAgent.run(question)
            ├─[Step1] BrickQueryDecomposer.decompose ──> LLMClient ──> LLM   (仅复杂查询)
            │            └─> QueryDecomposition(传感器/时序/聚合/意图)
            └─[Step2] 迭代循环 (≤15 轮):
                 ├─ controller(state)
                 │    ├─ 组装 prompt = 模板 + schema描述 + TTL样本 + 时序guide + 分解信息 + action历史
                 │    ├─ LLMClient.generate_text ──> LLM
                 │    └─ 解析文本 ──> BrickAction(Thought/Action)
                 ├─ execute_action(action)
                 │    ├─ search_brick/get_brick_entity/get_property_examples ──> BrickGraph(rdflib)
                 │    └─ execute_sparql:
                 │         ├─ _validate_and_fix_sparql (语法自动修正)
                 │         ├─ TemporalHandler 校验/应用时序约束
                 │         ├─ validate_sensor_coverage/aggregation/multi_sensor_joins (仅告警)
                 │         └─ BrickSparqlQuery.execute ──> brick_utils.execute_sparql ──> BrickGraph
                 ├─ observation 写回 action.observation，append 进 state.actions
                 └─ should_stop()? (stop 或满 15 轮)  否→回 controller；是→收敛
            └─ final_sparql = 最后一条生成的 SPARQL ──> 结果
```

数据载体：`AgentState`（问题、动作历史、生成的 SPARQL 列表、分解结果、token 统计）。

---

## 5. 主要功能执行步骤（`run()` 主循环）

1. `state = AgentState(question)`；`self._current_state = state`。
2. **Step1 分解**：`if use_decomposer and should_decompose(question)` → `decompose()` → 存 `state.decomposition`；否则跳过。
3. **Step2 迭代**：`while not state.should_stop()`（`should_stop` = 动作数≥15 或末动作是 stop）：
   a. `controller(state)` 产出 `BrickAction`；**解析失败重试 1 次**（append 一个 `error` 动作提示格式后再试），仍失败则强制 `stop`。
   b. **重复动作检测**：`is_duplicate_action`（与最近 5 个比）→ 命中则强制 `stop`。
   c. `execute_action(action)` 执行，得到 `observation` 与可选 `sparql_query`。
   d. `state.actions.append(action)`；有 `sparql_query` 则入 `generated_sparqls`。
4. 循环结束：`final_sparql = generated_sparqls[-1]`，返回 `(state, final_sparql)`。

### `controller` 内部（每轮）
- 限流 `sleep`；`get_client()`。
- 读 `prompts/brick_controller.prompt` 模板；拼入 schema 描述、TTL 样本（按大小判 sample/complete）、
  （复杂时序时）时序 guide、分解信息；简单模板替换 `{{ question }}`、注入 action 历史。
- `client.generate_text(prompt)`；累计 token；写 jsonl 日志。
- 解析输出：优先 `Thought:`/`Action: name(args)`（含括号平衡匹配）；兼容"直接输出 SPARQL（PREFIX/SELECT 开头）"；
  兼容"`finish`"兜底；都无法解析则抛 `ValueError` 触发上层重试。

### `execute_sparql` 内联校验（与论文"Inline Query Validation"对应）
语法（`_validate_and_fix_sparql`，**自动改**）→ 时序（`validate_temporal_query` + `apply_temporal_constraint`，**自动改**）→
传感器覆盖/聚合/多传感器 join（**只告警**，反馈给 LLM 下轮自纠）。

---

## 6. 关键数据结构
- `BrickAction`：thought / action_name / action_argument / observation；`POSSIBLE_ACTIONS = [search_brick, get_brick_entity, get_property_examples, execute_sparql, stop, error]`。
- `BrickSparqlQuery`：sparql / execution_result / execution_status / result_limit；`execute()`、`has_results()`、`results_as_table()`。
- `AgentState`：question / actions / generated_sparqls / final_sparql / max_iterations=15 / decomposition / token 统计；`should_stop`、`is_duplicate_action`、`get_action_history`。
- `QueryDecomposition`：sensors / sensor_count / temporal / aggregation / query_intent / raw_json。

---

## 7. 与论文（BuildSys'26）的差异 —— 以代码为准
1. **LLM 后端**：论文用 **Gemini 2.5 Flash（Vertex AI）**；当前代码改为 **`llm_client.py`（OpenAI 兼容，默认 Qwen/DashScope）**。`BrickAgent(engine=...)` 仅是标签。
2. **工具数**：论文列 5 个工具；代码 `POSSIBLE_ACTIONS` 多一个内部 `error`（用于解析失败重试，非暴露给 LLM 的正式工具）。
3. **校验行为**：论文说内联校验把问题**作为告警反馈、不自动改**；代码里**语法与时序是自动修正**的（`_validate_and_fix_sparql`、`apply_temporal_constraint`），只有传感器覆盖/聚合/join 是告警。即代码比论文描述"更进一步"。
4. **prompt 组装**：实际生效的是 `controller()` 内联拼装；`brick_agent.py` 里的 `_build_controller_prompt()` 是**遗留死代码，未被调用**。
5. **`--project` 参数**：Vertex 残留，设 `GOOGLE_CLOUD_PROJECT`，当前不被 llm_client 使用（用 `LLM_*` 环境变量）。

---

## 8. 常见坑 / 注意点
- **必须在 `BrickQA/` 目录下运行**：代码用相对路径读 `prompts/*.prompt`。
- **官方本体**：`BrickGraph` 会合并 `brick.ttl`（查找顺序 `$BRICK_ONTOLOGY_PATH` → `ontology/brick.ttl` → `brick.ttl`）；缺失时 `rdfs:subClassOf*` 查询可能返回空。
- **硬编码年份**：`_extract_date_metadata` 写死 `2018`（为 LBNL FCU 数据集），换数据需改。
- **单例图**：`BrickGraph` 是单例，重复 `initialize` 会跳过（换数据集要先 `reset_singleton`）。
- **CSV 取尾部**：`add_timeseries_data` 默认取**最后** max_rows 行。
- **`brick_agent.py` 的 `__main__`** 引用 `LBNL_FDD_*.ttl/csv`（不在仓库），属测试残留；日常用 `main.py` / `main_temporal.py`。
