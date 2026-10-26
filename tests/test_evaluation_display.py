"""Report facts must remain independent of the next-run selection."""
from pathlib import Path
import subprocess


def test_saved_backend_and_empty_result_reasons_in_both_languages():
    root=Path(__file__).resolve().parents[1]
    script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('ui/app.js','utf8');
const helpers=source.slice(source.indexOf('function evaluationBackend('),source.indexOf('function renderEvaluation('));
const translations=fs.readFileSync('ui/i18n.js','utf8');
const english=vm.runInNewContext('('+translations.slice(translations.indexOf('const english = ')+16,translations.indexOf('\n  };')+4).trim().replace(/;$/,'')+')');
for(const language of ['zh','en']){
 const ctx={t:s=>language==='en'?(english[s]||s):s};vm.createContext(ctx);vm.runInContext(helpers,ctx);
 // No current selector is passed to the report helper, even if the UI shows GraphDB.
 assert.equal(ctx.evaluationBackend({react_backend:'rdflib',baseline_reference:{execution_mode:'local_rdflib'}}),'rdflib');
 assert.equal(ctx.evaluationBackend({react_backend:'graphdb',baseline_reference:{execution_mode:'remote_GraphDB'}}),'graphdb');
 assert.equal(ctx.evaluationBackend({}),null);
 const row={status:'done',pred_count:0,actions:[{action_name:'execute_sparql',result_count:18},{action_name:'execute_sparql',result_count:0}]};
 const reason=ctx.evaluationReason(row);assert.ok(reason.includes('18'));
 const scoring=language==='en'?'Computing official F1 (column alignment may take time)':'计算官方 F1（列匹配可能耗时）';
 assert.equal(ctx.evaluationPhase({stage:'scoring'}),scoring);
 assert.equal(ctx.evaluationPhase({stage:'model',phase:'完成'}),scoring);
 assert.notEqual(ctx.evaluationPhase({stage:'model',phase:'执行 execute_sparql'}),scoring);
 assert.ok(reason.includes(language==='en'?'last generated query':'最后生成的查询'));
 assert.equal(ctx.evaluationReason({...row,error:'Original error'}),'Original error');
 if(language==='en')assert.ok(!/[\u4e00-\u9fff]/.test(reason));
}
'''
    subprocess.run(['node','-e',script],cwd=root,check=True,capture_output=True,text=True)


from test_language_and_metrics import tiny_agent
from test_react_baseline import raw_execution, scripted_client, WRITER, CRITIC, QUERY


def test_scoring_is_reported_before_metric_work_and_preserves_trace(tiny_agent, monkeypatch, raw_execution):
    import evaluation_runner
    from react_baseline import ReActBaselineAgent
    _, calls = scripted_client(monkeypatch, [WRITER(), CRITIC()])
    stages = []
    official = evaluation_runner.score_rows
    def score(gold, pred):
        assert stages == ['gold', 'model', 'scoring']
        assert agent._current_state.phase == '计算官方 F1'
        return official(gold, pred)
    monkeypatch.setattr(evaluation_runner, 'score_rows', score)
    agent = ReActBaselineAgent(tiny_agent, backend='rdflib')
    row = evaluation_runner.evaluate_question(agent, {'question':'List values','gold_sparql':QUERY},
                                              on_progress=stages.append)
    assert row['status'] == 'done' and row['exact_match_f1'] == 1
    assert row['steps'] > 0 and row['actions'] and row['tokens']['total'] > 0
    assert len(calls) == 2
