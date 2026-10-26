"""Only fully specified benchmarks for the active building are offered."""
import json
from pathlib import Path
import subprocess
import app


def test_benchmarks_follow_loaded_graph_and_exclude_mixed_unknown_or_broken_sets(monkeypatch, tmp_path):
    directory=tmp_path/'benchmarks';directory.mkdir()
    monkeypatch.setattr(app,'BASE_DIR',tmp_path)
    monkeypatch.setattr(app,'PROMPTS_DIR',tmp_path/'prompts')
    def write(name,ttls):
        (directory/name).write_text('\n'.join(json.dumps({'question':'Question','ttl':ttl}) for ttl in ttls),encoding='utf-8')
    for building in ['bldg1','bldg11','TUC_building']:
        write(building+'_all.jsonl',['data/'+building+'.ttl'])
    write('bldg11_human.jsonl',['data/bldg11.ttl'])
    write('mixed.jsonl',['data/bldg11.ttl','data/TUC_building.ttl'])
    write('unknown.jsonl',[None])
    (directory/'broken.jsonl').write_text('not JSON',encoding='utf-8')
    monkeypatch.setattr(app,'graph_meta',{'building':'bldg11','ttl':str(tmp_path/'data/bldg11.ttl')})
    assert app.benchmarks()['benchmarks']==['benchmarks/bldg11_all.jsonl','benchmarks/bldg11_human.jsonl']
    monkeypatch.setattr(app,'graph_meta',{'building':'TUC_building','ttl':str(tmp_path/'data/TUC_building.ttl')})
    assert app.benchmarks()['benchmarks']==['benchmarks/TUC_building_all.jsonl']
    monkeypatch.setattr(app,'graph_meta',{'building':None,'ttl':None})
    assert app.benchmarks()['benchmarks']==[]


def test_react_options_and_method_notes_follow_selection_and_busy_state():
    root=Path(__file__).resolve().parents[1]
    code=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const text=fs.readFileSync('ui/app.js','utf8');
const helper=text.slice(text.indexOf('function evaluationMethodControls('),text.indexOf('function controls('));
const nodes={evalMethod:{value:'brickqa'},reactBackendField:{},reactBackend:{value:'graphdb'},brickqaEvaluationNote:{},reactEvaluationNote:{}};
const ctx={$:id=>nodes[id]};vm.createContext(ctx);vm.runInContext(helper,ctx);
ctx.evaluationMethodControls(false);
assert.equal(nodes.reactBackendField.hidden,true);assert.equal(nodes.reactBackend.disabled,true);
assert.equal(nodes.reactEvaluationNote.hidden,true);assert.equal(nodes.brickqaEvaluationNote.hidden,false);
nodes.evalMethod.value='react';ctx.evaluationMethodControls(false);
assert.equal(nodes.reactBackendField.hidden,false);assert.equal(nodes.reactBackend.disabled,false);
assert.equal(nodes.reactEvaluationNote.hidden,false);assert.equal(nodes.brickqaEvaluationNote.hidden,true);
ctx.evaluationMethodControls(true);assert.equal(nodes.reactBackend.disabled,true);
nodes.evalMethod.value='brickqa';ctx.evaluationMethodControls(false);
assert.equal(nodes.reactBackendField.hidden,true);assert.equal(nodes.reactBackend.value,'graphdb');
'''
    subprocess.run(['node','-e',code],cwd=root,check=True,capture_output=True,text=True)
