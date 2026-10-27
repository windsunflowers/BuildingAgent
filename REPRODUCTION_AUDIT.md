## 2026-10-26 bldg11 5000T 作者提示片段解析修复

定位：prompts/bldg11_sample_5000.ttl 为5000行文本，末尾停在 sh:rule 空白节点内部，未闭合，RDFLib报EOF。与固定作者提交49d9e283c2a3958e9be110583be6575cbd40039b同路径文件原文一致，仅CRLF/LF差异。本地原始SHA256=fd704e01d857d71d45643392a448e992489545cfaa527416111e5911f8b0ea82；作者/LF归一化SHA256=6c0495503d2fb7a145b7ecaba6f9c776ce725a9f0fc043e7637346698dc990c7。

根因：网页 _prepare_ttl_context 对所有提示TTL强制Graph.parse计数，错误地把作者的截断提示文本等同于完整可解析执行图。修复为仅对确切项目路径、固定归一化SHA、原EOF错误的已审查作者文件接受原始提示文本。保留全部原文字节和提示内容，不补括号、不删末尾、不重新采样、不作为执行图。其他损坏文件照旧400拒绝。

上下文元数据 kind=author_prompt_text_fragment，parse_status=incomplete_upstream_turtle，line_count=5000，triples=null，并记录源提交与双哈希。模型不额外注入这些说明；UI在报告展示提示片段状态。5000T为文件名/实验标签，不能把5000行称作已验证5000条三元组。原数据执行仍为完整bldg11图，未改原样本或历史报告。

100项相关离线回归通过，包括原字节保留、未审查改动拒绝、提示原文注入而执行图不变，以及既有中英文/评测/基线测试。服务空闲重启启用；未请求模型或自动重跑评测。

## 2026-10-26 九道标准查询超时修复（本地 RDFLib）

在用户明确要求解决九道标准查询超时、保留本地 RDFLib 与单次180秒预算后，将已验证的连接重排集成为显式执行器适配。rdflib_execution.py 通过 CUSTOM_EVALS 仅为 Project/Distinct/BGP 构成的无限制 SELECT 在每步绑定后重选未绑定节点最少的模式；单模式仍调用 RDFLib 原 evalBGP。包含 Slice/LIMIT/OFFSET、ORDER BY、聚合、BIND、OPTIONAL、UNION、子查询等的整个查询不启用优化。无查询重写、无图改动、无GraphDB、无LIMIT追加、无金标准改写。优化上下文按请求隔离并覆盖惰性物化，结束或异常均恢复。BRICK_RDFLIB_OPTIMIZER=native 可回到原生求值；默认 connected_bgp。作者源文件不修改，不能把该适配标作执行器完全原样。

新元数据在 method_policy.rdflib_execution / 本地 ReAct baseline_reference.rdflib_execution 记录 RDFLib版本、模式、适用范围及无ORDER BY结果行序可能变化。单次预算仍180秒，不向模型注入金标准。黄金及预测共享同一本地执行通道，搜索/定位原作者工具直接 graph.query 不受请求优化上下文影响。

九道原始 gold 在正式 query_graph/隔离进程通道下分别返回470行，首次约0.968秒、其余约0.140–0.250秒，完整多重集均与独立本地图遍历一致；原报告字节未改。证据 output/validation/nine_gold_rdflib_fixed_20261026.json。补跑题集保留原题和gold，只抽取原索引68–76，写入 output/validation/bldg11_mortar009_retry_20261026.jsonl。

验证：228项完整回归通过，之后新增的重复行/RDF类型差分用例及原执行器用例共16项定向测试通过。服务已重启，单次180秒、Qwen固定版本与NoKG条件不变。仅补跑9题，任务e819b9f2c24d94ad18a066a3fbcf540ec，9/9完成、gold_error=0、model_error=0。新补全报告eef502e8234cf4ab89ecd0f7b74764d16复用原67题并替换9题，全部76题均有成功标准结果，保留原2个模型语法错误计零：Entity=0.36548762206588403，Row=0.28137814359687185，Exact=0.11294072153439859。新报告逐题带来源及原/补跑报告SHA，configuration.completion_provenance标注mixed_execution_policy=true；不能称为整轮统一执行器条件的新模型实验。旧报告哈希保持2341450d5269fc21156956050ef3d49db08f3d66ab2ed0568cbdb9271be2a726。

## 2026-10-26 MORTAR_009 超时解决方案只读验证

针对 e69c5d55371da4354b7c3f5f74f2ba16f 的9个重复 gold_error，读取保存的同一 gold_execution_sparql（不改查询），在空闲状态只读测试：原生 RDFLib 串行于20秒诊断预算超时；GraphDB 原查询首次约6.687秒返回470行。再按本地原始62578三元组独立计算 rdf:type/rdfs:subClassOf*、hasPoint、feeds+、HVAC_Zone 连接（保留多重集），470行，与 GraphDB infer=false 返回逐项多重集一致；该次关闭推理的远程查询约0.234秒。这里只证实这条查询，不证明两后端所有语义/推理条件相同。未把独立核算替换为正式gold。

独立 CachedPathGraph 属性路径缓存探测仍在20秒预算超时；未接入正式代码。不能把该失败实验写成已完成加速。建议路线：如采用GraphDB执行适配，gold与生成查询均统一后端，并先核对建筑数据/推理、固定配置；按图数据哈希+完整查询+后端/推理配置缓存成功的全量gold，重复变体不重复执行。若坚持原生作者RDFLib条件，则保留独立实验、进行通用等价执行计划优化，不擅自改gold、加LIMIT或删题。增加SPARQL预算只作为临时诊断措施，不视为性能根治。

本轮无生产代码变更、无模型调用、无历史结果修改。证据：output/validation/mortar009_execution_probe_20261026.json、mortar009_independent_crosscheck_20261026.json、mortar009_path_cache_probe_20261026.json。

## 2026-10-26 BuildingQA ReAct 方法 + 固定 Qwen 的最终口径

用户再次明确：对齐 BuildingQA 的 ReAct 方法，模型继续 qwen-plus-2025-12-01。本轮不再将“必须改 Gemini”作为方法对齐条件；metadata 将误导性的 paper_model_required 改为 caller-selected model policy，并将 Gemini 仅标作 BrickQA 论文历史模型。未自动更换模型。

联网核验：BuildingQA 当前官方 main 为 b792a627419dfb679ad1f26e4d3dc325a758e95b；官方原 ReAct SHA256=91f3409b15df57d652895fa0b94b7668cc6cdafaeb0cecb1c17784e4bbdcd52e，metrics SHA256=d7d982fe1f9eaa020d00615ec8ab48ed6f0b6117cd4963a53f8e39473447010b，与本地固定源码一致。

两轮分数：e0d61c67fd4ff4e58a045f47a983cc6c4 为 GraphDB 0.277778/0.277778/0.138889；e8658797f887647a9bd505e1b8f7ef412 为 RDFLib 0.342593/0.291667/0.138889。均 DFLEX 36 题、同上下文哈希、固定 Qwen；629 条提示图与建筑源图同构。RDFLib 36/36 题、168 次请求通过原循环回放；GraphDB 35/36、200 次请求通过，另第30题是 Writer 首轮连接失败，缺少模型响应，不可冒称已完成回放。两轮各2题错误；GraphDB 27题、RDFLib 22题耗尽三轮，其余停止类型另在原报告保存。出现非空中间结果后末次为空并不允许事后选最佳候选。

实际修正：原 Notebook 的 client=OpenAI(...) 不设置 max_retries，当前所用 SDK 默认2；本地却显式关闭 SDK 重试。现仅 ReAct 通过 with_options(max_retries=2) 恢复该行为，应用层仍只调用一次，不叠加外层重试。BrickQA 原客户端 retry 配置不变。请求日志和 baseline_reference 写明 SDK retries=2；保留用户批准的300秒网络等待预算。离线 HTTP MockTransport 返回503、503、200，确认单次角色调用的SDK发起3次尝试并成功，基础共享客户端仍max_retries=0。该修正针对临时网络失败，不声称能把语义准确率提升至某个历史数值。

已对齐并保持：原英文 Writer/Critic 提示及历史追加、Notebook最多3轮、temperature=0、JSON object、不设输出token上限、Critic FINAL提前结束、末次查询、默认GraphDB前十行反馈、显式RDFLib行数反馈、gold/pred同后端与全量bindings官方评分。用户自定Qwen、300秒、并发调度、冻结TTL文件及执行器等条件保持显式；不改变金标准、注入测试规则、替换末次答案或强制Exact归零。

验证：213 项完整离线回归通过（2 个已有 FastAPI 弃用警告），服务空闲重启生效，恢复 DFLEX；实际 SDK 选项仅本地构造核验，不请求模型。

本轮新审计产物：output/validation/react_e8658797f887647a9bd505e1b8f7ef412_audit_20261026.json 与 react_e0d61c67fd4ff4e58a045f47a983cc6c4_audit_20261026.json。旧分数不重算覆盖，无真实模型调用。

## 2026-10-26 英文模型链路与原文历史

按用户要求，将解析失败后的固定 Thought/Action 格式重试提示、解析耗尽与重复动作提示、缺失 Thought 的补充文案及动作异常包装统一为英文。不再根据界面语言生成这些消息；删除未调用的中文 _build_controller_prompt 备用入口，实际控制器仍唯一使用作者英文模板及既有消融派生。

历史 observation 保留工具/模型数据原文：取消 execute_action 对整段观察或异常详情的 feedback() 替换；SPARQL 异常仅加英文固定包装，原始异常内容保持不变；结果表、RDF 字面值、URI 不替换。移除对 error 动作 observation 的额外重写。底层平台自有 SELECT/ASK、SERVICE 拒绝和查询超时错误在源头用英文生成。原文为中文的数据或第三方异常仍作为原始数据保留，不能为追求字符集纯英文而丢弃/翻译原始证据。中文问题不翻译；本次按用户英文问题场景验证。

中文展示只由 ui/app.js recordedFeedback 派生，补齐重试、PREFIX、未知动作及超时消息展示；需要翻译时提供原文折叠项。旧报告仅展示，不重写原记录。新 LANGUAGE_POLICY=english-prompts-verbatim-history-ui-only-v2，区分历史条件；不改变模型、三轮、原模板、gold 和官方三项 F1。

验证：211 项完整离线回归通过；随后增加的展示层测试连同两项模型历史测试 3/3 通过。两个界面语言在解析重试、空搜索、工具异常、SPARQL 和停止路径的完整请求逐字一致；英文问题及英文工具内容下请求不含中文。独立测试确认特意含中文的 RDF 值/第三方错误原文不被改写。测试没有真实模型调用。服务空闲后重启启用，不自动重跑评测。

## 2026-10-26 宽表官方评分阶段显示修正

e055fffde2d90446494951b6835260f81 已完成 33/36，剩余 DFLEXLIBS_001 三个问题变体。Agent state.phase 已为“完成”，但评测还在执行 score_rows；旧 UI 仅有 gold/model 阶段，误显示“完成”并持续计时。这不是 LLM 网络等待。该标准查询投影 16 列、1080 行，其中首行实际绑定 10 列；固定作者 scorer 从首行 keys 决定映射列数，并枚举候选预测列的一对一排列，每种映射执行嵌套逐行比较，搜索默认 timeout=1200 秒，在映射之间检查，非强制整题截止时间。

修改：evaluate_question 在评分前发送 scoring 阶段、保留评分后的轨迹，并在评分前后检查取消事件；app 记录阶段开始时间与阶段耗时，状态接口支持评分阶段；UI 支持新 scoring 状态，同时将旧运行的 model/phase=完成显示为“计算官方 F1（列匹配可能耗时）”，中英文一致。静态资源版本更新，当前运行刷新即可正确显示；服务不重启，既有运行不打断。新后台阶段字段在下次正常服务重启后启用。

未修改作者评分源码、列映射、1200 秒预算或结果选择；未将未完成题计零。99 项定向回归通过，含新旧阶段显示、评分前事件顺序、轨迹/token 保留。当前问题没有被描述为“已加速”：严格保留原评分实现仍可能耗时较长，取消也不能中断已进入的原始单次评分函数。

## 2026-10-26 LLM 请求超时从 30 秒调整为 300 秒

按用户要求增加长请求等待时间。llm_client.llm_timeout_seconds() 统一解析 LLM_TIMEOUT（默认 300 秒，校验有限正数），传给 SDK；ReAct baseline_reference、网页/CLI 总配置和逐题记录同一实际超时值。错误提示包含当前超时秒数；状态接口提供 model_timeout_seconds。保留原模型、提示、生成参数、三轮上限与重试次数，此为运行环境变更，不归因于论文算法提升；旧报告原环境值不重标。

用户明确选择“现在中断本轮并重启”。已先请求取消 edd549ee2929b4f0fb3e7225ebadeff45，再将保存报告备份至 output/validation/llm_timeout_pre_restart_20261026.json 后重启；原报告不重算。重启后旧轮显示 interrupted，保留 23 条结果，未自动补跑。恢复 dflexlibs_multizone 图谱；状态与真实 SDK 均确认 timeout=300，无真实模型请求。115 项相关离线回归通过（含默认值、600 秒覆盖、非法值、SDK/元数据一致性）。模型仍 qwen-plus-2025-12-01。

网络等待上限不是整题总时限；显式整题预算可提前取消。客户端创建后读取配置，修改环境变量需重启。增加等待时间不能保证上游故障、断网或服务端主动超时时成功。

## 2026-10-25 两后端差异与官方评分复核

核对最新 TUC/DFLEX 两后端四轮报告（132 题、706 次模型请求），原作者循环、停止与评分回放均通过。将 GraphDB 保存的最终查询在 RDFLib 重放，TUC/DFLEX 三项均值分别仍为 0.316667/0.300000/0.200000、0.194444/0.194444/0.083333，与原 GraphDB 记录一致。两组真实模型运行的最终查询不同，不能把原均值差直接归因于执行引擎。Exact 非零符合固定 scorer 的按列位置结果匹配定义；不强制归零。模型仍是用户固定 Qwen，作者历史 Exact CSV 差异仍未解决，未宣称论文定量复现完成。本次无新的模型调用、无历史结果覆盖、无算法改动。

详细证据与限制见 output/validation/REACT_BACKEND_COMPARISON_20261025.md；新增离线循环审计与同查询重放 JSON。当前 GraphDB 未运行，重放比较历史远程结果与当前本地执行，并非今天新的远程模型实验。

## 2026-10-24 统一 Notebook 默认 GraphDB / 最多三轮

原始固定 ReAct_demo.ipynb 明确 USE_LOCAL_TTL_FILE=False、max_iterations=3。按用户要求，API EvalRequest、后台入口、CLI --react-backend、evaluate_item 兼容参数、evaluation_agent 工厂、ReActBaselineAgent 与 reference 元数据默认均统一为 graphdb。网页已有 GraphDB 默认选择，不改变旧报告实际后端。显式 rdflib 保留为作者本地分支，不在远程失败时回退。最多三轮为原固定常量，Critic FINAL 可以提前结束；耗尽后仍提交最后生成查询。

GraphDB 继续使用用户原有三个仓库地址、作者前十行 bindings 反馈、原英文 Writer/Critic、temperature=0 和官方评分。模型/上下文未自动更换，未自动重跑任何评测。新增回归从默认工厂构造 GraphDB Agent，模拟三次 Writer 与三次 Critic IMPROVE，断言六次模型调用后结束及三轮元数据；原 RDFLib 测试改成显式选本地，避免把默认值变化误当算法变化。

## 2026-10-24 GraphDB 连接拒绝修复

实际原因：本机 GraphDB 未运行，127.0.0.1 与 CHINAMI-42UOT9U:7200 均实测 WinError 10061，无监听进程。这是传输层故障，不能据此判断 gold 查询语法有误。使用原安装 GraphDB Desktop 恢复服务，保留现有 Roaming/GraphDB 数据目录及 TUC_building_test、DFLEX、bldg11 仓库；未修改端点、数据或推理设置。

react_graphdb.py 区分 HTTP 查询错误与 URLError/OSError 传输异常；传输异常包含仓库地址及检查提示。网页启动 GraphDB ReAct 评测前执行只读 SELECT (1 AS ?ready) WHERE {}，失败返回 HTTP 503，中英文提示“评测尚未启动”，不创建评测任务、不调用模型、不回退 RDFLib。运行中断线仍按原 gold_error 规则阻止可比较汇总，历史报告不修改。

验证：三个配置仓库均成功返回 ready=1；TUC 第一条原始 gold 返回 ZoneID/point 两列、18 行。证据 output/validation/graphdb_connectivity_20261024.json。完整离线回归 200 passed，2 个已有弃用警告。空闲工作台重启后恢复 TUC 建筑，未自动发起模型评测。GraphDB 必须在使用远程后端时持续运行。

## 2026-10-24 评测结果宽表格显示修正

截图中的标准答案有多列，通用 table-layout:fixed 与 overflow-wrap:anywhere 将列平均压缩并逐字断行。本次仅调整 evaluation-comparison 内的表格：自动列布局、内容宽度、最小列宽 120px、保持表头/单元格/URI 按钮不拆行，由各自 table-wrap 横向滚动。标准和预测面板仍分别占据可用宽度，小屏按已有规则上下排列。更新静态资源版本使刷新加载新样式；数据、评分和查询不改变。验证范围为样式与页面结构静态检查，未启动新模型评测。

## 2026-10-23 作者协议复核与修正

结论：已实现 BrickQA Agent 和独立 BuildingQA ReAct，并完成多项源码对齐；仍不能宣称论文完整定量复现。基准固定 BrickQA 49d9e283c2a3958e9be110583be6575cbd40039b、BuildingQA b792a627419dfb679ad1f26e4d3dc325a758e95b。下述新规则取代本文旧的本体合并/本地修复说明，历史报告不改写。

### 本次已修正

- prompting.py：删除控制器尾部本地命名空间、类路径、时间范围与输出指令；分解器不再接收从执行图提取的额外命名空间/时间范围。保留作者英文模板、已有模块消融和空会话模板渲染适配。
- app.py：标准评测禁用交互界面的 schema_description，结束/失败均恢复；CLI 本来不加载此描述。NoKG 不再从该描述获得静态建筑知识。报告记录 schema_description_in_prompt=false。
- brick_utils.py：不再自动合并独立 Brick 本体。新加载的执行图按作者使用建筑 TTL；源图与执行图初始化三元组一致。远程 GraphDB 仓库数据不作改动，仍须核实其推理/导入设置。
- brick_agent.py / implementation_policy.py：从校验 SHA256 的原始作者文件 AST 提取并执行原 _validate_and_fix_sparql；恢复固定 bldg-59#、去除时间戳 Z、DESC 无 LIMIT 自动补 LIMIT 1 等作者行为。执行层只在没有 PREFIX 时补原常量，不再调用本地 namespace 重写。作者这些行为未必适合所有建筑，但不以本地改良冒充复现。
- llm_client.py：BrickQA controller/decomposer 不再强制 temperature=0 和 max_tokens=2048；像作者 generate_content 一样不显式指定。所选 API 的默认值不保证等于 Vertex AI；模型与供应商仍是独立差异。ReAct 继续显式 temperature=0、JSON object、不设 token 上限。
- BrickQA 与 ReAct 均保存全量 SPARQL JSON bindings，并交给同一固定官方三项 F1。显示用字符串行不再作为 BrickQA 评分入口；这不改变官方归一化函数，也不承诺必然改变得分。

### 已验证与结果解释

- 完整离线回归：197 passed；2 个已有 FastAPI on_event 弃用警告。新检查覆盖原始图无本体追加、RDF 类型/未绑定变量、执行层不改声明命名空间；已有用例核对作者 LIMIT/Z 行为、标准评测上下文隔离及恢复、中英文模型输入分离、ReAct 源码循环和评分。
- 重新审计 e15354bfb31034bfea00e322a530d7b25：30/30 题、178/178 次调用与原 ReAct 循环相符，见 output/validation/react_workflow_reaudit_20261023.json。这是保存响应回放，不是新模型实验；报告原 SHA256 保持不变。
- 论文第 4.1.3 节使用 Gemini 2.5 Flash；当前用户固定 Qwen，不能将它标作同模型复现。标准 BuildingQA 关闭 Temporal/Operations，ReAct 为 Notebook 3 轮而非类默认 5 轮；GraphDB 给前十行 bindings，RDFLib 仅给行数。低分不能作为擅自改变 Critic 提示、停止规则或选择最佳历史查询的理由。
- 既有诊断显示 Critic 可能将正确类型改为不存在的类型，导致可执行但零行；语法合法不代表语义正确。详见 output/validation/REACT_TUC_E153_DIAGNOSIS_20261022.md。
- 既有作者 CSV 查询回放中，TUC 5000T Entity/Row 逐题一致，但 Exact 历史 0 与固定源码重算 0.444444 不一致；缺少作者当时 bindings/环境，原因未解决，不改 scorer 凑分。

### 尚未完成 / 阻塞完整复现

- 尚未按论文模型与相同 API/数据条件重跑三个建筑 × NoKG/100T/5000T × 两种方法；未测量本轮修正后的新 F1。Table 2 Total 要使用建筑宏平均，不能比较单个 TUC 或题目加权均值。
- GraphDB 数据版本/推理配置、论文采样上下文字节、作者历史 Exact 评分环境尚未全部核实。保留已有 TTL 样本而不重新随机取样。
- SDK/解析器/隔离执行器、修复过的输入 TTL、模块消融提示派生、失败处理和供应商默认生成参数仍须作为工程适配披露。LBNL 时序案例不属于本次已完成定量实验。
- 本次没有模型调用、没有重算覆盖历史报告；检查时 8123 没有运行服务，新代码在下次 npm run dev 启动后生效。

# BrickQA 复现审计与项目边界

2026-10-22 评测布局微调：设置与操作分为两行，并发题数标签/输入框保持同组，运行/取消/导出按钮和进度位于第二行。HTML 结构核验通过，静态资源版本更新；仅修改布局，无实验条件变化。

2026-10-22 评测入口收敛：BrickQA 选择下隐藏 ReAct 后端标签/下拉框及 ReAct 专属说明，切到 ReAct 才显示；BrickQA 专属模块说明同样按方法显示。/api/benchmarks 根据当前实际加载 TTL 的规范化绝对路径筛选，排除其他建筑、混合建筑、无 TTL 声明及无效文件；建筑切换立即清空旧选项并重载，异步旧响应不会覆盖新建筑列表。无匹配题集时禁止启动评测；历史报告仍保持原样展示。新增两项回归验证匹配边界、建筑切换和界面显示/忙碌状态，连同既有报告显示测试共三项通过，Python/JS 语法通过。本次不改作者方法、模型或评分，也不调用模型。

2026-10-22 低分复核：截图对应 e15354bfb31034bfea00e322a530d7b25，实际为 RDFLib + 固定 Qwen，并非控件当前显示的 GraphDB。30/30 题、178/178 次真实消息与固定作者循环一致，23 题合法空结果；首题 Critic 将实际存在的 Max_Air_Temperature_Setpoint 错改为无实例的 Maximum_Air_Temperature_Setpoint。保存查询 GraphDB 回放中 16 题修订后 Row F1 下降，最终三分与原报告一致。修复报告实际后端/模型显示、下一轮选择差异提示、服务端后端回执及空结果说明，更新静态资源版本；不修改作者算法或挑选更高分候选。作者公开 TUC 查询在当前仓库的 Entity/Row 逐题 30/30 复现；Exact 历史 0 与固定源码重算 0.444444 的差异仍待原始环境/bindings 核实。192 项回归通过。详细证据见 output/validation/REACT_TUC_E153_DIAGNOSIS_20261022.md，旧报告哈希不变；未调用模型重跑。

2026-10-22 GraphDB 后端：已接入用户三个仓库；ReAct 远程分支使用作者前十行真实 bindings 摘要，本地分支保留行数摘要。网页显式选择，GraphDB 默认；兼容 API/CLI 默认 RDFLib。两分支的 gold/预测共用各自执行器，远程错误不回退，完整 bindings 送固定 scorer。报告区分 implementation_mode、endpoint、graph scope、feedback policy 及服务端默认推理未核实状态。191 项离线测试通过，包括直接执行作者远程函数对照、真实本机 HTTP、同仓库 gold/预测、15 行完整评分、远程错误正文与后端传参。未自动更换固定 Qwen 或调用模型；数据版本、GraphDB 推理配置和论文模型一致性仍须单独核验。远程取消等待当前 HTTP 返回/180 秒超时，未引入后台重试。

实仓库只读验证：TUC 5/5、DFLEX 6/6、bldg11 的 human 文件中 31/31 条（含相同 query_id 的题目变体）gold 均成功执行。bldg11 的缺省前缀按既有 gold_query_text/作者 notebook 规则补源 TTL 声明，原 gold 不改写。TUC/DFLEX 的远程行数与本地源图逐题相同；bldg11 本地逐题对照耗时较长而中止，不宣称两边结果完全一致。默认计数和 infer=false 计数均为 101515/629/98592，这不能证明推理配置与作者相同。证据：output/validation/react_graphdb_live_checks_20261022.json。服务已重启，恢复 TUC 与固定 qwen-plus-2025-12-01，空闲且未自动重跑模型评测。

2026-10-22 补充对齐及完整验证：ReAct 错误摘要改为直接使用执行器原始错误，避免界面翻译替换异常中引用的名称或数据；三项 F1 直接以全量类型化 SPARQL JSON bindings 输入固定作者 scorer，保留未绑定字段、重复行和列顺序。新增原始错误及带 datatype/lang、未绑定列、重复行的评分输入回归；全套 184 项测试通过（两个既有 FastAPI 弃用警告），Python/JavaScript 语法及 diff 空白检查通过。此前 52 项局部验证及 DPAPI 权限限制是历史状态，本轮在当前 Windows 用户权限下补齐网页/CLI 入口验证。未调用模型重跑；固定 Qwen、RDFLib 与原论文模型/远程后端仍属不同条件。

2026-10-22 RDFLib 分支反馈对齐：按用户最新要求，ReAct 移除传给 Critic 的列名/总行数附加头与前十行预览，恢复作者本地 RDFLib 的成功行数、空结果及错误摘要。新 implementation_mode=buildingqa_react_rdflib_author_v1，feedback_policy=upstream_rdflib_row_count_only_v1。3 轮、固定模型、原始建筑执行图及完整结果的三项官方评分保留。旧报告不重写；模型替换、执行预算和 SDK 适配仍是剩余差异，不代表论文数值复现完成。52 项离线回归通过，包括作者 RDFLib 函数独立执行对照；网页/CLI 两项入口检查因当前 Windows 用户无法解密本机模型配置未通过，暂不计入验证。未重启服务或发起真实模型评测。

2026-10-21 用户文件对齐：按 react_baseline_implementation.md 修正 ReAct 直接使用 TTL 源图，gold/pred 同图，完整 SPARQL JSON bindings 与结构化结果/辅助评测字段对齐；原始提示四段 AST 相同。用户确认保留 3 轮、列名/前十行反馈与固定 Qwen。新模式 buildingqa_react_document_v1，旧合并图实验保留。完整对照与剩余平台边界见 output/validation/REACT_USER_DOCUMENT_ALIGNMENT_20261021.md。

2026-10-21 新反馈后的完整 30 题复核：报告 e041bd33988b847c1a8d67bc41278d9b9 为 0.308333/0.233333/0.166667，15 题合法空结果、3 题实际查询错误，10 题 Critic FINAL、20 题三轮结束。用该轮真实响应与保存的执行反馈，直接执行固定源码原循环：30/30 题、146/146 次消息、最终查询选择与保存的三项评分均一致，证据见 output/validation/react_actual_workflow_replay_20261021.json。本次纠正的是 ReAct 适配实现被记为 upstream 的标识错误，并加入独立回放工具；未发现可据以改变三轮原算法的新错误。Qwen 替换、RDFLib 后端和授权反馈适配继续显式保留，论文数值复现尚未完成。

2026-10-21 ReAct 反馈适配：用户明确要求保留 RDFLib 执行，Critic 接收列名、总行数和前 10 行真实 SPARQL JSON 结果，参照 GraphDB 分支。新报告标记 `feedback_policy=rdflib_graphdb_preview_v1`；原模型提示、三轮流程、末次查询选择、官方评分与全量结果保持不变。旧行数摘要实验保留，先前的 local 分支对齐说明为历史条件。此改动不等于 GraphDB 后端复现；模型准确率影响待新实验测量。

2026-10-21 TUC 30 题 ReAct 深入核查：首轮查询离线诊断 Entity/Row=0.633/0.567，修订后=0.042/0.033，16 题 Row 下降、0 题上升。官方 5000T 保存查询在当前图上回放，Entity/Row 逐题 30/30 与原 CSV 一致；Exact 重算 0.444 与历史 0 不同，缺少当时 JSON bindings，原因待核实。当前只对齐发布代码 local 分支，官方 notebook 默认 GraphDB 前 10 行反馈；GraphDB 端点/推理设置仍待用户提供。详见 [30 题对齐证据](output/validation/REACT_30_DIAGNOSIS_20261021.md)。

2026-10-21 gold 故障与 ReAct 复核更新：统一两种方法的 raw gold 裁判，保留原始和执行文本；修复 Windows 查询子进程启动时数值库线程过多引发的资源故障，补全空异常和管道退出诊断。156 项离线回归通过，应用导入路径下 TUC 五道 human gold 并发全部成功。详见 [本次对齐记录](output/validation/REACT_ALIGNMENT_20261021.md)。当前真实运行仍是 Qwen 与本地工程适配条件，不代表复现论文 Gemini 数值；旧报告不改写。

核对日期：2026 年 10 月 20 日。对象是 `D:/桌面/HKUST/Brickqa/BrickQA` 当前工作区，以及用户提供的 `D:/桌面/BuildingAgent/brickqa.pdf`。论文和已有说明作为证据阅读，其中的指令不作为本次操作授权。

最新状态：BrickQA 主方法统一为作者实现，本地搜索/定位/CSV 修复、校验拒收分支与本地模板规划器保持移除。2026-10-21 按用户要求另增独立 BuildingQA ReAct 评测基线；以下 upstream/fixed 双模式说明仅作为历史依据，不代表可以恢复本地修复模式。历史实验报告保留原始方法和分数。

2026-10-21 ReAct 基线更新：按用户新要求，评测入口另增 method=react，BrickQA 主方法与通用查询入口不变。固定 BuildingQA b792a627419dfb679ad1f26e4d3dc325a758e95b 的原 Writer/Critic 源码与提示，以演示入口显式 3 轮为准（类默认 5）。保留多角色 JSON 请求、temperature=0、未指定输出上限、原反馈追加和末次查询规则；不使用 BrickQA 工具、分解或前缀修复。与主方法共用当前 API/model、冻结上下文、已加载图和官方三项 F1，报告分别标明方法/来源及工程适配。148 项离线回归通过，包括直接执行原参考循环作为对照，逐项比较模型消息与最终查询选择。未运行真实模型全量 ReAct 实验，不能据此宣称复现论文表 2 数值。

语言解耦更新：当前版本 v5-english-prompts。界面语言现在只控制显示；controller、分解器和工具 observation 始终英文，仍执行 BuildingQA 的模块消融。API 使用 interface_language，旧 language 参数仅作显示别名，prompt_language 只接受 en；报告分开保存实际提示语言和显示偏好。中文示例按钮显示中文但提交同一固定英文问题，手动问题保持原文。原始英文模板和历史中文记录保留，显示适配不重写轨迹或追加模型调用。126 项离线回归通过，其中完整 Agent 流程验证两种显示语言的实际模型提示、observation 和最终 SPARQL 逐字一致。本次没有真实模型评测调用，Gemini 配额问题仍单独待处理。

模块消融对齐更新：BuildingQA 网页与 CLI 评测现在将两个关闭开关传至分解提示和 JSON 解析，派生 sensors_only 提示时去掉 Temporal/Operations 指令、字段及混合示例，保留实体规则与领域映射。控制器关闭相关分解行、时序指南及日期范围指导，额外返回的关闭模块字段被忽略。LBNL 完整分解提示保留原样，`main.py --experiment lbnl_fdd` 显式启用完整模块，不能与禁用参数冲突使用。数据加载和时序答案核验仍是独立实验要求。新报告增加 decomposition_policy 与 experiment，提示版本为 v4-module-ablation；这是对论文模块消融要求的本地运行时适配，不宣称找到作者发布的专用 sensors_only 模板。原模板与官方 scorer 文件未改，历史报告未重算；本次不调用模型重跑。

本次模块消融验证：119 项离线回归通过，覆盖中英文实际分解提示、关闭字段的额外/非法响应、控制器注入、并发子任务与父配置隔离、CLI 实验配置冲突，以及完整提示逐字保持。Python 编译、前端 JavaScript 和 diff 空白检查通过。Gemini 既有 HTTP 429 配额问题不属于模块开关修复，仍需另行处理请求调度或项目配额。

模型选择更新：右侧滑动面板支持现有 Qwen 与 Google `gemini-2.5-flash`，密钥按供应商用 Windows 当前用户 DPAPI 加密保存，任务运行期间禁止切换。客户端按配置版本更新，新报告记录请求与响应模型标识。101 项测试通过，实际 Gemini 单次连接测试成功，响应模型为 `gemini-2.5-flash`；没有自动运行正式评测。保留温度与 token 上限，未额外覆盖 Gemini 默认思考配置。Google OpenAI 兼容接入仍是模型适配条件，不能等同作者 Vertex AI SDK 的完整环境；不同模型结果须单独报告，作者工具及 BuildingQA 指标未改。

英文反馈与评测页面更新：修复英文异常分支漏译，避免对 RDF 数据值做文本替换；英文提示明确要求英文动作目的，作者英文模板原件不变。历史中文运行在英文界面以动作摘要展示并标注原语言，原文可展开；不将其冒充翻译后的原轨迹。评测页改为整页滚动。BuildingQA 源码和用户提供的 419 行代码 AST 一致，新报告固定源码哈希并记录评分协议。对最近完成的中文 30 题报告离线核查：24 题合法结果三项 F1 与官方实现差值为 0，6 题执行失败仍计零分；原文件哈希未变。未重跑模型、未修复或改写模型生成查询。证据见 `output/validation/buildingqa_language_layout_checks.json`。

本次回归 92 项通过；新请求另存完整提示快照与 SHA256，逐题报告关联日志。原 500 字预览仍保留，但不再作为重建输入的唯一资料。界面滚动检查：结果区域 `overflow: visible` 且内容高度等于区域高度，文档高度超过视口，无横向溢出；历史中文评测的英文主视图使用明确标注的步骤摘要。

并发调度更新：网页与 CLI 默认并发 3 题，允许 1–8。网页隔离每题 Agent、分解器、客户端、token、提示日志与查询子进程，共享执行图只读；CLI 隔离进程中的图谱单例。结果原题序保存，报告记录并发数，取消通知所有在途题目并停止补充队列。86 项离线回归通过，包含真实 Windows SPARQL 子进程、客户端隔离、Agent 轨迹/token 隔离、乱序完成归位和全并发取消。未调用模型验证加速比；请求时序、限流和硬件资源条件变化需与串行实验区分。

本轮验证：68 项回归全部通过，前端 JavaScript 语法检查通过；服务版本为 `BrickQA-author-only-20261020-v3`。已检查中英文页面无方法切换入口、旧 API 方法参数被拒绝。未调用模型重跑评测，历史报告文件 SHA256 保持不变。

评测交互更新：新增取消接口与按钮；取消保留已完成结果，中断题目单独记录，不计零分或执行错误，明确标记部分汇总。每题及评分原因、查询对照、结果对照、执行轨迹采用可展开面板，轮询保留展开状态。73 项回归通过，并通过离线浏览器点击验证取消的等待/完成状态，不调用模型。按用户明确选择中断的 30 题运行已保留其 6 题检查点，原报告未重写。

评测接收修正：对照固定提交 `brick_agent.py`，upstream 已撤销本地新增的校验硬拦截、拒绝 stop、只允许无警告查询成为 final 的策略，采用原检查函数并只留诊断；结束后选取最后生成查询。去掉默认整题 150 秒计时，单次查询预算对齐 180 秒；fixed 单独保留原严格策略。BuildingQA 评分与用户本次提供代码经逐行规范化及 AST 比对一致，无需重写指标。该改动改变 Agent 轨迹与接收条件，应重新运行正式实验，不能把旧报告改成新分数；离线回放只验证接收和计分行为。

方法对齐更新：网页和 CLI 默认 upstream，从固定提交的未改动源文件调用搜索、实体/属性定位、CSV 观测导入方法；fixed 独立保留原本地修复。固定 `bldg-59#`、原属性解析、CSV 文件行序 tail(N) 与 `xsd:float` 已恢复；空结果和异常写诊断，不回退。模式绑定图谱，切换需重载；语言不改变方法。源文件清单见 `third_party/brickqa_upstream/source_manifest.json`，差异与使用说明见 `QUICKSTART.md`。本体合并、TTL 恢复、通用查询执行/校验、模型适配仍是当前工程条件，不将该方法模式称为完整官方环境。

复现影响：upstream 可返回本地优先策略曾隐藏的类、多类型重复实体，排序及 LIMIT 竞争也不同；固定 URI 可使其他命名空间的短名定位失败；CSV 可能生成与 TTL 测点不相连的 `bldg-59#` 节点，且无序文件的末尾行与按时间排序的末尾行不同。上述差异均按原实现保留；分数、成本与时序答案须在模式内重新测量，不能将两种模式结果合并。

网页上下文更新：100/5000 数量选项已改为当前建筑已有 TTL 文件，读取原文作为提示上下文，执行图不随之改变。与此前按字符串排序截取执行图相比，输入三元组集合、排列及前缀可能变化，因而 token、延迟和答案可能变化；应按文件路径、SHA256 及实际条数区分实验，不能直接沿用旧数量标签下的结果。完整 TTL 也可选，不自动视为论文的 5000 条条件。旧 CLI 数值接口保留。

同日功能更新：已增加网页和 CLI 的中英文切换，英文 controller 和分解提示保留作者模板原件。评分已改用固定版本 BuildingQA 原实现，网页和 CLI 共用三项指标、失败处理与宏平均；结果自动保存并可导出。下文“初始评分差异”保留为修改依据，已由 `tests/test_language_and_metrics.py` 的反例回归覆盖。这些实现完成不代表已跑完正式模型实验；模型、本体和工具条件的差异仍然存在。

**当前项目已完成主体方法移植、数据准备和较完整的本地工作台，处于功能验证和模型试跑阶段；尚未完成论文实验复现。** 比较准确的项目名称是“BrickQA 的 Qwen 适配与复现准备”。现在不能把网页可用、单元测试通过、SPARQL 执行成功，或仓库自带的分数，表述成“已经达到论文精度”。

初始审计只新增说明、证据和项目约束，没有修改算法、提示词、数据或已有实验结果，也没有调用收费模型。机器可读证据见 [audit_evidence.json](D:/桌面/HKUST/Brickqa/BrickQA/output/reproduction_audit/audit_evidence.json) 和 [provenance.json](D:/桌面/HKUST/Brickqa/BrickQA/output/reproduction_audit/provenance.json)，它们记录修改前的观测结果。

## 版本和比较依据

| 对象 | 已核实的版本或定位 | 如何使用 |
|---|---|---|
| 论文 | BrickQA，BuildSys 2026，11 页，DOI `10.1145/3744256.3812570` | 第 3 节定义方法，第 4 节定义实验，PDF 第 5 页表 2 和第 9 页表 4给出主要目标 |
| 作者开源仓库 | [yun-dam/BrickQA](https://github.com/yun-dam/BrickQA)，`49d9e283c2a3958e9be110583be6575cbd40039b` | 本地 HEAD 与本次联网核实的上游 main 一致；用 `git diff HEAD` 区分本地改动 |
| BuildingQA 数据 | [INFERLab/BuildingQA](https://github.com/INFERLab/BuildingQA)，`b792a627419dfb679ad1f26e4d3dc325a758e95b` | 本地下载清单固定了三张图和三份问题文件；六个 SHA256 均匹配 |
| 官方指标源码 | [固定版本的 metrics.py](https://github.com/INFERLab/BuildingQA/blob/b792a627419dfb679ad1f26e4d3dc325a758e95b/metrics.py) | 复现评测必须对齐可执行定义；其 SHA256 已记入审计证据 |
| 本地环境 | Python 3.12.14；rdflib 7.6.0；pandas 3.0.6；openai 3.26.0 | 是本次观测到的环境；`requirements.txt` 仍只是版本下界，不是锁定环境 |

开始审计时，9 个受 Git 跟踪的文件已修改；工作台、评测、数据等大量文件尚未被 Git 跟踪。这些是工作区相对上游的差异，不能据此判断具体由谁、在哪一轮工作中编写。当前没有一个提交能够完整代表这个工作区版本，正式实验前需要固定代码快照。

## 论文究竟要求复现什么

### 方法范围

保留自然语言到 SPARQL 的主流程：复杂问题的结构化分解，五个工具驱动的 Thought Action Observation 循环，以及执行前的内联校验。五个工具为 `search_brick`、`get_brick_entity`、`get_property_examples`、`execute_sparql` 和 `stop`；最多 15 轮。简单问题跳过分解也是论文设计。

标准 BuildingQA 实验保留实体关联和查询意图，但关闭分解中的时间约束和 Operations。时序案例另外启用时间与聚合能力。论文使用 Gemini 2.5 Flash；更换为 Qwen 可以验证方法迁移，但产生的是不同模型条件下的结果。

### 数据和实验范围

| 建筑 | 完整执行图三元组 | Human 问题 | 全部问题 | 独立 query_id |
|---|---:|---:|---:|---:|
| DFLEX | 629 | 6 | 36 | 6 |
| TUC | 1,855 | 5 | 30 | 5 |
| BLDG11 | 62,578 | 31 | 76 | 9 |
| 合计 | 65,062 | 42 | 142 | 20 |

BLDG59 使用 ASHRAE 223，论文明确排除，因此本地只准备这三栋是正确的范围。BLDG11 的 Human 问题数并非 9，而是 31；只按 query_id 去重会丢掉问题。Human 加 LLM_1 至 LLM_5 的全部 142 个问题才对应完整标准实验。

每栋建筑分别运行 NoKG、100T、5000T。**执行图始终是完整建筑图；0、100、5000 控制模型初始获得的实例上下文。NoKG 仍允许工具查询完整图。** 小建筑不足 5000 条时使用其全部可用三元组。论文还使用建筑结构描述；描述是否注入、从什么样本生成，都应固定，不能把“NoKG”理解成没有任何领域知识或没有工具。

主实验为三栋建筑乘三种上下文的 9 个条件，BrickQA 一次共 426 个问题运行；同条件 ReAct 再需 426 个。拆分 Human 和五类改写报告，不能仅用 42 个 Human 或 6 个中文自制题替代。论文第 4.4 节说明原研究为单次运行；多次重复是可选增强，不应冒充原研究已经提供的设计。

建议先固定以下三种配置定义；它们是后续实验协议，当前尚未实现统一的一键配置入口。

| 配置 | 模型与提示 | 数据和实现 | 允许支持的结论 |
|---|---|---|---|
| 作者发布基线 | Gemini 2.5 Flash、作者英文提示 | 作者提交的工具、原始建筑图和已声明执行策略 | 对照作者发布实现，核对论文结果；发布实现与论文描述的差异仍须说明 |
| 仅换模型的移植对照 | Qwen、与上行相同的英文提示 | 与上行尽量相同，只替换客户端和必要接口适配 | 测量模型替换的影响 |
| 当前改造版 | Qwen、中文及附加指导 | 本体合并、工具和校验修正；显式 paper 路径 | 测量改造后的方法表现；后续逐项消融确认原因 |

local/auto 工作台另外作为应用扩展评估。**当前仅把 `LLM_MODEL` 改回 Gemini，无法恢复作者条件**，因为提示词、图、工具和停止策略仍已改变。

## 已经完成和仍未完成的工作

| 工作 | 当前证据 | 判定 |
|---|---|---|
| 上游方法主体 | Agent、分解、五个工具、15 轮循环、执行和反馈代码均在 | 主体已保留，细节已改造 |
| Qwen 接入 | 统一 OpenAI 兼容客户端；历史试跑记录模型为 qwen-plus | 已实现并有历史模型调用证据 |
| 三栋完整建筑和官方题集 | 清单校验 6/6；已生成 6 份 Human 和 All JSONL | 数据准备完成 |
| 上下文开关 | `set_schema_context(0/100/5000)` 从 source_graph 采样，执行图不随之截断 | 基础能力完成，采样协议仍需对齐 |
| 标准评测模块关闭 | CLI 和网页评测显式关闭 temporal 与 aggregation，Agent 也清除对应分解标记 | 已实现；实际实验需保存设置 |
| 工作台 | 图谱切换、实体和关系探索、查询、导出、取消、网页评测 | 工程功能已实现 |
| 回归测试 | 本次 `.venv/Scripts/python.exe -m pytest -q` 为 26 passed，2 条弃用警告 | 工程回归通过；模型调用使用 mock 的测试不能证明真实精度 |
| 真实模型 pilot | TUC 一题，gold 18 行、预测 0 行，Row F1 为 0，9 动作、84,033 tokens、96.73 秒 | 有试跑，但该题没有答对；不能估计全题集精度 |
| 中文自制题演示 | `evaluate_demo.json` 三题中两题 F1 为 0；第三题 gold/pred 都为空，被计 1 | 不能证明三题中有一道业务问题已正确回答；缺图导致的空答案需单列 |
| 数据和本地模板验证 | 旧 `data_checks.json` 记录 9 个 local 查询和 3 个 CSV 数值核对 | 证明特定模板和数据链路；不能替代模型评测 |
| 正式模型全量实验 | 未发现带固定配置和逐题轨迹的本地 426 题正式结果 | 未完成 |
| ReAct 同条件对照 | 已接入固定版本的独立 Writer/Critic 网页、API 与 CLI 入口，离线原函数对照通过 | 运行入口完成；真实同条件全量实验仍未完成 |
| 官方指标一致性 | 初始反例已覆盖；后续改为固定版本官方实现和统一适配层 | 本次已修正；仍需正式实验 |
| 论文成本效率 | 有 token 计数，但缺乏正式逐题输入输出及计费记录 | 未完成；Qwen 价格不能直接验证 Gemini 的成本倍数 |
| LBNL 的 10 个案例 | 有时序加载和单问入口，没有 10 题完整、独立核验的结果表 | 未完成 |

上述 pilot 和历史 JSON 是过去运行的留存证据，不是本次对当前代码重跑的模型结果。当前模型是否可联网、当前全题集表现如何，本次没有据此作结论。

## 本地改动以及对复现的影响

| 相对作者提交的变化 | 代码位置 | 对复现的实际影响 | 处理方式 |
|---|---|---|---|
| Gemini Vertex AI 改为 Qwen OpenAI 兼容接口 | [llm_client.py](D:/桌面/HKUST/Brickqa/BrickQA/llm_client.py:54)，controller 和 decomposer | 同时改变推理能力、动作格式遵从性、分解结果、tokenizer、延迟和价格。模型差异会与方法差异混合 | 保留为 Qwen 变体；严格条件另建 Gemini 配置。`engine="gemini-flash"` 标签不能代表实际模型 |
| 中文 controller 提示词和中文 Thought 要求；补充别名和动态命名空间指导 | [提示词](D:/桌面/HKUST/Brickqa/BrickQA/prompts/brick_controller.prompt)，[controller](D:/桌面/HKUST/Brickqa/BrickQA/brick_agent.py:474) | 改变语言、先验和 token 开销；不能把分数变化只归因于模型。额外类路径指导也可能帮助或干扰查询 | 固定原英文提示词作对照，中文版本单独命名并记录哈希 |
| 中文分解触发规则、额外上下文、分解 token 统计 | [brick_decomposer.py](D:/桌面/HKUST/Brickqa/BrickQA/brick_decomposer.py:76) | 中文适配合理；触发频率、调用次数和成本会改变。统计更完整不等于算法更高效 | 中文题另列；比较成本时统一统计 controller 和 decomposer |
| 自动合并 Brick 1.4.4 本体 | [brick_utils.py](D:/桌面/HKUST/Brickqa/BrickQA/brick_utils.py:102) | 改变执行图、类层级可达性和探索空间。本次温度查询在 DFLEX 为原图 0、合并图 15；并非纯安装修复 | 需要 raw 与 merged 的独立实验条件；正式基线必须声明本体策略及 SHA256 |
| 改写 search 和实体、属性工具，按真实命名空间解析，搜索偏向实例且结果确定排序 | [search_brick](D:/桌面/HKUST/Brickqa/BrickQA/brick_utils.py:415)，[get_brick_entity](D:/桌面/HKUST/Brickqa/BrickQA/brick_utils.py:442) | 修复实体无法定位等问题，但工具每轮给模型的证据也变了；搜索排序和截断会影响多跳推理 | 作为工具修复单独对照，不能断言只会提高 F1 |
| 增加 local 模板和 auto 路由 | [run](D:/桌面/HKUST/Brickqa/BrickQA/brick_agent.py:820)，[query_planner.py](D:/桌面/HKUST/Brickqa/BrickQA/query_planner.py:68) | 命中模板时不走模型推理，速度与正确率来源不同。网页默认 auto，Agent API 默认 paper；正式评测目前走 paper | 正式模型实验显式 `mode="paper"`；单独报告 local/auto 的覆盖率和准确率 |
| 上下文按排序后的 RDF 三元组重新采样和序列化 | [set_schema_context](D:/桌面/HKUST/Brickqa/BrickQA/brick_agent.py:325) | 便于计数和重复，但不是论文所说“TTL 前 N 条”的同一序列；空白节点标识也不能仅靠排序就保证跨解析稳定 | 预生成并保存上下文文件、实际条数及哈希；不能仅凭配置名认为样本相同 |
| 校验改为告警反馈、禁止带警告直接 stop；最终结果必须成功且无警告 | [execute_action](D:/桌面/HKUST/Brickqa/BrickQA/brick_agent.py:725)，[结束条件](D:/桌面/HKUST/Brickqa/BrickQA/brick_agent.py:947) | 可能减少未完成答案，也可能因启发式误报拒绝正确答案、增加迭代或失败。语义正确性仍不能仅由校验通过保证 | 保存警告、停止原因和逐题轨迹，比较成功与拒答的变化 |
| 移除主执行路径的时间约束自动补丁、无条件 LIMIT 1 和时间戳 Z 删除 | [语法处理](D:/桌面/HKUST/Brickqa/BrickQA/brick_agent.py:615) | 更接近论文告警反馈和保持语义的目标；但与发布源码的具体行为有差异，可能改变时序成败 | 明确属于实现修正；`apply_temporal_constraint` 仍有定义，不代表现在会执行 |
| 修复 CSV 测点 URI 对齐、真实日期提取、截止日期处理与无效数据反馈 | [add_timeseries_data](D:/桌面/HKUST/Brickqa/BrickQA/brick_utils.py:152)，[日期元数据](D:/桌面/HKUST/Brickqa/BrickQA/brick_agent.py:315) | 有助于避免图里有传感器却没有可连通观测；相对时间现在基于已加载数据最新时间。截断仍会改变计算范围 | 时序实验固定日期、完整覆盖、参考时刻和传感器映射 |
| 子进程 SPARQL 执行、30 秒预算、只读限制和超时回收 | [query_graph](D:/桌面/HKUST/Brickqa/BrickQA/brick_utils.py:350)，[sparql_worker.py](D:/桌面/HKUST/Brickqa/BrickQA/sparql_worker.py) | 改善阻塞问题；进程启动、序列化和超时策略会改变延迟及可完成题数。SELECT/ASK 范围也应登记 | 同实验组使用相同预算，区分 gold 超时、模型超时和错误答案 |
| 冷却等待默认归零、请求超时和重试策略变化 | [客户端参数](D:/桌面/HKUST/Brickqa/BrickQA/llm_client.py:80)，[controller](D:/桌面/HKUST/Brickqa/BrickQA/brick_agent.py:363) | 比作者源码每轮 6 秒前等待加 60 秒后等待更快，主要是运行策略变化，不能证明方法计算效率更高 | 同时报墙钟时间、冷却时间、API 时间与查询时间 |
| 新增 UI、服务、评测和样本恢复器 | [app.py](D:/桌面/HKUST/Brickqa/BrickQA/app.py:190)，[building_data.py](D:/桌面/HKUST/Brickqa/BrickQA/building_data.py) | UI 本身可保留；入口自动加载描述、上下文及模块默认值不一致会使同名条件实际不同。恢复损坏样本会减少图内容 | 正式实验统一入口和配置；演示样本恢复结果不能充当完整执行图 |

这些影响中，只有特定查询语义变化、指标反例和当前测试结果已被本次执行验证；其余对全量 F1 的正负影响是待实验验证的推断。不能笼统说“做了工程修复，所以复现分数只会更好”。

## 必须先解决的评测问题

### 初始评分差异已修复

修改前的 `evaluation_metrics.py` 已实现整张结果表的全局列匹配，但仍有以下可复现差异。初始反例同时调用当时的本地函数与固定版本官方函数，不依赖模型。当前实现直接适配官方函数，已修复表中差异；“当前实现”列保留表示初始审计时的实现。

| 输入情形 | 当前实现 | 官方实现 | 影响 |
|---|---|---|---|
| Gold 单列两行 A、B；预测单列只有 A | `exact_match=0` | `exact_match_f1=0.6667` | 本地二值 EM 不能拿来对比论文列名相近的 F1 |
| Gold 有两行相同 A；预测只有一行 A | Row F1 为 1 | Row F1 为 0.6667 | 本地 set 去重丢失行的重复次数，会改变非 DISTINCT 查询得分 |
| Gold 为一行两列 A、B；预测只有一列 A | Entity F1 为 0.6667 | Entity F1 为 0 | 缺列时本地按平铺值比较，结构约束不同 |
| Gold 单列 A；预测两列 A、B | Row F1 为 0 | Row F1 为 1；Exact Match F1 为 0 | 官方允许对额外列取映射子集，本地行为不同 |
| 两列的 precision 和 recall 分布不一致 | 示例 Entity F1 为 0.6667 | 为 0.75 | 逐列 F1 平均与先平均 precision/recall 再计算 F1 不等价 |

还有官方行匹配的规范化处理、本地超过 7 列不做排列搜索、分别最大化 Entity 与 Row 分数等差异。官方实现本身也存在特殊约定，例如列级与行级规范化并不完全相同；严格复现应保留其行为，合理改进另起指标名。

论文文字把 Exact Match F1 描述得接近完全执行正确率，而官方函数实际计算固定列位置下的行 F1，存在部分得分。这是来源之间需要显式记录的口径差异。建议同时输出 `exact_match_f1_official` 与 `execution_accuracy_binary`，不要把两者混用。

### 失败题分母和宏平均必须一致

初始 CLI 只对非空分数求均值，异常题被排除，会抬高结果；网页按全部已评测题数求均值，两个入口曾不一致。当前已统一为 `summarize_results`：模型失败按零分计入，gold 不能执行则标记 `gold_error` 并阻止可比汇总。gold 问题属于评测输入或执行器问题，不能直接当作模型失败，也不能悄悄删题。

本次将作者 CSV 的缺失分数按 0 计入全部题数，再先求每栋建筑均值、最后对三栋做宏平均，重算出：

| 条件 | Entity Set F1 | Row Matching F1 | Exact Match F1 |
|---|---:|---:|---:|
| NoKG | 0.570 | 0.460 | 0.239 |
| 100T | 0.634 | 0.589 | 0.390 |
| 5000T | 0.743 | 0.690 | 0.437 |

这与论文表 2 的 BrickQA Total 一致，**属于原始结果重算，不能算本地模型复现**。`evaluation/` 三份 CSV 与作者提交的内容一致，只有工作区换行符与 Git blob 的字节差异。其每份 284 行分别对应 BrickQA 142 行和 ReAct 142 行。

直接用 pandas 默认 `mean()` 会跳过缺失值。例如 100T 的 DFLEX Row F1 会被算成 0.5484，而按全部 36 题应为 0.4722。论文成本图的 Row F1 约 0.435、0.510、0.597，则与按全部 142 题求均值相符；它与主表按建筑宏平均的 0.460、0.589、0.690 是不同汇总口径。

作者 5000T CSV 内的 142 条 ReAct 均为 `no_results` 且分数全零，与论文表 2 的非零基线不符。因此这份公开 CSV 不能独立重建完整 ReAct 主表；应核对 BuildingQA 的原始基线记录或自行重跑，并注明来源。不能把这个上游产物缺口归咎于本地改动。

`relation_mismatch` 也只是诊断启发式：正则同时抓取关系名和类名，且仅检查两集合有无交集；共享 `rdf:type` 等项就可能掩盖错误。它不等同于论文的 Relationship Error 分类，`false` 不意味着多跳路径正确。

## 数据和时序验证的具体结论

### 完整图和提示样本需要分开

当前本体文件含 50,087 条三元组。合并后 DFLEX、TUC、BLDG11 分别变成 50,716、51,942、95,601 条；BLDG11 原图已与本体部分重叠，因此不能简单把两者条数相加当成实际执行图大小。这里是本体并图与显式属性路径，不等于启用了完整 OWL 推理。

本次执行了 20 个不同 gold SPARQL 的 raw/merged 对照。8 秒执行预算下，两边均为 19 个成功；成功查询的行数相同，这不证明所有绑定内容都完全一致。`MORTAR_009` 两边超时，随后提高到当前默认的 30 秒，两边仍超时，见 [超时复核](D:/桌面/HKUST/Brickqa/BrickQA/output/reproduction_audit/gold_timeout_followup.json)。该 gold 的执行条件需要在正式实验前处理。旧 `data_checks.json` 在 5 秒预算下记录的 8 次错误也都是超时，不是已经证实的 SPARQL 语法错误。

附带 `bldg11_sample_5000.ttl` 尾部有不完整 Turtle 语句，当前恢复器排除末尾 932 个字符后只得到 4,907 条三元组。问题来自作者附带样本，本地新增的是恢复处理。其他 5000 样本实际是 DFLEX 629、TUC 1,855；三个 100 样本均为 100。不能把文件名中的 5000 当成实测条数，更不能将此样本传给 `--ttl` 后声称在完整 BLDG11 上评测。

### 时序链路存在不等于十题成功

附带小时 CSV 有 8,760 行、29 个数据点加 Datetime 列，覆盖 2018 年全年，与作者版本内容一致。`BrickAgent.initialize_graph` 的默认加载量是末尾 100 行，从 12 月 27 日 20:00 开始；网页和 `main_temporal.py` 默认末尾 2,000 行，从 10 月 9 日 16:00 开始。因此默认加载会排除论文案例中的 8 月和 9 月日期。显式 `--start-date/--end-date` 后仍要确保 `max_rows` 足够覆盖筛选后的范围。

已有 `buildingqa_results/lbnl_temporal/result_20260912_165311_lbnl_temporal.json` 标记 `status=success`，问题是“过去 24 小时的最大室外温度”，但最终 SPARQL 只返回室外温度传感器 URI，没有时间窗口和最大值。这是明确的“执行成功、语义未完成”历史例子。不能用它支持论文时序案例成功率。

论文表 4 需要逐题核验以下能力：

| 题号 | 核验任务 | 必须独立确认 |
|---|---|---|
| 1 | 过去 24 小时室温高于送风温度的时段 | 双传感器时间对齐和窗口 |
| 2 | 9 月 20 日冷却水流为零时的室外湿度 | 日期和条件筛选 |
| 3 | 昨天风机关闭时的制热阀位置 | “关闭”的操作语义；论文此题失败 |
| 4 | 9 月 18 日混风阀超过 80% 时的回风温度 | 比例量纲、测点及条件 |
| 5 | 9 月 1 日 9 点至 17 点室温与冷却设定值 | 两个测点和日内边界 |
| 6 | 8 月 25 日送风温度与室温的平均差 | 对齐后作差再平均 |
| 7 | 过去 24 小时最高室外温度 | 必须返回数值极值 |
| 8 | 8 月 25 日制热阀与制冷阀同时开启时段 | 开启阈值及时间交集 |
| 9 | 9 月 10 日室温超过冷却设定值的次数 | 明确按小时样本计数还是事件次数 |
| 10 | 过去两天室温高于冷却设定值的时长 | 时间间隔、缺测和边界 |

论文报道 9/10 成功；本地应该逐题给出实际通过数，不能以“复现 90%”为理由强行让第三题失败。相对时间参考点、选取的工况、小时重采样方式、开阀阈值和成功判定若公开产物没有充分说明，应记录为假设。固定这些定义后，用 pandas 独立计算 gold；不让 Agent 生成结果同时充当自己的裁判。

## 原有项目说明需要怎样解读

[ARCHITECTURE.md](D:/桌面/HKUST/Brickqa/BrickQA/ARCHITECTURE.md) 反映较早代码，不能直接当作当前状态：年份已经从真实观测提取，SPARQL 已有子进程隔离，默认冷却为 0，主路径不再调用时间自动补丁，也不再无条件追加 `LIMIT 1` 或删除 `Z`。其“代码比论文更进一步”的判断也不足以支持精度提升。

`README.md` 仍是上游 Gemini 安装说明，`QUICKSTART.md` 混用了旧 WorkBuddy Python 路径和当前 `.venv` 路径。它们需要统一。`main_temporal.py` 原样保留，但运行的是已改造的 Agent，所以“入口文件没有改”不意味着时序行为没有改。

有几项容易误判为本地偏离，其实作者代码已有：内部 `error` 动作、未被 controller 调用的 `_build_controller_prompt`、分解失败转 `_mock_decompose`、重复动作提前停止等。论文同时有“语法修正”和“告警不自动改”的描述，发布代码还包含自动时序处理；应分别注明论文描述、发布实现和本地修正，不能假定三者完全一致。

## 后续工作顺序和验收标准

### P0 固定复现定义和评分口径

- [ ] 固定当前改造代码快照，并保存相对作者提交的补丁；保留完整上游基线。
- [x] 把固定版本官方指标作为复现评分实现或参考适配层，保留重复行、列映射和规范化语义；本地二值 EM 另名输出。
- [x] 统一 CLI 与网页的失败处理、全题分母和建筑宏平均；gold 错误独立标记，禁止静默删题。
- [ ] 给正式实验配置显式命名：模型、提示词语言、描述、工具版本、本体、上下文、模块开关、查询预算和相对时间基准。
- [ ] 解决全部 gold 的执行预算与可执行性；对 raw/merged 保存绑定差异，冻结正式使用的 gold 结果。
- [ ] 固定 0/100/5000 上下文内容及哈希；说明与原附带样本的差异，不重写作者文件。

验收：官方 scorer 与适配层在已列反例上逐项一致；单独验证列交换、重复行、空结果、缺列、多列和失败题分母。142 个基准问题保持完整，且每题的执行图和 gold 可追溯。

### P1 完成标准实验

- [ ] 先用每栋少量官方问题验证模型、工具和记录链路，再执行完整矩阵。
- [ ] 严格条件使用原模型、英文提示和已声明的发布实现；Qwen 变体单独运行并命名。
- [ ] 三栋乘三上下文共 9 个条件、426 个 BrickQA 问题运行全部落盘；禁止 local 模板参与。
- [x] 引入固定版本 BuildingQA 的独立 ReAct Writer/Critic 评测入口；离线对照已通过。真实同条件全量实验仍待运行，不能把作者原表当成本地重跑。
- [ ] 输出分建筑、分上下文、分 Human/LLM_1 至 LLM_5 的三种官方 F1、执行失败和停止原因，并复建表 2。

验收：每个汇总数字能定位到逐题记录；任何条件的模型、图、本体和提示词变化都明确标注。完成 Qwen 矩阵后，可称“不同模型条件下的复现评估”；补齐严格条件后，再讨论论文数值复现程度。分数不完全相等时报告差值和原因，不能通过改 gold 或挑题逼近论文。

### P2 完成时序案例和成本分析

- [ ] 表 4 的 10 个原问题分别建用例，固定完整日期覆盖及相对时间参考点。
- [ ] 用独立 pandas 计算答案，逐题比较数值、时间戳、计数、时长和单位。
- [ ] 保存输入、输出、缓存等可得 token 分类和请求计费模型，记录采价日期与币种。
- [ ] 区分方法执行时间、冷却、API 与查询时间；按论文成本图的题目均值汇总，同时保留主表的建筑宏平均。

验收：明确报告本地时序成功数和失败原因；成本结论只适用于所运行模型和价格口径。不能用 Qwen 的费用直接声称重现论文 Gemini 的 3 至 12.7 倍结论。

### P3 单独评估扩展改动

在基准稳定后依次测量 Qwen 替换、中文提示、本体合并、工具修复、校验和停止策略。每次只变一个因素，记录其 Row F1、失败率、调用量、token 与耗时。local/auto 工作台单独测覆盖率和端到端正确率。

当前不把 UI 美化、新模型堆叠、GraphRAG、微调、多 Agent 编排或新数据集列为复现必需项。它们会扩张研究问题，应在核心实验完成后另立范围。

## 实验记录最低要求

每次运行保存 `run_id`、代码提交和补丁哈希、数据和本体哈希、模型请求名与响应中的实际模型、API 提供方、采样参数、提示词与描述哈希、实际上下文条数及文件、模块开关、查询和整题预算、冷却、依赖版本、时间基准及数据窗口。不得记录 API Key。

每题保存稳定题目编号、building、query_id、question_source、题目原文、gold/pred SPARQL、列序、完整结果绑定、执行状态、告警、停止原因、动作轨迹、分解是否降级、各阶段 token 和耗时，以及官方三种 F1。只截取 prompt 前 500 字符、用 `self.engine` 记模型的现有日志不足以恢复实际调用，应补充完整提示词文件及哈希。网页 `eval_tasks` 目前只保存在进程内存，正式实验结果需自动持久化。

本项目后续约束见 [AGENTS.md](D:/桌面/HKUST/Brickqa/BrickQA/AGENTS.md)。接下来最有价值的工作是完成 P0，再跑最小官方题集确认口径，最后开展全量实验。
