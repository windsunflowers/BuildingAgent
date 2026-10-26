# TUC ReAct 30 题：源码对齐与低分定位

核查报告：`e6cf4e80cdf244eefbf7cf422fca186f2`。报告 SHA256 为 `50c7017650e2dad9d2bde0d245a999f886d5308801df4931a3360c8079694574`。本次为只读查询回放，不是模型重跑，原报告与分数保持不变。

## 实测结论

| 条件 | Entity-set F1 | Row Matching F1 | Exact Match F1 |
|---|---:|---:|---:|
| 用户本轮 Qwen 最终查询，30 题 | 0.041667 | 0.033333 | 0.033333 |
| 同轮已保存首轮查询，离线诊断 | 0.633333 | 0.566667 | 0.300000 |
| 官方 Gemini 5000T 历史 CSV，TUC 30 题 | 0.864877 | 0.710210 | 0.000000 |
| 官方已保存查询在当前执行图与固定官方 scorer 上回放 | 0.864877 | 0.710210 | 0.444444 |

首轮是诊断数据，不能替代作者规定的最后一轮评分。30 题中 16 题的 Row F1 在修订后降低，0 题提高，14 题不变；所有题均达到三轮上限。最终 24 题合法空结果、4 题语法失败、2 题非空；模型调用未记录传输或 JSON 失败。第一题首轮 Entity/Row 为 1/1，Critic 否定实际设备—空间—分区路径，下一轮改为直接 zone→point 后返回空结果。另有 3 个 UNION 语法错误和 1 个 `|` 语法错误作为最终答案。

这说明本轮主要退化发生在 Critic 反馈后的模型修订阶段。Qwen 与 Gemini 的模型条件不同，local 与 remote 的结果反馈不同；本次没有单变量模型实验，不能量化二者各自造成多少差值。

## 已排查的可能原因

- 上下文并未漏传：模型请求快照内含完整 1855 条 TUC TTL，落盘 context 与所选原文件逐字一致；与完整建筑源图 RDF 同构。报告 `context=0` 是数值兼容字段，实际输入由 `context_mode=existing_ttl` 与文件快照确定，不代表模型实际跑了 NoKG。
- 官方 CSV 与本轮 30 个问题逐字匹配，覆盖相同题集；模型请求确实为 `qwen-plus-2025-12-01`，英文提示、temperature=0、JSON object、无额外输出 token 上限。
- 回放官方 30 条生成查询，结果行数 30/30 与官方记录一致；Entity F1、Row F1 也逐题 30/30 一致。因此本轮低 Entity/Row 不是普遍的本地执行或评分失败。
- Exact F1 仅 16/30 与官方历史 CSV 相同。固定提交 `metrics.py` 按首行 binding 的键顺序建立列位置映射；官方 CSV 没有保存当时的完整 JSON bindings。可能涉及历史评分版本或后端绑定顺序，但现有证据不能确定。原始 RDFLib 与 GraphDB JSON 行键顺序未验证；不得强行将当前第三项清零。

## 官方来源核验

本次从官方 GitHub 固定提交重新下载并校验，而非只比较本地拷贝：

- [BuildingQA ReAct 源码](https://github.com/INFERLab/BuildingQA/blob/b792a627419dfb679ad1f26e4d3dc325a758e95b/ReAct_agent/sparql_refinement_agent.py)：SHA256 `91f3409b15df57d652895fa0b94b7668cc6cdafaeb0cecb1c17784e4bbdcd52e`。
- [演示 notebook](https://github.com/INFERLab/BuildingQA/blob/b792a627419dfb679ad1f26e4d3dc325a758e95b/ReAct_demo.ipynb)：SHA256 `fec11c4493009eab57ebf4cecd1f66cf6cc44604d3cab3f1604bfc4d06e4f2a9`。
- [官方历史结果](https://github.com/INFERLab/BuildingQA/blob/b792a627419dfb679ad1f26e4d3dc325a758e95b/Experiment_Results/ReAct(5000)/gemini-flash-2.5.csv)：TUC 均值与 BrickQA 论文表 2 的 0.865/0.710/0 一致；CSV 的 model 字段实际写 `google/gemini-flash`，没有可核验的日期快照。
- [固定 metrics.py](https://github.com/INFERLab/BuildingQA/blob/b792a627419dfb679ad1f26e4d3dc325a758e95b/metrics.py)：在线源文件与本地 vendor 均为 `d7d982fe1f9eaa020d00615ec8ab48ed6f0b6117cd4963a53f8e39473447010b`。
- BrickQA `49d9e283c2a3958e9be110583be6575cbd40039b` 的完整文件树没有独立 ReAct 源文件；其论文 ReAct 结果需要追溯 BuildingQA，不能凭空从 BrickQA 提取另一套 ReAct 实现。

下载来源与哈希见 `react_30_reference_manifest.json`，官方原 CSV 另存为 `buildingqa_react5000_gemini_upstream.csv`。全部回放与逐题证据见 `react_30_query_replay_20261021.json`。

## 代码对齐的准确边界

本地 Writer/Critic 原提示、消息角色、历史追加、JSON、三轮入口、保留末次查询均与固定源码一致。独立执行原源码的 local formatter/query 函数，对照成功、空结果、未绑定列、语法错误、ASK 继承问题，新增回归通过。

但目前只对齐了作者 **local RDFLib 分支**，不等于论文环境：

1. notebook cell 9 明确 `USE_LOCAL_TTL_FILE=False`，连接 GraphDB；remote 分支向 Critic 给前 10 行 SPARQL JSON bindings。本地分支只给行数。两者 Critic 均没有收到 Writer 的 TTL 上下文，这是原代码行为，不是本地漏传。
2. 当前 API 模型是用户指定的固定 Qwen，论文称 Gemini 2.5 Flash；保持两者实验条件分开。
3. BuildingQA 的 get_kg_subset_content 用 RDFLib 截取/序列化；本地按用户既有要求使用固定 TTL 原文。TUC 全图仅 1855 条，覆盖一致，但文本顺序/序列化不同仍须记录。
4. 执行图本体合并、180 秒预算和 SDK 的 30 秒请求预算仍是本地适配；本次四个错误均为模型查询语法错误，未观测到本轮预算或 API 配额失败。
5. notebook 批处理示例还复用外部 TTL/endpoint/JSON 变量，且该处构造 agent 未传 client；它本身不能证明发布表格的完整运行配置。正式入口应逐建筑固定路径和配置，不能机械复制未闭合的 notebook 状态。

本次只补充真实后端/模型的界面说明、来源元数据和独立源码回归，未改变模型提示、三轮停止、最终查询选择或官方 scorer。

## 未完成与阻塞

严格对齐官方远程执行路径需要用户提供可用 GraphDB repository URL，以及该库的 TTL、本体、推理配置；当前没有这些信息，不能宣称 GraphDB 环境已复现。已向用户询问端点。

正式论文数值复现还需要原模型条件及对 Exact F1 历史差异的解释/原始 bindings。现阶段可称“固定 Qwen 条件下的 BuildingQA local ReAct 方法复现”，不能称完整论文数值复现。原始报告、原查询和基准不作追分修改。
