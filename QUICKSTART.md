# BrickQA 本地启动指南（Qwen 版）

## 唯一方法：BrickQA 作者方法

网页、API、Python 和 CLI 均只提供作者方法，已移除方法下拉框、`--implementation-mode`、本地修复分支及本地模板规划器。直接加载建筑后查询或运行评测，无需选择方法。旧客户端传入 `mode` 或 `implementation_mode` 参数会返回参数错误，而不会切换到其他实现。

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

网页右上角选择 **中文 / English**，界面、示例问题、controller 与分解器提示会一起切换，选择会保存在当前浏览器。运行中暂时锁定语言，避免一个任务混用两套提示。问题原文、实体 URI 和 SPARQL 不会被翻译。

英文模式下，新运行的受控工具反馈（空结果、语法/前缀错误、停止等）使用英文，结果中的 RDF 值保持原样。历史中文运行会明确标记，英文界面显示按动作生成的英文步骤摘要及受控反馈；原始中文轨迹可展开核查。这些摘要不是逐句翻译，也不会回写报告或追加模型调用。仅切换界面不会把一次中文实验重标为英文实验。

评测详情采用整页向下滚动，展开的轨迹和查询自然增加页面高度，不再挤在固定高度的结果窗口内；轮询保留展开状态和当前页面滚动位置。

新报告记录 `metric_reference`：BuildingQA 固定提交、源码 SHA256、重复行与全局列映射规则、Exact Match F1 定义及汇总口径。源码哈希不符时评测会明确失败。页面主分数是已评测题目均值，报告中的 `building_macro` 供论文表 2 的建筑宏平均对照使用；两者不能混称。6 类常见反例及真实 RDFLib JSON 绑定回归用于核对评分。

完整 controller 和分解提示按 SHA256 保存于 `logs/prompt_snapshots/`。请求日志记录路径与哈希，逐题报告关联提示日志和分解提示，便于恢复真实模型输入；日志里的 500 字预览不再是唯一依据。快照包括问题和图谱上下文，请按本地实验资料管理。

网页查询固定使用 **Agent 动态探索**，不再提供自动模式和本地模板选项。长历史问题、实体名称及结果文本在各自框内完整换行显示。

查询和评测的“模型上下文 TTL”可选 NoKG，或当前建筑在项目中已有的 TTL，例如 `prompts/bldg11_sample_100.ttl`、`prompts/bldg11_sample_5000.ttl`、`buildings/bldg11.ttl`（完整路径为 `data/buildings/bldg11.ttl`）。选择后读取所选文件原文，不再从执行图重新截取 100/5000 条。切换建筑后自动更新可选文件；执行图仍由左侧加载的建筑决定。完整 TTL 可能显著增加输入 token，请按实验条件选择。评测报告记录文件路径、SHA256 和实际三元组数，并保存 `context.ttl` 快照；CLI 的旧数值上下文参数保留兼容。

英文模板保存在 `prompts/en/`，与作者提交 `49d9e283c2a3958e9be110583be6575cbd40039b` 的两个模板逐字节一致；来源和哈希见该目录的 `source_manifest.json`。运行时仍会加入当前图谱命名空间、日期范围和必要的执行指导。切换语言不会改变配置的模型，也不会撤销本体合并或工具修复。

CLI 可指定提示语言：

```powershell
.\.venv\Scripts\python.exe main.py --ttl data/buildings/TUC_building.ttl --language en --question "What temperature sensors are in the building?"
.\.venv\Scripts\python.exe evaluate.py --benchmark benchmarks/TUC_building_all.jsonl --context 0 --language en
```

第二条会调用配置的模型执行评测。网页与 CLI 使用同一套固定版本 BuildingQA 官方评分：`entity_set_f1`、`row_matching_f1`、`exact_match_f1`。Exact Match F1 是固定列位置下的行 F1，允许部分得分；二值完全正确率另记为 `execution_accuracy_binary`。重复行不会被去重。

模型失败以零分计入完整题目分母；标准查询失败标记为 `gold_error`，汇总分数暂不可比较。JSON 同时给出按题目均值和 `building_macro`，后者对应论文表 2 的建筑宏平均。网页提供导出，CLI 默认写入新的 `output/evaluations/<run_id>/report.json`，也可指定 `--report`。

English mode uses the original upstream controller and decomposition templates with English runtime context. The configured model is unchanged. Web and CLI evaluations share the pinned official BuildingQA Entity-set F1, Row Matching F1 and Exact Match F1 implementation. Reports preserve duplicate rows, count model failures as zero, and flag invalid gold queries separately.

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
| `LLM_MODEL` | `qwen-plus` |

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
