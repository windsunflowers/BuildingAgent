'use strict';
const t = source => BrickI18n.t(source);
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n; };
const btn = (text, action, cls='button secondary') => { const n=el('button',cls,text);n.type='button';n.onclick=action;return n; };
const S={status:null,active:null,running:null,pending:false,evaluating:false,cache:new Map(),poll:null,signature:'',evaluation:null,evalPoll:null,evalTimer:null,buildings:[],contextBuilding:null};
let modelCatalog=null,modelPending=false;
const actionNames={react_writer:'ReAct Writer',react_critic:'ReAct Critic',search_brick:'搜索图谱',get_brick_entity:'查看实体',get_property_examples:'验证关系',execute_sparql:'执行查询',stop:'完成',error:'修正查询'};
function recordedFeedback(value){
  if(!value)return value||'';
  if(BrickI18n.language!=='en')return String(value).split('\n').map(line=>{
    const exact={'No results found.':'未找到结果。','No examples found':'未找到示例',
      'Stopping execution':'正在结束执行','Query cancelled':'查询已取消',
      'Agent stopped after repeated output parsing errors':'Agent 因反复解析错误已停止',
      'ERROR: Reply with exactly one Thought: and one Action: label. Use Action: execute_sparql(query) or stop(). Do not include Observation:.':'格式错误：请只输出一个 Thought: 和一个 Action:，使用 execute_sparql(query) 或 stop()，不要输出 Observation:。',
      'Write every PREFIX URI inside angle brackets.':'所有 PREFIX URI 都必须放在尖括号内。',
      'Required prefixes: brick:, bldg:, ref:, xsd:':'所需前缀：brick:、bldg:、ref:、xsd:'};
    if(Object.hasOwn(exact,line))return exact[line];
    const prefixes={'No results. Status: ':'查询未返回任何结果。状态：', 'Execution error: ':'执行错误：',
      'Error executing action: ':'执行动作时出错：', 'SPARQL execution error: ':'SPARQL 执行错误：',
      'PREFIX error: ':'PREFIX 错误：', 'Unknown action: ':'未知动作：',
      'Types:':'类型:','Properties:':'属性:'};
    for(const [source,target]of Object.entries(prefixes))if(line.startsWith(source))return target+line.slice(source.length);
    return line.replace(/^Query exceeded (\d+(?:\.\d+)?) seconds$/, '查询超过 $1 秒');
  }).join('\n');
  return String(value).split('\n').map(line=>{
    const pairs=[['查询未返回任何结果。状态：','No results. Status: '],['执行错误：','Execution error: '],['执行动作时出错：','Error executing action: '],['SPARQL 执行错误：','SPARQL execution error: '],['PREFIX 错误：','PREFIX error: '],['类型:','Types:'],['属性:','Properties:']];
    for(const [source,target] of pairs)if(line.startsWith(source))return target+line.slice(source.length);
    if(line==='未找到结果。')return 'No results found.';
    if(line==='未找到示例')return 'No examples found';
    if(line==='正在结束执行')return 'Stopping execution';
    if(line==='查询已取消')return 'Query cancelled';
    if(line==='Agent 因反复解析错误已停止')return 'Agent stopped after repeated output parsing errors';
    return line.replace(/查询超过 (\d+(?:\.\d+)?) 秒/g,'Query exceeded $1 seconds').replace(/^RuntimeError: 查询已取消$/,'RuntimeError: Query cancelled');
  }).join('\n');
}
function recordedMessage(value){
  const content=el('div'),display=recordedFeedback(value);
  if(BrickI18n.language==='en'&&/[\u4e00-\u9fff]/.test(display)){
    content.append(el('p','muted','The original recorded message is in Chinese. Open the source text for exact details.'),detail('Original recorded message (Chinese)',el('pre','code',value)));
  }else content.append(el('p','muted',display));
  return content;
}
function traceStep(action,index){
  const n=el('div','trace-step'),en=BrickI18n.language==='en';
  n.append(el('strong','',(index+1)+'. '+(t(actionNames[action.action_name])||action.action_name)));
  const purpose=action.thought||'',summarized=en?/[\u4e00-\u9fff]/.test(purpose):/[A-Za-z]/.test(purpose);
  const purposes=en?{react_writer:'Generate or revise the query.',react_critic:'Review the query and execution summary.',search_brick:'Search the graph for candidate entities.',get_brick_entity:'Inspect the entity and its properties.',get_property_examples:'Inspect examples of the requested relationship.',execute_sparql:'Execute the generated SPARQL query.',stop:'Stop and select the last generated query.',error:'Review the previous execution feedback.'}:{react_writer:'生成或修改查询。',react_critic:'评审查询与执行摘要。',search_brick:'搜索图谱中的候选实体。',get_brick_entity:'查看实体及其属性。',get_property_examples:'查看指定关系的示例。',execute_sparql:'执行模型生成的 SPARQL 查询。',stop:'停止并选择最后生成的查询。',error:'查看上一动作的执行反馈。'};
  n.append(el('p','trace-purpose',summarized?(en?'Step summary: ':'步骤摘要：')+(purposes[action.action_name]||(en?'Perform the recorded action.':'执行记录中的动作。')):purpose));
  const original=action.observation||'',observation=recordedFeedback(original);
  const controlled=['execute_sparql','stop','error'].includes(action.action_name)&&(/(?:状态：|执行错误：|出错：|PREFIX 错误：|已取消|反复解析错误)/.test(original)||action.execution_error);
  let shown=observation,sourceNeeded=summarized||observation!==original;
  if(en&&controlled&&/[\u4e00-\u9fff]/.test(observation)){
    shown='Execution feedback was recorded in Chinese. See the original trace for exact details.';
    if(action.execution_status)shown+=' Status: '+action.execution_status;
    sourceNeeded=true;
  }
  n.append(el('pre','code trace-feedback',(action.action_argument||'')+'\n\n'+shown));
  if(sourceNeeded)n.append(detail(en?'Original recorded trace (Chinese; preserved)':'原始执行记录（保留英文原文；摘要仅用于显示）',el('pre','code',purpose+'\n\n'+original)));
  return n;
}
let toastTimer;
function toast(text,error=false){$('toast').textContent=text;$('toast').className='toast'+(error?' error':'');$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('toast').hidden=true;},6000);}
async function api(path,body){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),45000);try{const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});const d=await r.json();if(!r.ok){const error=new Error(typeof d.detail==='string'?t(d.detail):t('输入参数无效，请检查数据和范围'));error.status=r.status;throw error;}return d;}finally{clearTimeout(timer);}}
function busy(){return S.pending||!!S.running||S.evaluating||S.status?.loading;}
function evaluationMethodControls(b){const react=$('evalMethod').value==='react';$('reactBackendField').hidden=!react;$('reactBackend').disabled=b||!react;$('brickqaEvaluationNote').hidden=react;$('reactEvaluationNote').hidden=!react;}
function controls(){modelControls();const b=busy();for(const id of ['askBtn','loadBtn','evalRun','schemaContext','evalContext','evalMethod','reactBackend','benchSelect','evalWorkers'])$(id).disabled=b;evaluationMethodControls(b);$('evalRun').disabled=b||!S.status?.graph?.ttl||!$('benchSelect').value;$('benchSelect').disabled=b||!$('benchSelect').value;$('cancelBtn').hidden=!S.running;document.querySelectorAll('.example').forEach(n=>n.disabled=b);$('connection').className='connection '+(b?'busy':'ready');$('connectionText').textContent=S.status?.loading?t('加载中'):S.evaluating?t('评测中'):b?t('查询中'):t('已连接');if(!b)$('runStatus').textContent=t('就绪');$('evalCancel').disabled=!!S.evaluation?.cancel_requested||!S.status?.evaluation_cancellation;}
function drawer(open){$('sidebar').inert=matchMedia('(max-width:760px)').matches&&!open;$('sidebar').classList.toggle('open',open);$('drawerBackdrop').classList.toggle('show',open);$('sidebarToggle').setAttribute('aria-expanded',String(open));}
async function refreshStatus(initial=false){try{const d=await api('/api/status');S.status=d;$('modelChooser').textContent=t('模型 · ')+d.model;$('modelChooser').title=(d.model_provider||'')+' · '+d.model;S.running=d.active_task_id;S.evaluating=d.evaluating;const g=d.graph;if(S.contextBuilding!==g.ttl){S.contextBuilding=g.ttl;loadContextOptions();loadBenchmarks();}$('buildingLabel').textContent=g.building?(g.sample?t('样本 · '):t('完整 · '))+g.building:t('尚未加载');$('tripleCount').textContent=Number(g.triples||0).toLocaleString();$('sensorCount').textContent=Number(g.sensors||0).toLocaleString();$('modelInfo').textContent=d.llm_ready?t('模型已配置 · ')+d.model:t('模型未配置 · Agent 需要 API Key');const notices=[...(g.warnings||[])];if(!g.implementation_mode)notices.push('当前服务仍为旧版；本轮评测完成后请重启，才能启用作者方法及完整进度显示。');$('notice').hidden=!notices.length;$('notice').textContent=notices.map(t).join(' ');$('loadHint').textContent=g.timeseries?.rows?t('已加载 ')+g.timeseries.rows+t(' 行 · ')+g.timeseries.start.slice(0,10)+t(' 至 ')+g.timeseries.end.slice(0,10):g.building?t('已加载。时间类问题需选择对应 CSV。'):t('请选择建筑后加载');if(initial){$('buildingSelect').value=g.ttl||$('buildingSelect').value;$('csvSelect').value=g.csv||'';}controls();const evaluationId=d.active_eval_task_id||(initial?recoveryEvaluationId():null);if(evaluationId&&S.evalPoll!==evaluationId){showTab('evaluate');pollEvaluation(evaluationId);}if(initial&&d.active_task_id){S.active=d.active_task_id;pollTask(d.active_task_id);}}catch(e){$('connection').className='connection error';$('connectionText').textContent=t('连接中断');if(initial)toast(t('无法连接服务：')+e.message,true);}}
async function loadBuildings(){const d=await api('/api/buildings');S.buildings=d.buildings;const full=el('optgroup'),sample=el('optgroup');full.label=t('完整建筑');sample.label=t('论文上下文样本');$('buildingSelect').replaceChildren();for(const b of d.buildings){const o=el('option','',b.id);o.value=b.ttl;o.dataset.description=b.description||'';(b.sample?sample:full).append(o);}$('buildingSelect').append(full,sample);for(const p of d.csvs){const o=el('option','',p.split(/[\\/]/).pop());o.value=p;$('csvSelect').append(o);}}
function loadContextOptions(){
  const buildingId=value=>String(value||'').split(/[\\/]/).pop().replace(/\.ttl$/i,'').replace(/_sample_\d+$/,'');
  const current=buildingId(S.status?.graph?.ttl);
  for(const id of ['schemaContext','evalContext']){
    const select=$(id),previous=select.value,none=el('option','',t('NoKG · 无初始图谱'));none.value='';
    select.replaceChildren(none);
    for(const b of S.buildings.filter(b=>buildingId(b.ttl)===current)){
      const option=el('option','',b.ttl.split(/[\\/]/).slice(-2).join('/'));option.value=b.ttl;select.append(option);
    }
    select.value=[...select.options].some(o=>o.value===previous)?previous:'';
  }
}
async function loadExamples(){try{const language=BrickI18n.language,d=await api('/api/examples?language='+language);if(language!==BrickI18n.language)return;$('examples').replaceChildren();for(const [index,q] of d.questions.entries()){const n=btn(q,()=>ask(d.model_questions[index]),'example');n.append(el('span','','↗'));$('examples').append(n);}controls();}catch(e){toast(e.message,true);}}
async function doLoad(){if(busy())return;S.pending=true;controls();$('loadHint').textContent=t('正在加载图谱与时序数据…');const custom=$('customTtl').value.trim();try{await api('/api/load',{ttl:custom||$('buildingSelect').value,description:custom?null:$('buildingSelect').selectedOptions[0]?.dataset.description||null,csv:$('csvSelect').value||null,start_date:$('startDate').value||null,end_date:$('endDate').value||null,max_rows:Number($('maxRows').value)});S.active=null;S.signature='';$('answer').replaceChildren();$('welcome').hidden=false;$('sparqlEditor').value='';await refreshStatus();await loadExamples();await loadExplore();drawer(false);toast(t('建筑已加载'));}catch(e){toast(t('加载失败：')+e.message,true);}finally{S.pending=false;controls();}}
async function loadHistory(){try{const rows=await api('/api/tasks');$('historyList').replaceChildren();for(const r of rows){const n=btn('',()=>selectHistory(r.task_id),'history-item');n.classList.toggle('active',S.active===r.task_id);n.append(el('span','',r.question),el('small','',(r.building||'')+' · '+({running:t('查询中'),done:t('完成'),error:t('查询失败'),cancelled:t('已取消')}[r.status]||r.status)));$('historyList').append(n);}if(!rows.length)$('historyList').append(el('p','micro',t('第一次查询从这里开始。')));$('historyCount').textContent=rows.length;}catch(e){toast(e.message,true);}}
async function selectHistory(tid){S.active=tid;S.signature='';try{const d=S.cache.get(tid)||await api('/api/task/'+tid);renderAnswer(d);await loadHistory();if(d.status==='running')pollTask(tid);}catch(e){toast(e.message,true);}drawer(false);}
async function ask(question){if(busy())return;const q=question.trim();if(!q){$('questionInput').focus();return;}S.pending=true;controls();try{const d=await api('/api/ask',{question:q,context_ttl:$('schemaContext').value||null,interface_language:BrickI18n.language});S.active=d.task_id;S.running=d.task_id;S.signature='';$('cancelBtn').disabled=false;$('questionInput').value='';$('welcome').hidden=true;$('answer').replaceChildren(el('div','card question-card',q),loading(t('正在准备查询…')));await loadHistory();pollTask(d.task_id);}catch(e){toast(t('提交失败：')+e.message,true);}finally{S.pending=false;controls();}}
function loading(text){const n=el('div','card loading-state');n.append(el('span','spinner'),el('span','',text));return n;}
function pollTask(tid){clearTimeout(S.poll);let failures=0;const poll=async()=>{try{const d=await api('/api/task/'+tid);failures=0;S.cache.set(tid,d);if(S.active===tid)renderAnswer(d);$('runStatus').textContent=(t(d.phase)||t('查询中'))+' · '+(d.elapsed_seconds||0)+'s';if(d.status==='running'){S.running=tid;S.poll=setTimeout(poll,1000);}else{S.running=null;controls();await loadHistory();}}catch(e){failures++;if(failures===3)toast(t('连接暂时中断，正在恢复查询进度…'),true);S.poll=setTimeout(poll,Math.min(failures*1000,8000));}};S.poll=setTimeout(poll,200);}
function card(title,badge){const c=el('div','card'),head=el('div','card-head'),body=el('div','card-body');head.append(el('span','',title));if(badge)head.append(el('span','pill',badge));c.append(head,body);return{c,body};}
function detail(title,child){const n=el('details','details');n.append(el('summary','',title),child);return n;}
function uriButton(value){const n=btn(String(value).split('#').pop().split('/').pop(),()=>{showTab('explore');openEntity(String(value));},'result-link');n.title=String(value);return n;}
function table(rows){if(!rows?.length)return el('p','muted',t('当前已加载的数据中没有匹配记录。可查看查询语句或调整筛选范围。'));const wrap=el('div','table-wrap'),t=el('table'),head=el('thead'),hr=el('tr'),body=el('tbody'),cols=[...new Set(rows.flatMap(r=>Object.keys(r)))];for(const col of cols)hr.append(el('th','',col));head.append(hr);for(const row of rows){const tr=el('tr');for(const col of cols){const td=el('td'),v=row[col];if(typeof v==='string'&&/^(https?:|file:|urn:)/.test(v))td.append(uriButton(v));else td.textContent=v==null?'—':String(v);td.title=v==null?'':String(v);tr.append(td);}body.append(tr);}t.append(head,body);wrap.append(t);return wrap;}
function resultPage(holder,d,rows,offset){holder.replaceChildren(table(rows));const total=d.final_sparql.num_results;if(total>100){const p=el('div','pagination');p.append(el('span','',(offset+1)+'–'+Math.min(offset+rows.length,total)+t(' / 共 ')+total+t(' 条')));const previous=btn(t('上一页'),()=>page(holder,d,Math.max(0,offset-100))),next=btn(t('下一页'),()=>page(holder,d,offset+100));previous.disabled=offset===0;next.disabled=offset+100>=total;p.append(previous,next);holder.append(p);}}
async function page(holder,d,offset){try{const result=await api('/api/task/'+d.task_id+'/results?offset='+offset+'&limit=100');resultPage(holder,d,result.rows,offset);}catch(e){toast(e.message,true);}}
function renderAnswer(d){const sig=JSON.stringify([d.status,d.actions?.length,d.phase,d.final_sparql,d.error]);if(sig===S.signature)return;S.signature=sig;const scroll=$('queryScroll').scrollTop,opened=$('traceDetails')?.open,answer=$('answer');answer.replaceChildren();$('welcome').hidden=true;answer.append(el('div','card question-card',d.question));if(d.status==='running')answer.append(loading((t(d.phase)||t('正在查询'))+' · '+(d.actions?.length||0)+t(' 个动作')));if(d.error){const{c,body}=card(d.status==='cancelled'?t('查询已取消'):t('未能完成查询'));c.classList.add('error-card');body.append(recordedMessage(d.error),btn(t('重新填入问题'),()=>{$('questionInput').value=d.question;$('questionInput').focus();}));answer.append(c);}if(d.final_sparql){const f=d.final_sparql,{c,body}=card(t('本次查询结果'),t('论文 Agent')),intro=el('div','answer-intro');intro.append(el('span','success-icon','✓'),el('strong','',f.results?.length===1 && f.results[0].count!=null?t('统计结果：')+f.results[0].count:t('找到 ')+f.num_results+t(' 条结果')));body.append(intro,el('p','muted',t('数据来源：')+(d.graph?.building||t('当前建筑'))+t(' · 用时 ')+d.elapsed_seconds+'s · '+(d.actions?.length||0)+t(' 个动作')));if(f.diagnostic_warnings?.length)body.append(detail(t('校验诊断（仅记录）'),el('pre','code',f.diagnostic_warnings.join('\n'))));for(const w of d.warnings||[])body.append(recordedMessage(w));const holder=el('div');body.append(holder);resultPage(holder,d,f.results,0);const tools=el('div','answer-tools');tools.append(btn(t('复制 SPARQL'),async()=>{try{await navigator.clipboard.writeText(f.sparql);toast(t('已复制查询'));}catch(e){toast(t('无法自动复制，请展开查询语句手动复制'),true);}}),btn(t('在编辑器中打开'),()=>{$('sparqlEditor').value=f.sparql;showTab('sparql');}));const link=el('a','button secondary',t('导出全部 CSV'));link.href='/api/task/'+d.task_id+'/export';link.download='brickqa-results.csv';tools.append(link);body.append(tools,detail(t('查看执行的 SPARQL'),el('pre','code',f.sparql)));answer.append(c);}const diagnostics=(d.actions||[]).map(a=>a.diagnostics).filter(Boolean);if(diagnostics.length)answer.append(detail(t('方法与定位诊断'),el('pre','code',JSON.stringify(diagnostics,null,2))));if(d.actions?.length||d.decomposition){const container=el('div');if(BrickI18n.language==='en'&&d.language==='zh')container.append(el('p','warn-text','This query used Chinese prompts. English step summaries are display-only; the original trace is preserved.'));if(d.decomposition)container.append(detail(t('原始查询分解'),el('pre','code',JSON.stringify(d.decomposition,null,2))));for(const [index,a] of (d.actions||[]).entries())container.append(traceStep(a,index));const n=detail(t('查看查询过程 · ')+(d.actions?.length||0)+t(' 个动作')+(d.tokens?.total?' · '+d.tokens.total+' tokens':''),container);n.id='traceDetails';n.open=!!opened;answer.append(n);}if(d.status==='done'&&!d.final_sparql)answer.append(el('p','error-message',t('没有生成可用答案，请调整问题后重试。')));$('queryScroll').scrollTop=scroll;}
function showTab(name){document.body.classList.toggle('evaluation-page',name==='evaluate');document.querySelectorAll('.tab').forEach(n=>{const active=n.dataset.tab===name;n.classList.toggle('active',active);n.setAttribute('aria-selected',String(active));});document.querySelectorAll('.tab-panel').forEach(n=>{const active=n.id==='panel-'+name;n.classList.toggle('active',active);n.hidden=!active;});if(name==='explore')loadExplore();if(name==='sparql'&&!$('sparqlEditor').value)loadPrefixes();if(name==='evaluate')loadBenchmarks();}
function item(title,subtitle,count,action){const n=btn('',action,'list-item'),text=el('span');text.append(el('span','',title));if(subtitle)text.append(el('small','',subtitle));n.append(text);if(count!=null)n.append(el('span','count',count));return n;}
async function loadExplore(){try{const[c,r]=await Promise.all([api('/api/classes?limit=100'),api('/api/relations?limit=100')]);$('classesList').replaceChildren(...c.classes.map(x=>item(x.type,'',x.count,()=>openClass(x))));$('relationsList').replaceChildren(...r.relations.map(x=>item(x.pred,'',x.count,()=>openRelation(x))));}catch(e){toast(t('图谱探索：')+e.message,true);}}
async function searchEntities(){const q=$('searchInput').value.trim();if(!q)return;try{const d=await api('/api/search?q='+encodeURIComponent(q)+'&limit=40');$('searchResults').replaceChildren(...d.results.map(x=>item(x.id,x.types.join(', '),null,()=>openEntity(x.uri))));if(!d.results.length)$('searchResults').append(el('p','muted',t('没有匹配的建筑实体。')));}catch(e){toast(e.message,true);}}
async function openEntity(uri){$('entityDetail').replaceChildren(loading(t('读取实体关系…')));try{const d=await api('/api/entity?uri='+encodeURIComponent(uri));if(d.error)throw new Error(d.error);const{c,body}=card(String(d.uri).split('#').pop());body.append(el('p','uri',d.uri),el('p','muted',d.types.join(' · ')));for(const[key,values]of Object.entries(d.properties)){const p=el('div','property');p.append(el('label','',key));for(const v of values)p.append(v.type==='uri'?uriButton(v.uri):el('span','',v.value+' '));body.append(p);}body.append(el('h3','',t('关联到此实体')));for(const x of d.incoming){const p=el('div','property');p.append(el('label','',x.pred),uriButton(x.subject_uri));body.append(p);}$('entityDetail').replaceChildren(c);if(matchMedia('(max-width:760px)').matches)c.scrollIntoView({block:'start'});}catch(e){$('entityDetail').replaceChildren(el('p','error-message',e.message));}}
async function openClass(x){try{const d=await api('/api/class_instances?t='+encodeURIComponent(x.uri)+'&limit=100'),{c,body}=card(x.type,t('前 ')+d.instances.length+t(' 个实例'));d.instances.forEach(i=>body.append(item(i.id,i.label,null,()=>openEntity(i.uri))));$('entityDetail').replaceChildren(c);}catch(e){toast(e.message,true);}}
async function openRelation(x){try{const d=await api('/api/relation_instances?pred='+encodeURIComponent(x.uri)+'&limit=100'),{c,body}=card(x.pred,t('前 ')+d.instances.length+t(' 条关系'));for(const r of d.instances){const p=el('div','property');p.append(uriButton(r.subject_uri),el('span','',' → '),r.object_uri?uriButton(r.object_uri):el('span','',r.object));body.append(p);}$('entityDetail').replaceChildren(c);}catch(e){toast(e.message,true);}}
async function loadPrefixes(){try{const d=await api('/api/prefixes');$('sparqlEditor').value=d.block+'\n\nSELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 25';}catch(e){toast(e.message,true);}}
async function runSparql(){const q=$('sparqlEditor').value.trim();if(!q)return;$('sparqlRun').disabled=true;$('sparqlStatus').textContent=t('执行中…');try{const d=await api('/api/sparql',{query:q});$('sparqlStatus').textContent=d.ask?t('ASK 已执行'):t('共 ')+d.total+t(' 行 · 显示前 ')+d.rows.length+t(' 行');$('sparqlResult').replaceChildren(d.ask?el('div','card card-body',t('ASK 结果：')+d.value):table(d.rows));}catch(e){$('sparqlStatus').textContent=t('执行失败');$('sparqlResult').replaceChildren(el('p','error-message',e.message));}finally{$('sparqlRun').disabled=false;}}
async function loadBenchmarks(){
  const loaded=S.status?.graph?.ttl,selected=$('benchSelect').value;
  $('benchSelect').replaceChildren();controls();
  try{
    const d=await api('/api/benchmarks');
    if(loaded!==S.status?.graph?.ttl||d.ttl!==loaded)return;
    $('benchSelect').replaceChildren(...d.benchmarks.map(b=>{const o=el('option','',b);o.value=b;return o;}));
    if(!d.benchmarks.length){const o=el('option','',t('当前建筑没有对应的基准题集'));o.value='';o.disabled=true;$('benchSelect').append(o);}
    selectRunningBenchmark('benchmarks/'+S.status?.graph?.building+'_all.jsonl');
    if(selected)selectRunningBenchmark(selected);
  }catch(e){toast(e.message,true);}finally{controls();}
}
async function runEvaluation(){if(busy())return;const workers=Number($('evalWorkers').value);if(!Number.isInteger(workers)||workers<1||workers>8){toast(t('并发题数必须为 1 到 8 的整数'),true);return;}S.pending=true;controls();try{const d=await api('/api/evaluate',{benchmark:$('benchSelect').value,context_ttl:$('evalContext').value||null,interface_language:BrickI18n.language,workers,method:$('evalMethod').value,react_backend:$('reactBackend').value});S.evaluating=true;S.evaluation=null;if(d.method==='react')toast(t('已提交评测，服务端确认后端：')+(d.react_backend==='graphdb'?'GraphDB':d.react_backend==='rdflib'?'RDFLib':t('未记录')));$('evalSummary').replaceChildren();$('evalResults').replaceChildren(el('p','muted',t('正在启动评测…')));pollEvaluation(d.task_id);}catch(e){toast(e.message,true);}finally{S.pending=false;controls();}}
function metricValue(value){return value==null?'—':Number(value).toFixed(3);}
async function cancelEvaluation(){
  const tid=S.evalPoll;if(!tid)return;
  $('evalCancel').disabled=true;
  try{const d=await api('/api/eval_task/'+tid+'/cancel',{});if(d.cancel_requested){if(S.evaluation)S.evaluation.cancel_requested=true;$('evalCancel').textContent=t('正在取消…');toast(t('已请求取消评测，当前请求结束后停止；已完成结果会保留。'));}}
  catch(e){$('evalCancel').disabled=false;toast(e.message,true);}
}
function evaluationBackend(configuration){
  const mode=configuration?.baseline_reference?.execution_mode;
  if(mode==='remote_GraphDB')return 'graphdb';
  if(mode==='local_rdflib')return 'rdflib';
  return ['graphdb','rdflib'].includes(configuration?.react_backend)?configuration.react_backend:null;
}
function evaluationReason(row){
  if(row.status==='cancelled')return t('本题已取消，未计入评分。');
  if(row.error)return row.error;
  if(row.execution_error)return row.execution_error;
  if(row.status==='done'&&row.pred_count===0){
    const earlier=(row.actions||[]).find(a=>a.action_name==='execute_sparql'&&a.result_count>0);
    const empty=t('查询语法合法且执行成功，但最终查询没有匹配数据。合法空结果不代表答案正确；标准结果非空时三项 F1 为零。');
    return earlier?empty+' '+t('先前查询曾返回 ')+earlier.result_count+t(' 行，修订后的最终查询返回 0 行；作者规则仍选择最后生成的查询评分。'):empty;
  }
  if(row.exact_match_f1===1)return t('标准与预测结果的 Exact Match F1 为 1。');
  return t('标准与预测结果未完全匹配。请展开查询和结果对照；仅凭分数无法确定模型出错的原因。');
}
function evaluationPhase(current){
  if(current.stage==='gold')return t('执行标准查询');
  // Older live workers expose their completed Agent state while F1 is still running.
  if(current.stage==='scoring'||(current.stage==='model'&&current.phase==='完成'))return t('计算官方 F1（列匹配可能耗时）');
  return current.stage==='model'?(t(current.phase)||t('模型处理中')):t('正在处理');
}
function renderEvaluation(d){
  const summary=d.summary||{},done=summary.done||0;
  const pageScroll=window.scrollY,root=$('evalResults'),scroll=root.scrollTop,opened=new Set([...root.querySelectorAll('details[open][data-eval-key]')].map(n=>n.dataset.evalKey));
  const dropdown=(key,title,content)=>{const n=detail(title,content);n.dataset.evalKey=(d.task_id||'')+':'+key;n.open=opened.has(n.dataset.evalKey);return n;};
  if(d.configuration?.benchmark)selectRunningBenchmark(d.configuration.benchmark);
  if(d.configuration?.workers||d.status==='running')$('evalWorkers').value=d.configuration?.workers||1;
  $('evalProgress').textContent=d.status==='running'?(d.cancel_requested?t('正在取消…'):t('评测中 ')+done+'/'+summary.total):d.status==='cancelled'?t('评测已取消'):d.status==='interrupted'?t('评测已中断'):d.status==='done'?t('评测完成'):d.status==='invalid'?t('无可比分数'):t('评测失败');
  $('evalCancel').hidden=d.status!=='running';$('evalCancel').disabled=!!d.cancel_requested;$('evalCancel').textContent=d.cancel_requested?t('正在取消…'):t('取消评测');
  const metrics=el('div','metrics');
  for(const [label,value] of [[t('已评测'),done+'/'+(summary.total||0)],['Entity-set F1',metricValue(summary.entity_set_f1)],['Row Matching F1',metricValue(summary.row_matching_f1)],['Exact Match F1',metricValue(summary.exact_match_f1)],[t('执行异常'),summary.errors||0]]){
    const node=el('div','metric');node.append(el('strong','',value),el('small','',label));metrics.append(node);
  }
  const facts=el('div','card card-body');
  facts.append(el('strong','',t('以下分数来自已记录的本轮配置，上方控件用于下一次运行。')));
  if(d.configuration?.method==='react'){
    const backend=evaluationBackend(d.configuration);
    facts.append(el('p','evaluation-note',t('本轮实际执行后端：')+(backend==='graphdb'?'GraphDB':backend==='rdflib'?'RDFLib':t('未记录'))));
    if(backend==='graphdb')facts.append(el('p','uri',d.configuration.evaluation_graph?.endpoint||d.configuration.baseline_reference?.endpoint||t('未记录')));
    facts.append(el('p','evaluation-note',t('实际模型：')+(d.configuration.model_configuration?.model||d.configuration.model||t('未记录'))));
    if(backend&&$('reactBackend').value!==backend)facts.append(el('p','warn-text',t('当前所选后端与这份报告不同。切换选项不会重跑或改变已有分数。')));
  }
  $('evalSummary').replaceChildren(facts,metrics);
  $('evalSummary').append(el('p','evaluation-note metric-protocol',t('评分协议：')+(d.metric_protocol||'BuildingQA (legacy report)')+' · '+t('汇总：已评测题目均值；建筑宏平均另存报告。')));
  $('evalSummary').append(el('p','evaluation-note',t('本轮方法：')+((d.configuration?.method||'brickqa')==='react'?'ReAct · BuildingQA':'BrickQA')));
  const localExecution=d.configuration?.method_policy?.rdflib_execution||d.configuration?.baseline_reference?.rdflib_execution;
  if(localExecution?.optimizer==='connected_bgp')$('evalSummary').append(el('p','evaluation-note',t('本轮启用本地 RDFLib 连接顺序优化；查询与数据不变，单次预算仍为 180 秒。此项属于执行器工程适配。')));
  if(d.configuration?.completion_provenance)$('evalSummary').append(el('p','evaluation-note',t('本报告由历史已评测题与本次补跑题合成，逐题来源已记录；并非整套题的新模型重跑。')));
  if(d.configuration?.method==='react'){
    if(d.configuration.evaluation_graph?.scope==='raw_building_ttl')$('evalSummary').append(el('p','evaluation-note',t('按提供文档使用建筑 TTL 源图，不合并本体；标准与预测查询使用同一执行图。')));
    $('evalSummary').append(el('p','evaluation-note',t('实际模型：')+(d.configuration.model_configuration?.model||d.configuration.model||'—')));
    $('evalSummary').append(el('p','evaluation-note',t('当前为方法复现与反馈适配，不代表论文原实验。论文模型为 Gemini 2.5 Flash；当前实际模型与执行后端以本轮记录为准。')));
    if(d.configuration.baseline_reference?.execution_mode==='remote_GraphDB')$('evalSummary').append(el('p','evaluation-note',t('GraphDB 仓库：')+(d.configuration.evaluation_graph?.endpoint||'—')+' · '+t('Critic 接收作者前 10 行结果反馈；全量结果用于评分。')));
    if(d.configuration.baseline_reference?.feedback_policy==='rdflib_graphdb_preview_v1')$('evalSummary').append(el('p','evaluation-note',t('本轮由 RDFLib 执行；Critic 接收列名、总行数及前 10 行真实结果。结果反馈参照作者 GraphDB 分支，执行后端仍为本地 RDFLib。')));
    else if(d.configuration.baseline_reference?.execution_mode==='local_rdflib')$('evalSummary').append(el('p','evaluation-note',t('本轮使用作者本地 RDFLib 分支，Critic 仅接收行数；官方演示使用 GraphDB 并反馈前 10 行结果。此报告不代表论文运行环境完全一致。')));
  }
  if(d.status==='running'){$('evalMethod').value=d.configuration?.method||'brickqa';$('reactBackend').value=d.configuration?.react_backend||'rdflib';}
  $('evalResults').replaceChildren();
  if(d.restored_from_disk)$('evalResults').append(el('p','warn-text',t('历史报告只读显示，分数未按当前策略重新计算。')));
  if(['cancelled','interrupted'].includes(d.status))root.append(el('p','warn-text',t('评测已停止。以下分数仅汇总已完成题目，不代表完整基准成绩；未完成题目不计零分。')));
  if(d.status==='running'&&!S.status?.evaluation_cancellation)root.append(el('p','warn-text',t('本轮正在由旧版服务执行，取消功能需服务更新后生效；请勿重复启动评测。')));
  if(d.status==='running'){
    const currents=d.active_questions||(d.current?[d.current]:[]);
    root.append(el('p','micro',t('并发执行：')+(d.configuration?.workers||1)+t(' · 运行中：')+currents.length));
    for(const c of currents){const phase=evaluationPhase(c);root.append(el('p','evaluation-current',t('当前第 ')+c.index+'/'+c.total+t(' 题 · ')+phase+' · '+(c.elapsed_seconds||0)+'s'+(c.steps!=null?' · '+c.steps+t(' 个动作'):'')+'\n'+c.question));}
  }
  if(summary.gold_errors)$('evalResults').append(el('p','error-message',t('标准查询异常，当前汇总不可比较。')));
  const rows=[...(d.results||[]),...(d.interrupted_questions||(d.interrupted_question?[d.interrupted_question]:[]))];rows.sort((a,b)=>(a.question_index||0)-(b.question_index||0));
  rows.forEach((row,position)=>{
    const index=row.question_index??position;
    const failed=['error','gold_error'].includes(row.status),body=el('div','card-body');
    const label=row.status==='cancelled'?t('已取消'):failed?t('异常'):row.exact_match_f1===1?t('完全匹配'):t('未完全匹配');
    const title=el('span','evaluation-question',row.question),heading=el('span','evaluation-heading');heading.append(title,el('span','pill'+(failed?' error':''),label));
    const c=dropdown(index,'',body);c.querySelector('summary').append(heading);c.classList.add('card','evaluation-row');
    body.append(el('p','muted','Entity-set F1: '+metricValue(row.entity_set_f1)+' · Row Matching F1: '+metricValue(row.row_matching_f1)+' · Exact Match F1: '+metricValue(row.exact_match_f1)));
    body.append(el('p','micro',t('标准：\n')+(row.gold_count??'—')+t(' 行 / 预测 ')+(row.pred_count??'—')+t(' 行')));
    body.append(dropdown(index+':reason',t('评分说明与失败原因'),recordedMessage(evaluationReason(row))));
    const comparison=el('div','evaluation-comparison');
    for(const [label,query] of [[t('标准 SPARQL'),row.gold_sparql],[t('生成 SPARQL'),row.pred_sparql]]){const part=el('div');part.append(el('h4','',label),el('pre','code',query||t('未记录')));comparison.append(part);}
    body.append(dropdown(index+':queries',t('对照标准与生成查询'),comparison));
    const results=el('div','evaluation-comparison');
    for(const [label,data] of [[t('标准结果'),row.gold_rows],[t('预测结果'),row.pred_rows]]){const part=el('div');part.append(el('h4','',label));if(data==null)part.append(el('p','muted',t('未记录')));else if(!data.length)part.append(el('p','muted',t(label===t('预测结果')&&row.status!=='done'?'未得到可执行结果':'合法空结果')));else{part.append(table(data.slice(0,50)));if(data.length>50)part.append(el('p','micro',t('仅展示前 50 行，完整内容请导出评测 JSON。')));}results.append(part);}
    body.append(dropdown(index+':results',t('标准与预测结果对照'),results));
    const trace=el('div');if(BrickI18n.language==='en'&&row.language==='zh')trace.append(el('p','warn-text','This run used Chinese prompts. English step summaries are display-only; the original trace is preserved below. New runs always use upstream English prompts.'));trace.append(el('p','muted',t('停止原因：')+(row.stop_reason||t('未记录'))+' · '+t('动作数：')+(row.steps??'—')+' · '+t('用时：')+(row.elapsed_sec??'—')+'s'));
    for(const [step,a] of (row.actions||[]).entries())trace.append(traceStep(a,step));
    if(!row.actions?.length)trace.append(el('p','muted',t('未记录执行轨迹')));
    body.append(dropdown(index+':trace',t('执行详情与过程'),trace));
    if(row.model_diagnostics?.length)body.append(dropdown(index+':model-diagnostics',t('模型调用诊断（原始记录）'),el('pre','code',JSON.stringify(row.model_diagnostics,null,2))));
    if(row.diagnostic_warnings?.length)body.append(dropdown(index+':warnings',t('校验诊断（仅记录）'),el('pre','code',row.diagnostic_warnings.join('\n'))));if(row.tool_diagnostics?.length)body.append(dropdown(index+':diagnostics',t('方法与定位诊断'),el('pre','code',JSON.stringify(row.tool_diagnostics,null,2))));
    $('evalResults').append(c);
  });
  if(d.error)$('evalResults').prepend(recordedMessage(d.error));
  $('evalExport').hidden=!d.report_path;
  if(d.report_path){$('evalExport').href='/api/eval_task/'+d.task_id+'/export';$('evalExport').download='brickqa-evaluation.json';}
  root.scrollTop=scroll;if(document.body.classList.contains('evaluation-page'))window.scrollTo(0,pageScroll);
}
function selectRunningBenchmark(path){
  const normalized=path.replaceAll('\\','/');
  const option=[...$('benchSelect').options].find(o=>normalized===o.value||normalized.endsWith('/'+o.value));
  if(option)$('benchSelect').value=option.value;
}
function recoveryEvaluationId(){
  const urlId=new URL(location.href).searchParams.get('evaluation');
  if(urlId&&/^e[a-f0-9]+$/.test(urlId))return urlId;
  try{return localStorage.getItem('brickqa-active-evaluation');}catch(_){return null;}
}
function pollEvaluation(tid){
  clearTimeout(S.evalTimer);S.evalPoll=tid;
  try{localStorage.setItem('brickqa-active-evaluation',tid);}catch(_){}
  const poll=async()=>{try{
    const d=await api('/api/eval_task/'+tid);if(S.evalPoll!==tid)return;
    d.task_id=tid;S.evaluation=d;S.evaluating=d.status==='running';renderEvaluation(d);controls();
    if(d.status==='running')S.evalTimer=setTimeout(poll,1600);
    else{S.evalPoll=null;try{localStorage.removeItem('brickqa-active-evaluation');}catch(_){}await refreshStatus();}
  }catch(error){
    if(error.status===404){S.evalPoll=null;S.evaluating=false;try{localStorage.removeItem('brickqa-active-evaluation');}catch(_){}$('evalResults').replaceChildren(el('p','error-message',t('评测记录不存在，服务可能已重启。')));controls();return;}
    toast(t('正在恢复评测连接…'),true);S.evalTimer=setTimeout(poll,5000);
  }};
  poll();
}

async function changeLanguage(){
  BrickI18n.setLanguage($('languageSelect').value);S.signature='';loadContextOptions();
  const groups=$('buildingSelect').querySelectorAll('optgroup');
  if(groups[0])groups[0].label=t('完整建筑');if(groups[1])groups[1].label=t('论文上下文样本');
  if(S.active&&S.cache.has(S.active))renderAnswer(S.cache.get(S.active));
  if(S.evaluation)renderEvaluation(S.evaluation);
  await refreshStatus();await loadExamples();await loadHistory();
}
$('languageSelect').onchange=changeLanguage;
$('askForm').onsubmit=e=>{e.preventDefault();ask($('questionInput').value);};$('questionInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();ask($('questionInput').value);}};$('loadBtn').onclick=doLoad;$('cancelBtn').onclick=async()=>{try{await api('/api/task/'+S.running+'/cancel',{});$('cancelBtn').disabled=true;toast(t('已请求取消，当前请求结束后恢复查询'));}catch(e){toast(e.message,true);}};$('searchForm').onsubmit=e=>{e.preventDefault();searchEntities();};$('sparqlRun').onclick=runSparql;$('sparqlPrefixes').onclick=loadPrefixes;$('evalRun').onclick=runEvaluation;$('evalCancel').onclick=cancelEvaluation;$('sidebarToggle').onclick=()=>drawer(!$('sidebar').classList.contains('open'));$('drawerBackdrop').onclick=()=>drawer(false);document.onkeydown=e=>{if(e.key==='Escape'){drawer(false);closeModels();}if(e.key==='Tab'&&!$('modelPanel').hidden){const focusable=[...$('modelPanel').querySelectorAll('button,input,select')].filter(n=>!n.disabled);const first=focusable[0],last=focusable[focusable.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}};document.querySelectorAll('.tab').forEach(n=>n.onclick=()=>showTab(n.dataset.tab));
(async()=>{try{await loadBuildings();await refreshStatus(true);await loadExamples();await loadHistory();setInterval(refreshStatus,8000);drawer(false);matchMedia('(max-width:760px)').addEventListener('change',()=>drawer(false));}catch(e){toast(t('初始化失败：')+e.message,true);}})();

function modelControls(){
  const running=S.pending||!!S.running||S.evaluating||S.status?.loading;
  if(!$('modelSave'))return;
  $('modelSave').disabled=modelPending||running;
  $('modelSelect').disabled=modelPending;
  $('modelApiKey').disabled=modelPending;
  $('modelTest').disabled=modelPending||running||!modelCatalog||$('modelSelect').value!==modelCatalog.active.profile_id||!!$('modelApiKey').value;
  $('modelSaveHint').textContent=running?t('任务运行中，完成或取消后才能切换模型。'):t('先应用模型，再测试连接。');
}
function selectedModelInfo(){
  if(!modelCatalog)return;
  const profile=modelCatalog.profiles.find(p=>p.profile_id===$('modelSelect').value);
  if(!profile)return;
  $('modelEndpoint').textContent=profile.base_url;
  $('modelKeyState').textContent=(profile.configured?t('密钥已配置'):t('需要配置此模型的密钥'))+(profile.profile_id===modelCatalog.active.profile_id?t(' · 当前模型'):'');
  modelControls();
}
async function openModels(){
  try{
    modelCatalog=await api('/api/models');
    $('modelSelect').replaceChildren(...modelCatalog.profiles.map(profile=>{const option=el('option','',profile.model+' · '+profile.provider);option.value=profile.profile_id;return option;}));
    $('modelSelect').value=modelCatalog.active.profile_id;$('modelApiKey').value='';$('modelResult').textContent='';selectedModelInfo();
    $('modelPanel').hidden=false;$('modelBackdrop').hidden=false;document.body.classList.add('model-panel-open');$('modelChooser').setAttribute('aria-expanded','true');
    void $('modelPanel').offsetWidth;
    requestAnimationFrame(()=>$('modelPanel').classList.add('open'));$('modelSelect').focus();
  }catch(e){toast(e.message,true);}
}
function closeModels(){
  if($('modelPanel').hidden)return;
  $('modelPanel').classList.remove('open');$('modelPanel').hidden=true;$('modelBackdrop').hidden=true;document.body.classList.remove('model-panel-open');$('modelApiKey').value='';$('modelChooser').setAttribute('aria-expanded','false');$('modelChooser').focus();
}
async function applyModel(){
  if($('modelSave').disabled)return;
  modelPending=true;modelControls();
  try{
    const payload={profile_id:$('modelSelect').value};if($('modelApiKey').value)payload.api_key=$('modelApiKey').value;
    const selected=await api('/api/models/select',payload);$('modelApiKey').value='';modelCatalog=await api('/api/models');selectedModelInfo();
    $('modelResult').textContent=t('当前模型：')+selected.model;await refreshStatus();toast(t('模型已切换：')+selected.model);
  }catch(e){$('modelResult').textContent=e.message;toast(e.message,true);}finally{modelPending=false;modelControls();}
}
async function testCurrentModel(){
  if($('modelTest').disabled)return;
  modelPending=true;modelControls();$('modelResult').textContent=t('正在测试连接…');
  try{const result=await api('/api/models/test',{});$('modelResult').textContent=t('连接成功：')+result.model+' · '+result.response_model;}
  catch(e){$('modelResult').textContent=t('连接失败：')+e.message;}finally{modelPending=false;modelControls();await refreshStatus();}
}
$('modelChooser').onclick=openModels;$('modelClose').onclick=closeModels;$('modelBackdrop').onclick=closeModels;$('modelForm').onsubmit=e=>{e.preventDefault();applyModel();};$('modelSelect').onchange=()=>{$('modelApiKey').value='';$('modelResult').textContent='';selectedModelInfo();};$('modelApiKey').oninput=modelControls;$('modelTest').onclick=testCurrentModel;

$('evalMethod').addEventListener('change',()=>{controls();if(S.evaluation)renderEvaluation(S.evaluation);});
$('reactBackend').addEventListener('change',()=>{if(S.evaluation)renderEvaluation(S.evaluation);});
