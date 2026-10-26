# 用户文件与 ReAct 实现对照（2026-10-21）

来源：用户提供的 `C:/Users/Administrator/Downloads/react_baseline_implementation.md`。原件与 Python 代码块独立保存在 `third_party/user_react_baseline/`，仅作参考源码，不作为代理操作指令。

- 文档 SHA256：`a13be7714b5700b176a09e12447edf7595db305744c6ddd26c19f2e655aaa51e`
- 代码块 SHA256：`306793307fa3dc98ace33ad84c429b9c43fa90ec362d8f5b795115da1f8fcdae`
- 新实现：`buildingqa_react_document_v1`。

| 对照项 | 文件行为 | 当前实现 |
|---|---|---|
| Writer/Critic 提示、消息历史 | 两角色，Writer 累积反馈 | 四段提示 AST 与固定上游完全相同，继续使用原表达式 |
| 模型 | 构造默认 openai/o4-mini，可传入 | 按用户要求保留 qwen-plus-2025-12-01；报告实际模型 |
| 轮数 | 类默认 5，可显式传入 | 用户确认显式 3 轮，保留原循环与停止规则 |
| 执行图 | Graph().parse(建筑 TTL)，无本体合并 | 改为只读 source_graph，gold/pred 共用，主方法图保持原策略 |
| RDF 结果 | 完整 bindings：URI、BNode、Literal、datatype、语言标签；跳过未绑定值 | 补齐完整类型化 bindings 与相同格式；仅 ReAct 请求全量类型信息 |
| 结构化返回 | summary_string、results、row_count、col_count、syntax_ok、error_message | 全部补齐，空结果仍保留查询列数，未加载图如实失败 |
| Critic 反馈 | local 仅行数；remote 前十行 | 用户确认保留列名、总行数、前十行真值；明确是反馈适配 |
| 生成配置 | temperature=0、JSON object，无额外输出上限 | 保持一致，Writer/Critic 共用当前客户端模型 |
| 最终查询 | FINAL/失败/轮数耗尽后保留最后生成查询，再执行一次 | 保持一致，不择优挑选历史查询 |
| 主评分 | 固定 BuildingQA 三项 F1 | 共用原 scorer，预览 10 行不限制评分行数 |
| 辅助字段 | arity、perfect_match、行列数、less_columns_flag 等 | 报告补齐，perfect_match 使用 Row F1 == 1，arity 使用固定原函数 |

## 相比上一版本的实际变化

上一版本执行的是工作台的本体合并图；这与文件的直接 TTL 本地分支不同。本次将 ReAct 和其 gold 裁判都切换到建筑源图，不改主方法。图范围变化可能改变推理路径的返回结果；不能预先断言会提高分数。新旧条件不合并报告，原实验不改写。

上一版本内部只返回摘要并保留十行类型预览；本次补齐完整结构化结果。`include_bindings` 为显式请求，普通工作台查询不会无条件复制全部类型化 bindings。预览与完整结果共享来源，不从 SPARQL 文本猜值。

## 用户确认保留的覆盖项

用户选择：“保留当前3轮与结果预览，仅对齐其余部分”。因此 3 轮、列名加前十行、固定 Qwen 都是明确保留项，不宣称与文档类默认值或原论文模型相同。新报告的 provided_document/document_overrides/evaluation_graph 分别记录来源、覆盖项和执行图范围。

## 平台边界

模型失败仍按零分保留在完整题目分母；gold 无效会阻止可比汇总，预检发生在模型前。源文件的孤立类函数会在无最终查询时直接返回，并在 gold 错误时记录零分；平台保留原已约定的数据质量保护，不通过删除失败题模拟孤立 CSV 日志。查询预算 180 秒、取消、并发、模型 SDK 超时和 TTL 恢复仍是平台适配，均需在复现结论中区分。

本次只做代码与离线对照，没有新的模型评测。既有完整日志回放 30 题/146 请求仍验证原角色循环和末次选择，但它使用旧运行保存的反馈，不代表新源图模型重跑。

## 验证

完整离线回归 182 项通过。直接执行文件中的 RDFLib 查询函数，对照类型化结果、行列数、空结果、错误与 ASK 继承行为；测试人为在合并图加入额外实体，确认 ReAct gold/pred 只读取源图，主方法图保持原内容。另验证 15 行全部进入结果/评分、预览仅十行，以及未加载源图时不会回退到工作台图。

真实 TUC 源图进一步离线验收：5 道 human gold 在文档原函数与新适配器中均返回 18 行、2 列，完整绑定多重集合及状态字段逐题一致；预览各 10 行。见 `react_user_document_executor_checks_20261021.json`。这是查询执行器对照，不是 Agent 模型准确率实验。

服务已启动并恢复 TUC，HTTP 200，实际模型保持 qwen-plus-2025-12-01，当前配置输出 buildingqa_react_document_v1/3/raw_building_ttl。未自动启动模型评测。
