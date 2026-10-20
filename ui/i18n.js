'use strict';
// UI strings only. User questions, RDF values and SPARQL are never translated.
window.BrickI18n = (() => {
  let language;
  try { language = localStorage.getItem('brickqa-language'); } catch (_) {}
  if (!['zh', 'en'].includes(language)) language = 'zh';
  const english = {
    '选择模型':'Choose model','模型 · ':'Model · ','模型':'Model','关闭模型设置':'Close model settings',
    '切换后用于后续查询与评测；运行中的任务不能切换模型。':'The selected model is used for subsequent queries and evaluations. Models cannot be switched during a running task.',
    '留空使用已保存密钥':'Leave blank to use the saved key',
    '密钥使用 Windows 当前用户加密保存，不写入代码和评测日志。':'Keys are encrypted for the current Windows user and excluded from source code and evaluation logs.',
    '应用模型':'Apply model','测试当前模型':'Test current model',
    '任务运行中，完成或取消后才能切换模型。':'A task is running. Finish or cancel it before changing models.',
    '先应用模型，再测试连接。':'Apply the model before testing its connection.',
    '密钥已配置':'Key configured','需要配置此模型的密钥':'An API key is required for this model',' · 当前模型':' · Current model',
    '当前模型：':'Current model: ','模型已切换：':'Model switched: ','正在测试连接…':'Testing connection…',
    '连接成功：':'Connection successful: ','连接失败：':'Connection failed: ',
    '原始查询分解':'Original recorded decomposition',
    '建筑数据，一问即知。':'Ask your building data.',
    '评分协议：':'Metric protocol: ',
    '汇总：已评测题目均值；建筑宏平均另存报告。':'Summary: mean over evaluated questions; building macro averages are saved separately.',
    '并发题数':'Concurrent questions','同时评测的题数，1 为串行':'Questions evaluated in parallel; 1 is sequential',
    '并发题数必须为 1 到 8 的整数':'Concurrent questions must be an integer from 1 to 8',
    '并发执行：':'Concurrency: ',' · 运行中：':' · Active: ',
    'BuildingAgent':'Ask your building data.',
    '取消评测':'Cancel evaluation','正在取消…':'Cancelling…','评测已取消':'Evaluation cancelled',
    '评测已中断':'Evaluation interrupted',
    '本轮正在由旧版服务执行，取消功能需服务更新后生效；请勿重复启动评测。':'This evaluation is running on the previous server. Cancellation requires the server update; do not start a duplicate evaluation.',
    '已请求取消评测，当前请求结束后停止；已完成结果会保留。':'Cancellation requested. Evaluation stops after the current request returns; completed results are retained.',
    '评测已停止。以下分数仅汇总已完成题目，不代表完整基准成绩；未完成题目不计零分。':'Evaluation stopped. Scores cover completed questions only, not the full benchmark; unfinished questions are not scored as zero.',
    '本题已取消，未计入评分。':'This question was cancelled and excluded from scoring.',
    '标准与预测结果的 Exact Match F1 为 1。':'Exact Match F1 between gold and predicted results is 1.',
    '标准与预测结果未完全匹配。请展开查询和结果对照；仅凭分数无法确定模型出错的原因。':'Gold and predicted results do not fully match. Expand the queries and results for comparison; scores alone do not establish the cause.',
    '评分说明与失败原因':'Score explanation and failure reason','标准 SPARQL':'Gold SPARQL','生成 SPARQL':'Generated SPARQL',
    '标准结果':'Gold results','预测结果':'Predicted results','未记录':'Not recorded','合法空结果':'Valid empty result',
    '未得到可执行结果':'No executable result',
    '仅展示前 50 行，完整内容请导出评测 JSON。':'Showing the first 50 rows. Export the evaluation JSON for the complete results.',
    '标准与预测结果对照':'Gold and predicted result comparison','停止原因：':'Stop reason: ','动作数：':'Actions: ','用时：':'Elapsed: ',
    '未记录执行轨迹':'No execution trace recorded','执行详情与过程':'Execution details and trace',
    'BrickQA · 建筑数据工作台':'BrickQA · Building Data Workspace',
    '展开建筑设置':'Open building settings','BrickQA 首页':'BrickQA home',
    '建筑数据工作台':'Building Data Workspace','连接中':'Connecting',
    '建筑数据与查询历史':'Building data and query history','你的建筑数据':'Your building data',
    '建筑图谱':'Building graph','自定义数据与时间范围':'Custom data and time range',
    '本机 TTL 路径（可选）':'Local TTL path (optional)','时序 CSV':'Timeseries CSV',
    '无时序数据':'No timeseries data','开始日期':'Start date','结束日期':'End date',
    '最近时序行数':'Recent timeseries rows',
    
    
    
    
    
    
    
    '作者方法只支持 Agent 查询。':'Author methods require Agent queries.',
    '方法与定位诊断':'Method and lookup diagnostics',
    
    '日期筛选后加载最近 N 行。时间问题以已加载数据的最新时间为基准。':'Load the last N rows after date filtering. Relative time uses the latest loaded timestamp.',
    '加载建筑 ':'Load building ','正在读取建筑信息…':'Reading building information…',
    '图谱三元组':'Graph triples','传感器实例':'Sensor instances','查询历史':'Query history',
    '第一次查询从这里开始。':'Your first query will appear here.',
    '基于 Brick Schema':'Powered by Brick Schema','每个结果都有图谱依据':'Results grounded in your graph',
    'BuildingAgent':'Ask your building data.',
    '从设备关系到传感器读数，让数据给出答案。':'Explore equipment relationships and sensor readings with natural language.',
    '工作区':'Workspace','自然语言查询':'Natural language','图谱探索':'Graph explorer','准确度评测':'Evaluation',
    
    '论文 Agent · 动态探索':'Paper Agent · dynamic exploration',
    '模型可见图谱':'Model graph context','NoKG · 动态探索':'NoKG · dynamic exploration',
    '模型上下文 TTL':'Model context TTL',
    'NoKG 或当前建筑已有的 TTL 文件；不改变执行图谱。':'NoKG or an existing TTL for the loaded building; the execution graph stays unchanged.',
    'TTL 文件与旧版上下文数量不能同时选择。':'Choose either context_ttl or a legacy context size.',
    '请选择列表中已有的项目 TTL 文件。':'Select an existing project TTL from the list.',
    '上下文 TTL 必须属于当前已加载的建筑。':'Context TTL must match the loaded building.',
    '上下文 TTL 解析失败。':'Context TTL could not be parsed.',
    'Agent · 动态探索':'Agent · dynamic exploration',
    '模型未配置 · Agent 需要 API Key':'Model not configured · Agent requires an API key',
    '从一个问题开始':'Start with a question',
    '查询设备、追踪关联测点，或探索最近的运行数据。':'Find equipment, trace connected points, or explore recent operational data.',
    '试试当前建筑的示例问题。':'Try an example for the loaded building.',
    '✓ 实际图谱执行':'✓ Executed on the graph','✓ 查询过程可查看':'✓ Inspectable query trace','✓ 结果可导出':'✓ Exportable results',
    '你的建筑问题':'Your building question','例如：楼里有哪些温度传感器？':'e.g. What temperature sensors are in the building?',
    '查询 ':'Ask ','取消':'Cancel','Enter 查询 · Shift + Enter 换行':'Enter to ask · Shift + Enter for a new line',
    '搜索图谱':'Search graph','搜索名称、类型或标签，例如 AHU、Temperature':'Search names, types or labels, e.g. AHU, Temperature',
    '搜索':'Search','搜索结果':'Search results','输入关键词探索实体。':'Enter a keyword to explore entities.',
    '建筑中的类型':'Types in the building','实际关系':'Graph relationships','沿着关系探索':'Explore relationships',
    '选择一个类型、关系或实体，查看实际连接。':'Select a type, relationship or entity to inspect its connections.',
    'SPARQL 查询':'SPARQL query','执行查询':'Execute query','重置为当前前缀':'Reset to graph prefixes',
    '支持 SELECT 与 ASK':'SELECT and ASK supported','SPARQL 编辑器':'SPARQL editor','基准问题':'Benchmark',
    '运行评测':'Run evaluation',
    '作者模式的校验提示仅记录，三项 F1 按标准与预测结果计算。':'Author-mode validation messages are diagnostic only. The three F1 scores compare gold and predicted results.',
    '校验诊断（仅记录）':'Validation diagnostics (recorded only)',
    '历史报告只读显示，分数未按当前策略重新计算。':'This historical report is displayed read-only; its scores have not been recalculated under the current policy.',
    '服务重启前评测未完成；已保存结果保留，未自动重跑。':'The evaluation was unfinished when the service restarted. Saved results are retained; no model run was restarted.',
    '正在启动评测…':'Starting evaluation…',
    '执行标准查询':'Executing gold query',
    '模型处理中':'Model processing',
    '正在处理':'Processing',
    '当前第 ':'Current question ',
    ' 题 · ':' · ',
    '评测记录不存在，服务可能已重启。':'Evaluation record unavailable; the service may have restarted.',
    '基准文件没有问题。':'The benchmark contains no questions.',
    '基准问题格式无效。':'Invalid benchmark question format.',
    '评测使用论文 Agent 和标准 SPARQL，调用当前配置的模型。请先加载基准对应的建筑图谱。':'Evaluation uses the paper Agent, gold SPARQL and the configured model. Load the complete building graph for the benchmark first.',
    '查看实体':'Inspect entity','验证关系':'Check relationship','完成':'Done','修正查询':'Revise query',
    '输入参数无效，请检查数据和范围':'Invalid input. Check the data and range.',
    '加载中':'Loading','评测中':'Evaluating','查询中':'Querying','已连接':'Connected','就绪':'Ready',
    '样本 · ':'Sample · ','完整 · ':'Complete · ','尚未加载':'No building loaded',
    '模型已配置 · ':'Model configured · ',
    '已加载 ':'Loaded ',' 行 · ':' rows · ',' 至 ':' to ',
    '已加载。时间类问题需选择对应 CSV。':'Loaded. Select the matching CSV for timeseries questions.',
    '请选择建筑后加载':'Select a building to load','连接中断':'Disconnected','无法连接服务：':'Cannot connect to the server: ',
    '完整建筑':'Complete buildings','论文上下文样本':'Paper context samples',
    '正在加载图谱与时序数据…':'Loading graph and timeseries data…','建筑已加载':'Building loaded',
    '加载失败：':'Loading failed: ','查询失败':'Query failed','已取消':'Cancelled',
    '正在准备查询…':'Preparing query…','提交失败：':'Submission failed: ',
    '连接暂时中断，正在恢复查询进度…':'Connection interrupted. Restoring query progress…',
    '当前已加载的数据中没有匹配记录。可查看查询语句或调整筛选范围。':'No matching records in the loaded data. Inspect the query or adjust the filters.',
    ' / 共 ':' / total ',' 条':' records','上一页':'Previous','下一页':'Next',
    '正在查询':'Querying',' 个动作':' actions','查询已取消':'Query cancelled','未能完成查询':'Query could not be completed',
    '重新填入问题':'Edit this question','本次查询结果':'Query results','论文 Agent':'Paper Agent',
    '统计结果：':'Count: ','找到 ':'Found ',' 条结果':' results','数据来源：':'Source: ','当前建筑':'Loaded building',
    ' · 用时 ':' · time ','复制 SPARQL':'Copy SPARQL','已复制查询':'Query copied',
    '无法自动复制，请展开查询语句手动复制':'Copy failed. Open the query and copy it manually.',
    '在编辑器中打开':'Open in editor','导出全部 CSV':'Export all CSV','查看执行的 SPARQL':'View executed SPARQL',
    '查询分解：':'Query decomposition: ','动作与执行反馈':'Action and observation','等待执行':'Waiting for execution',
    '查看查询过程 · ':'Query trace · ','没有生成可用答案，请调整问题后重试。':'No usable answer was generated. Revise the question and try again.',
    '图谱探索：':'Graph explorer: ','没有匹配的建筑实体。':'No matching building entities.',
    '读取实体关系…':'Loading entity relationships…','关联到此实体':'Incoming relationships',
    '前 ':'First ',' 个实例':' instances',' 条关系':' relationships',
    '执行中…':'Executing…','ASK 已执行':'ASK executed','共 ':'Total ',' 行 · 显示前 ':' rows · showing first ',
    ' 行':' rows','ASK 结果：':'ASK result: ','执行失败':'Execution failed',
    '评测中 ':'Evaluating ','评测完成':'Evaluation complete','评测失败':'Evaluation failed',
    '已评测':'Evaluated','执行异常':'Execution errors','异常':'Error','完全匹配':'Perfect match','未完全匹配':'Partial or no match',
    ' · 标准 ':' · gold ',' 行 / 预测 ':' rows / predicted ','对照标准与生成查询':'Gold and generated queries',
    '标准：\n':'Gold:\n','\n\n生成：\n':'\n\nGenerated:\n',
    '正在恢复评测连接…':'Restoring evaluation connection…',
    '已请求取消，当前请求结束后恢复查询':'Cancellation requested. Queries resume after the current request ends.',
    '初始化失败：':'Initialization failed: ',
    '准备查询':'Preparing query','分解查询':'Decomposing query','模型正在选择下一步':'Model selecting the next action',
    '执行 ':'Executing ',
    '导出评测 JSON':'Export evaluation JSON','标准查询异常，当前汇总不可比较。':'Gold query errors: this summary is not comparable.',
    '模型失败按零分计入；标准查询异常会阻止可比汇总。':'Model failures count as zero; gold query errors block comparable summary scores.',
    '界面与提示语言':'Interface and prompt language','无可比分数':'No comparable scores',
    '请输入问题':'Enter a question','请先加载建筑':'Load a building first',
    '另一项任务进行中，请稍候':'Another task is running. Please wait.',
    '另一项任务进行中':'Another task is running',
    '查询或评测进行中，请完成后再切换建筑':'A query or evaluation is running. Wait before changing buildings.',
    '记录不存在（服务重启后历史会清空）':'Record not found. In-memory history is cleared on restart.',
    '记录不存在':'Record not found','查询完成后才能导出':'Export is available after the query completes',
    '查询结果不存在':'Query results not found','分页参数无效':'Invalid pagination parameters',
    '图谱未加载':'No graph loaded','空搜索词':'Enter a search term','需提供 id 或 uri':'Provide an id or URI',
    '空查询':'Enter a query','查询、加载或评测进行中，请稍候。':'A query, load or evaluation is running. Please wait.',
    'Agent 未初始化':'Agent not initialized','未知评测任务':'Evaluation task not found',
  };
  const t = source => {
    if (source == null || language !== 'en') return source;
    if (Object.hasOwn(english, source)) return english[source];
    if (source.startsWith('执行 ')) return 'Executing ' + source.slice(3);
    const truncation = source.match(/^时序仅加载最近 (\d+) \/ (\d+) 行，请按需要调整日期或行数。$/);
    if (truncation) return `Only the latest ${truncation[1]} / ${truncation[2]} timeseries rows are loaded. Adjust the date range or row limit.`;
    if (source === '当前 TTL 是采样图谱，结果仅覆盖已加载数据；完整建筑查询请加载完整 TTL。') return 'This is a sampled graph. Load the complete TTL to query the whole building.';
    const prefixes = {'基准文件不存在: ':'Benchmark file not found: ',
      '基准与当前建筑不匹配，请先加载对应完整图谱：':'Benchmark does not match the loaded building. Load its complete graph first: ',
      'TTL 文件不存在或格式不正确：':'TTL file missing or invalid: ',
      '以下 CSV 列未关联到测点：':'CSV columns not matched to points: '};
    for (const [original, translated] of Object.entries(prefixes)) {
      if (source.startsWith(original)) return translated + source.slice(original.length);
    }
    return source;
  };
  const staticText = [], staticAttributes = [];
  function initialize() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!['SCRIPT','STYLE'].includes(node.parentElement.tagName) && /[\u4e00-\u9fff]/.test(node.textContent)) {
        staticText.push([node, node.textContent]);
      }
    }
    document.querySelectorAll('[aria-label],[placeholder],[title]').forEach(node => {
      for (const attr of ['aria-label','placeholder','title']) {
        const value = node.getAttribute(attr);
        if (value) staticAttributes.push([node, attr, value]);
      }
    });
    applyStatic();
  }
  function applyStatic() {
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    document.title = t('BrickQA · 建筑数据工作台');
    staticText.forEach(([node, source]) => { node.textContent = t(source); });
    staticAttributes.forEach(([node, attr, source]) => node.setAttribute(attr, t(source)));
    document.getElementById('languageSelect').value = language;
  }
  function setLanguage(value) {
    if (!['zh','en'].includes(value)) throw new Error('Unsupported language');
    language = value;
    try { localStorage.setItem('brickqa-language', value); } catch (_) {}
    applyStatic();
  }
  return {t, initialize, setLanguage, get language() { return language; }};
})();
BrickI18n.initialize();
