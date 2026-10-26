# BrickQA 本地启动指南

## 模型请求超时

LLM_TIMEOUT 默认 300 秒，适用于 BrickQA 与 ReAct，SDK 和新评测报告使用同一数值。长提示/并发时不会再按旧默认 30 秒过早终止。需进一步调整时，在启动前设置：

```powershell
$env:LLM_TIMEOUT = '600'
npm run dev
```

改动后需重启服务，已创建的客户端不会自动更新。LLM_TIMEOUT 必须为有限正数；独立的 EVAL_PER_QUESTION_TIMEOUT/CLI --timeout 仍按原配置执行。此设置增加网络等待时间，不保证断网或上游持续无响应时成功，不会自动重跑失败题。

## 选择模型

点击页面右上角的模型按钮打开右侧滑动面板，可在现有 Qwen 配置与 `gemini-2.5-flash` 之间选择。输入该供应商的 API Key，点击“应用模型”，再点击“测试连接”。密钥按供应商分别使用 Windows 当前用户 DPAPI 加密，保存到 Git 忽略的 `.local/model_profiles.json`；页面和报告不返回密钥。重启后恢复所选模型，需使用同一 Windows 用户。

Gemini 使用 Google 官方 OpenAI 兼容地址 `https://generativelanguage.googleapis.com/v1beta/openai/`。模型切换不修改作者工具、提示模板、数据或 BuildingQA 三项评分。现有温度与 token 上限保留，未额外关闭 Gemini 默认思考；Gemini 与 Qwen 属于不同实验条件，应分别报告。查询、评测或图谱加载期间禁止切换；新报告记录实际模型、供应商、地址与响应模型标识。不会自动重跑评测。

## 主方法：BrickQA 作者方法

## BuildingQA ReAct 对照评测

2026-10-22 新增作者 GraphDB 分支。选择 ReAct 后，在“ReAct 执行后端”选择 GraphDB（网页默认）或 RDFLib。GraphDB 按加载建筑固定映射：TUC_building → `http://CHINAMI-42UOT9U:7200/repositories/TUC_building_test`，dflexlibs_multizone → `http://CHINAMI-42UOT9U:7200/repositories/DFLEX`，bldg11 → `http://CHINAMI-42UOT9U:7200/repositories/bldg11`。gold 和预测都发往同一仓库；不在失败时回退本地。CLI 可加 `--react-backend graphdb`；网页、API、CLI 未指定后端时均为 graphdb（2026-10-24 按作者 Notebook 默认值统一）；本地对照须显式指定 --react-backend rdflib。示例：`.\.venv\Scripts\python.exe evaluate.py --method react --react-backend graphdb --benchmark benchmarks/TUC_building_all.jsonl --context 5000 --workers 3`（会真实调用当前模型）。

远程分支标记 `buildingqa_react_graphdb_author_v1`：Critic 接收作者原文摘要和前十行 SPARQL JSON bindings，不额外添加列名头或 TTL；空结果/失败使用作者远程分支摘要，HTTP 错误保留响应正文。本地分支继续按下述 RDFLib 设置，仅反馈行数。两者评分使用全量 bindings，3 轮、英文提示、固定当前模型不变。仅初始 TTL 提示来自本地文件；远程执行数据取自 GraphDB 仓库，服务端推理保留默认，报告记录为未核实配置。传输用标准库 GET/JSON 替代 SPARQLWrapper，无新增依赖；取消在当前 HTTP 请求返回或 180 秒超时后生效。未知建筑拒绝运行。

显式选择 RDFLib 时对齐作者本地分支，`implementation_mode=buildingqa_react_rdflib_author_v1`、`feedback_policy=upstream_rdflib_row_count_only_v1`。保留 **3 轮与固定 Qwen 模型**；Critic 成功反馈仅含行数，空结果及错误采用作者摘要，错误正文不经过界面翻译。ReAct 的执行和 gold 裁判都使用建筑 TTL 源图，不额外合并本体；主方法仍使用工作台原图。文档原件及代码块保存在 `third_party/user_react_baseline/`，报告记录文档 SHA256、实际图范围及覆盖项。三项 F1 直接使用完整类型化 SPARQL JSON bindings；行列数及 `arity_matching_f1`、`perfect_match`、`less_columns_flag` 等辅助字段与文件对应。

早期 `buildingqa_react_rdflib_preview_v1` 使用共享合并图；`buildingqa_react_document_v1` 使用源图与前十行反馈。两者仅作为旧报告条件保留。可运行 `.\.venv\Scripts\python.exe audit_react_run.py --report <报告路径> --output <独立审计路径>`，用保存的真实响应离线对照作者原循环；审计输出不覆盖原报告、不调用模型。需要报告目录中的 context.ttl 和完整模型请求快照。

准确度评测中可选择 BrickQA 或 ReAct，随后选择同一建筑、题集和上下文并运行。两者使用右上角当前选择的同一 API 供应商、模型和对应密钥，输出同一套 Entity-set F1、Row Matching F1、Exact Match F1；历史结果不混入新汇总，报告记录 method、实际模型、完整多角色提示快照、轨迹与停止原因。论文模型条件为 Gemini 2.5 Flash；选择 Qwen 仍属于模型迁移条件，不等同原论文数值复现。

ReAct 对齐 BuildingQA `b792a627419dfb679ad1f26e4d3dc325a758e95b` 的 Writer → 所选后端执行 → Critic 流程，最多 3 轮（来源为 `ReAct_demo.ipynb` 的显式参数，类构造默认值是 5）。Writer 累积自己的查询与 Critic 反馈；Critic 每轮只接收原问题、当前查询和作者分支对应摘要：GraphDB 为前 10 行 bindings，RDFLib 为行数；不额外提供 TTL 或列名头。无分解、动态搜索、BrickQA 模式描述或日期指南，也不补写/替换 PREFIX。JSON object、temperature=0、输出 token 上限未指定，均按参考实现；Critic 或后续 Writer 失败时保留最后已生成查询。沿用当前工程 SDK 的网络超时与重试封装，每次角色调用不增加外层重试；ReAct SDK 重试为 2，与原 Notebook 创建 OpenAI 客户端时的 SDK 默认行为对齐。网络等待默认 300 秒为用户运行设置。原版源码存于 `third_party/buildingqa/react/`，提示表达式从哈希固定的原文件提取，不导入原文件的 SDK/远程端点配置。本项目默认远程 GraphDB，与 Notebook 默认分支一致；最多 3 轮，Critic FINAL 可提前结束。

网页上下文文件原文在两种方法之间共用；CLI 的 0/100/5000 同样共用现有上下文选择逻辑。需使用同一冻结上下文并核对哈希，不能只看 100T/5000T 标签。GraphDB 执行使用远程仓库；显式 RDFLib 与 BrickQA 使用本地完整建筑图，不额外合并本体。各自 gold/pred 使用同后端和同图。共享官方评分、gold 预检、SPARQL 子进程隔离、180 秒预算及 SDK 超时，这些平台适配写入报告。不会自动更换模型或重跑整套基准。

```powershell
.\.venv\Scripts\python.exe evaluate.py --method react --benchmark benchmarks/TUC_building_all.jsonl --context 0 --workers 3
.\.venv\Scripts\python.exe evaluate.py --method brickqa --benchmark benchmarks/TUC_building_all.jsonl --context 0 --workers 3
```

以上命令会真实调用模型并分别生成报告。两方法可复用取消、并发、逐题详情和导出；新增入口的离线测试不代表论文全量成绩已复现。

BuildingQA 网页与 `evaluate.py` 固定关闭 Temporal Constraints 和 Operations：实际发送的分解提示仅保留实体与意图，排除关闭模块的指令、输出字段及混合示例；控制器不注入时间分解、聚合分解或时序范围指导。模型额外返回的关闭模块字段也不会进入运行状态。此开关不禁止最终 SPARQL 使用题目所需的 COUNT 等语法。原始英文模板、作者工具与三项 F1 实现不变。

新报告的 `decomposition_policy`、`experiment=buildingqa` 及提示快照记录此条件，当前版本为 `BrickQA-author-only-20261020-v5-english-prompts`；此前仅返回后关闭字段或使用中文提示的历史报告不可重标或与新结果直接合并。网页双语说明已同步。

LBNL FDD 时序案例与标准基准分开：自然语言查询默认保留完整模块，须先加载正确 TTL、CSV、日期及行数。`main.py --experiment lbnl_fdd` 显式启用全部分解模块，`main.py --experiment buildingqa` 显式仅启用实体分解；二者不能与 `--no-temporal` 或 `--no-decomposer` 混用。这些参数只控制模块，不自动加载 CSV；命令行时序输入须提供已包含观测的图谱。标准 `evaluate.py` 不作为 LBNL 完整时序案例入口，表 4 数值答案仍须独立 pandas 核验。

自然语言查询仅提供 BrickQA 作者方法；评测可显式选择 BrickQA 或独立的 BuildingQA ReAct 基线。本地修复分支、`--implementation-mode` 与模板规划器保持移除。评测使用 `method` / `--method`，旧客户端传入 `mode` 或 `implementation_mode` 仍会返回参数错误，不会恢复旧实现。

搜索、实体/属性定位及 CSV 导入直接调用指定提交的原函数：保留固定 `bldg-59#`、原属性解析、文件行序末尾 N 行及 `xsd:float`。默认 N=100；原函数失败时记录原因，不启动其他方法。源文件和 SHA256 见 `third_party/brickqa_upstream/source_manifest.json`。

校验只记录诊断，不拒收可执行结果。Agent 遇到 stop、重复动作或达到 15 个动作时结束，选取最后生成的 SPARQL。默认无整题时限，单次 SPARQL 为 180 秒；可显式设置 `EVAL_PER_QUESTION_TIMEOUT` 或 CLI `--timeout N`，`0` 表示无整题时限。SDK 请求仍有自身网络超时。

BuildingQA 三项 F1 与用户提供的 419 行参考代码一致。新评测使用唯一作者方法；历史报告只读保留原始模式与分数，不重写为新结果。中英文、已有 TTL 选择、实时进度与报告导出继续可用。

本体合并、TTL 恢复、Qwen 适配及通用查询执行器仍是工程条件，方法统一不表示正式论文实验已经完成。

## 中英文切换和论文评分

网页评测新增“并发题数”，默认 **3**，范围 **1–8**；设为 1 可做串行对照。运行中显示每个在途题目的阶段、动作数和耗时。完成顺序可不同，报告仍按原始题序保存，并记录实际 `workers` 配置。取消会通知所有在途题目并停止启动后续题目，保留已完成和中断记录。

CLI 同样默认并发 3 题，可指定 `evaluate.py --workers 3` 或 `--workers 1`。网页用隔离 Agent 的有界线程池，CLI 用独立进程隔离图谱单例；网页的 SPARQL 也按题目使用独立查询子进程。作者工具、提示内容、停止规则和官方 F1 计算保持不变。并发会改变请求时序、模型限流和资源占用，不能把耗时变化当作作者原始串行条件；尚未测量真实模型加速倍数。

评测启动前检查基准题集与已加载建筑是否匹配，不匹配时直接提示，不调用模型。运行中显示当前题目、标准查询/模型阶段、动作数及用时；刷新页面会恢复活动评测，已完成题目和异常会持续显示。不要通过重复点击启动来恢复进度。服务重启会结束内存中的活动任务，已有逐题报告保存在 `output/evaluations/`。

运行中可点击“取消评测”，按钮随即显示“正在取消…”。当前模型或 SPARQL 调用返回后退出，不启动后续题目，保留已完成结果和当前题目的中断记录。取消与显式单题超时分别处理；取消后的分数仅是已完成题目的部分汇总，未完成题目不计零分，不能作为完整基准成绩。服务确认退出前仍保持忙碌，避免同时修改执行图。

点击每题标题展开详情，再点击“评分说明与失败原因”“对照标准与生成查询”“标准与预测结果对照”或“执行详情与过程”查看对应内容。诊断另列，原因使用真实错误或中性的结果差异说明，不将启发式诊断当作确定的错误归因。结果表最多展示 50 行，完整内容可导出 JSON；进度刷新保留当前展开状态。

网页右上角选择 **中文 / English** 仅改变显示，选择会保存在当前浏览器，运行中也可切换。controller、分解器模板和回传给模型的工具反馈始终为英文。中文示例显示中文标签，点击提交与英文界面相同的固定英文题目；手动输入的用户问题、实体 URI 和 SPARQL 保持原文，不自动翻译。

新运行的受控工具反馈统一英文；中文页面对受控提示和动作摘要做本地显示适配，英文原轨迹可展开核查，结果中的 RDF 值保持原样。历史中文运行仍明确标记；摘要不是逐句翻译，不回写报告、不追加模型调用、不改变旧实验语言。

新 API 使用 `interface_language`（zh/en）；`prompt_language` 只能为 en。旧 `language` 参数保留为显示别名。报告的 `language`、`prompt_language` 均表示实际英文模型输入，`interface_language` 单独记录显示偏好，`language_policy=english-prompts-ui-only-v1` 标记本次策略。完整提示快照用于核查实际发送内容。

评测详情采用整页向下滚动，展开的轨迹和查询自然增加页面高度，不再挤在固定高度的结果窗口内；轮询保留展开状态和当前页面滚动位置。

新报告记录 `metric_reference`：BuildingQA 固定提交、源码 SHA256、重复行与全局列映射规则、Exact Match F1 定义及汇总口径。源码哈希不符时评测会明确失败。页面主分数是已评测题目均值，报告中的 `building_macro` 供论文表 2 的建筑宏平均对照使用；两者不能混称。6 类常见反例及真实 RDFLib JSON 绑定回归用于核对评分。

完整 controller 和分解提示按 SHA256 保存于 `logs/prompt_snapshots/`。请求日志记录路径与哈希，逐题报告关联提示日志和分解提示，便于恢复真实模型输入；日志里的 500 字预览不再是唯一依据。快照包括问题和图谱上下文，请按本地实验资料管理。

网页查询固定使用 **Agent 动态探索**，不再提供自动模式和本地模板选项。长历史问题、实体名称及结果文本在各自框内完整换行显示。

查询和评测的“模型上下文 TTL”可选 NoKG，或当前建筑在项目中已有的 TTL，例如 `prompts/bldg11_sample_100.ttl`、`prompts/bldg11_sample_5000.ttl`、`buildings/bldg11.ttl`（完整路径为 `data/buildings/bldg11.ttl`）。选择后读取所选文件原文，不再从执行图重新截取 100/5000 条。切换建筑后自动更新可选文件；执行图仍由左侧加载的建筑决定。完整 TTL 可能显著增加输入 token，请按实验条件选择。评测报告记录文件路径、SHA256 和实际三元组数，并保存 `context.ttl` 快照；CLI 的旧数值上下文参数保留兼容。

英文模板保存在 `prompts/en/`，与作者提交 `49d9e283c2a3958e9be110583be6575cbd40039b` 的两个模板逐字节一致；来源和哈希见该目录的 `source_manifest.json`。两种界面语言都使用这套模板；BuildingQA 排除关闭模块，时序实验仍加入日期范围等执行指导。旧中文模板仅作历史资料保留，不进入新模型请求。切换界面不会改变配置的模型或数据。

CLI 的 `--language` 仅记录显示偏好，模型提示固定英文：

```powershell
.\.venv\Scripts\python.exe main.py --ttl data/buildings/TUC_building.ttl --language en --question "What temperature sensors are in the building?"
.\.venv\Scripts\python.exe evaluate.py --benchmark benchmarks/TUC_building_all.jsonl --context 0 --language en
```

第二条会调用配置的模型执行评测。网页与 CLI 使用同一套固定版本 BuildingQA 官方评分：`entity_set_f1`、`row_matching_f1`、`exact_match_f1`。Exact Match F1 是固定列位置下的行 F1，允许部分得分；二值完全正确率另记为 `execution_accuracy_binary`。重复行不会被去重。

模型失败以零分计入完整题目分母；标准查询失败标记为 `gold_error`，汇总分数暂不可比较。JSON 同时给出按题目均值和 `building_macro`，后者对应论文表 2 的建筑宏平均。网页提供导出，CLI 默认写入新的 `output/evaluations/<run_id>/report.json`，也可指定 `--report`。

Both interface languages use upstream English controller and decomposition templates with English runtime context, subject to the BuildingQA module ablation. The configured model is unchanged. Web and CLI evaluations share the pinned official BuildingQA Entity-set F1, Row Matching F1 and Exact Match F1 implementation. Reports preserve duplicate rows, count model failures as zero, and flag invalid gold queries separately.

## 网页工作台启动

在正常、允许联网的 PowerShell 终端中运行：

```powershell
cd D:\桌面\HKUST\Brickqa\BrickQA
npm run dev
```

打开 `http://127.0.0.1:8123/`，按 `Ctrl+C` 停止。启动入口不依赖 npm 包，无需执行
`npm install`；需要已安装 Node.js 和项目 Python `.venv`。它同时启动 FastAPI 后端和网页，
修改 Python 后需停止并重新启动。端口优先使用命令参数，其次为 `BRICK_PORT` 环境变量，默认 8123。
若端口被占用，可运行 `npm run dev -- --port 8124`，然后打开对应端口的页面；不会自动关闭已有服务。

原来的 `.\start.ps1` 仍可使用，默认端口为 8000（可通过 `BRICK_PORT` 修改）。
启动脚本使用项目的 `.venv`，API Key 从当前终端的
`LLM_API_KEY` 环境变量读取，不写入脚本或日志。仅在当前进程中设置的环境变量不会
自动出现在其他终端里；新终端需要自行配置密钥。

如果本地页面能打开，但模型报 `Connection error` / `WinError 10013`，可能是服务
继承了启动环境的网络限制。2026-10-07 本机的问题已确认是服务运行在受限进程中：
同一密钥和接口在正常权限下可用。需要重新在允许联网的终端启动服务；由 Codex
启动时需让服务在沙箱外运行。调整密钥、延长超时或反复重试不能解除进程权限限制。
网页仅保留 Agent 模式，查询和评测均需要已配置的模型接口及网络连接。

> 本文件针对本机环境编写。2026-09-12 起项目已改为 **OpenAI 兼容接口调用 Qwen 模型**，
> 不再依赖 Google Cloud / Vertex AI / gcloud，开箱即用。

## 0. Python 环境（已就绪）
依赖已装进隔离 venv（rdflib、pandas、openai），运行请使用该环境的 python：

```
.venv/Scripts/python.exe
```

⚠️ 不要用系统 `python` 直接跑——会报 ModuleNotFoundError（多个 Python 环境混淆）。

## 1. LLM 配置（已配置完成）
以下用户级环境变量已 setx（**新开的终端生效**；当前已开的终端需手动 `$env:LLM_API_KEY="..."`）：

| 变量 | 值 |
|---|---|
| `LLM_API_KEY` | DashScope API Key（已设置） |
| `LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `LLM_MODEL` | `qwen-plus-2025-12-01`（固定版本） |

换模型/换服务商只需改这三个环境变量，无需改代码：
- DashScope：`qwen-plus` / `qwen-turbo` / `qwen-max` / `qwen-flash`
- aihubmix：`LLM_BASE_URL=https://aihubmix.com/v1`
- Ollama 本地：`LLM_BASE_URL=http://localhost:11434/v1`，`LLM_MODEL=qwen2.5:7b`（Key 随便填非空值）

## 2. 运行（必须在 BrickQA 目录下执行）
代码内部用相对路径读取 `prompts/*.prompt`，**务必先 cd 到 BrickQA 目录**。

**交互模式**（可连续提问）：
```
cd D:/桌面/HKUST/Brickqa/BrickQA
C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe main.py --ttl prompts/bldg11_sample_100.ttl
```

**单问模式**：
```
& "C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe" main.py --ttl prompts/bldg11_sample_100.ttl --question "What temperature sensors are in the building?"
```

**带 schema 样本（推荐，更准）**：
```
... main.py --ttl prompts/bldg11_sample_100.ttl --schema-in-prompt prompts/bldg11_sample_100.ttl
```

## 3. 本地可用的示例 TTL 数据
- `prompts/bldg11_sample_100.ttl` / `bldg11_sample_5000.ttl`
- `prompts/TUC_building_sample_100.ttl` / `TUC_building_sample_5000.ttl`
- `prompts/dflexlibs_multizone_sample_100.ttl` / `dflexlibs_multizone_sample_5000.ttl`
- `prompts/lbnl_fdd_fcu.ttl`（配 `lbnl_fdd_fcu_hourly.csv` 可跑时序任务）

## 4. 时序评估（含 CSV 时间序列）
```
python main_temporal.py `
    --building-id my_building `
    --ttl prompts/lbnl_fdd_fcu.ttl `
    --csv prompts/lbnl_fdd_fcu_hourly.csv `
    --schema-in-prompt prompts/lbnl_fdd_fcu.ttl `
    --question "Find the maximum outdoor air temperature observed during the last 24 hours." `
    --start-date 2018-01-01 --end-date 2018-12-31
```

## 5. 代码结构说明
- `llm_client.py`：统一 LLM 客户端（OpenAI 兼容），环境变量驱动，带指数退避重试。
- `brick_agent.py` 的 `controller()` 和 `brick_decomposer.py` 的 `decompose()` 均已改为调用 `llm_client`。
- 保留的 `--project` 参数已废弃（向后兼容，不再使用）。

## 6. Brick 官方本体已自动合并（根治 subClassOf 推理）
示例建筑 TTL 只含实例与具体类型（如 `Zone_Air_Temperature_Sensor`），**不含 Brick 类继承链**，
因此 `?s rdf:type/rdfs:subClassOf* brick:Temperature_Sensor` 这类层级查询会查空。

代码现已在加载建筑图时**自动合并官方 Brick 本体**（`ontology/brick.ttl`，v1.4.4 core，约 5 万三元组），
使上述层级查询**一次命中**，所有涉及类别推理的问题都受益（如"所有温度传感器""所有 setpoint""所有 AHU 下属设备"）。

- 本体文件位置：`BrickQA/ontology/brick.ttl`
- 自定义路径：设置环境变量 `BRICK_ONTOLOGY_PATH=/path/to/brick.ttl` 可覆盖
- 找不到本体时仅打印警告、不中断，但层级查询可能返回空

## 7. 常见问题
- **ModuleNotFoundError: rdflib / openai**：用错了 Python，请用第 0 步的 venv python。
- **LLM_API_KEY 未设置**：见第 1 步；或当前终端手动 `$env:LLM_API_KEY="sk-..."`。
- **429/限流**：客户端已内置指数退避重试；controller/decomposer 保留 6s/60s 冷却。
- **search_brick 偶发 "Expected SelectQuery, found 'FILTER'"**：agent 探索过程中的已有小瑕疵，不影响最终结果（会自动重试其他策略）。
