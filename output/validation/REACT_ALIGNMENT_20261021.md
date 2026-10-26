# ReAct 对齐与故障核查（2026-10-21）

## 结论与证据

最新截图是 gold 执行故障，模型尚未调用，不能证明 ReAct 生成了错误 SPARQL。此前 NoKG 报告中生成查询使用了图中不存在的 `brick:hasTimeseries`、`brick:timeseriesId`，Critic 也没有纠正，属于另一类模型语义错误。

按真实应用导入方式进行离线并发，捕获 `OpenBLAS error: Memory allocation still failed after 10 retries, giving up.`。Windows spawn 会先导入主程序及 pandas/numpy，再进入查询 worker；每个进程额外创建数值库线程造成资源压力。修复后，同一 TUC 图、8 线程上限、五道 human gold 全部成功，各 18 行，见 `react_gold_all_human_after.json`。旧错误没有异常类型/退出码，不能证明每一个旧空白异常均为同一种原因。

## 源码核对

| 项目 | 依据与当前行为 |
|---|---|
| BrickQA 来源 | `49d9e283c2a3958e9be110583be6575cbd40039b` |
| BuildingQA 来源 | `b792a627419dfb679ad1f26e4d3dc325a758e95b`，ReAct 源文件与 SHA256 保留 |
| Writer/Critic | 从未修改源码提取英文提示，角色/JSON/历史追加/失败保留最后查询，已与原函数逐消息离线比较 |
| 轮数 | notebook 显式 3，类默认 5；不能将演示设置混称论文全部参数已确认 |
| API/model | 与 BrickQA 共用当前选择；temperature=0、JSON object、原 ReAct 未指定输出 token 上限 |
| observation | 源码 local 分支仅给行数；remote 分支给前 10 行 bindings，两者不同 |
| ReAct 查询 | 原文执行，不注入 BrickQA 工具、schema guide、前缀修复或 gold |
| 评分 | 共用固定版本 BuildingQA 三项 F1；保留重复行与列映射 |
| BuildingQA 模块 | Temporal Constraints、Operations 关闭；ReAct 不调用 BrickQA 分解器 |
| 界面语言 | 只负责显示，实际新模型提示始终英文 |

## 本次修改

1. 原 gold 在 BrickQA 中走自动前缀处理，在 ReAct 中走原文执行，裁判条件不同。现统一 raw gold executor；仅遵循固定 notebook 规则，在完全不含 `prefix` 时追加源 TTL 声明，已有声明不覆盖。分别保存原文本、实际执行文本、状态、错误。
2. 查询子进程继承 BLAS/OMP/MKL/NumExpr 单线程环境；启动串行化以保护临时环境设置，之后恢复父进程原设置。题目并发数、模型参数、查询文本不变。
3. 空消息异常保留类型，管道 EOF/通信故障保留 PID/退出码，分类 other_error。未加入静默重试或查询修补。

## 真实实验的边界

- `ebf066731e90e48c9a19d1a496988caf7`：ReAct/Qwen/NoKG，TUC human 5 题；旧报告只保存 4 题。查询合法空结果与 unknown namespace 错误需分别看待。
- `e4038efdc75d245b4a5dcea0bb3e45c34`：ReAct/Qwen/已有 TUC TTL 上下文，保存 3/5、2 道 gold_error。经用户确认中断并重启；原报告保留，未自动重跑。
- 论文第 4.1.3 节用 Gemini 2.5 Flash；当前模型是 Qwen，不能当作相同实验条件。
- 论文表 2 的 TUC NoKG ReAct 三项 F1 均为 0，因此低分本身不能证明实现错误。human 子集与含 paraphrase 的完整题集也不能直接比较。
- 当前图含本体合并，ReAct 使用原源码 local 模式和共享已有 TTL 上下文。公开依据未固定全部后端设置，不能将 local 工作流一致宣称为论文运行环境完全一致。
- BrickQA 仍包含本地工程适配（图谱命名空间、schema guide、通用查询处理等），并非 ReAct 原提示的一部分。不能为提高 ReAct 分数加入这些信息，也不能忽略其对配对比较的影响，完整边界见项目审计。

## 验收与剩余工作

完整离线回归：156 passed，两个既有 FastAPI on_event 弃用告警。应用导入路径的 5/5 human gold 并发执行成功。服务已按用户确认重启，页面与 SPARQL 接口正常，旧任务恢复为 interrupted。

本次没有重跑模型或完整论文矩阵，不宣称模型准确率提高。正式复现仍需固定可用的 Gemini 配额、完整题集、上下文、执行图/本体及后端模式，再运行新的配对实验并重建表 2。依据不足的运行参数需明确记录，不能猜定后宣称完全一致。
