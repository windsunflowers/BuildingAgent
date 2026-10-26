"""Model inputs are independent of UI language, including failure paths."""
import re
from types import SimpleNamespace

import brick_agent
import llm_client
from brick_agent import BrickAction, BrickSparqlQuery
from test_language_and_metrics import tiny_agent


def test_parse_retry_and_tool_errors_use_same_english_history(tiny_agent, monkeypatch):
    all_prompts = []
    traces = []
    def fail_property(*args):
        raise RuntimeError('Original tool error: keep Case and punctuation!')
    monkeypatch.setattr(brick_agent, 'get_property_examples', fail_property)
    for language in ('zh', 'en'):
        tiny_agent.language = language
        prompts = []
        responses = iter([
            'Thought: Retry formatting.\nAction: invalid_without_parentheses',
            'Thought: Search for a point.\nAction: search_brick(missing_english_point)',
            'Thought: Inspect a property.\nAction: get_property_examples(ref:missing)',
            'Thought: Retrieve a value.\nAction: execute_sparql(SELECT ?x WHERE { VALUES ?x { "A" } })',
            'Thought: Finished.\nAction: stop()'])
        def generate(prompt, **kwargs):
            prompts.append(prompt)
            return next(responses)
        monkeypatch.setattr(llm_client, 'get_client', lambda:SimpleNamespace(
            model='offline', last_usage=None, generate_text=generate))
        state, final = tiny_agent.run('List the values.', verbose=False)
        assert final.execution_result == [{'x':'A'}]
        assert all(not re.search('[一-鿿]', prompt) for prompt in prompts)
        assert 'ERROR: Reply with exactly one Thought:' in prompts[1]
        assert 'No results found.' in prompts[2]
        assert 'Error executing action: Original tool error: keep Case and punctuation!' in prompts[3]
        all_prompts.append(prompts)
        traces.append([(a.thought, a.observation) for a in state.actions])
    assert all_prompts[0] == all_prompts[1]
    assert traces[0] == traces[1]


def test_result_values_and_exception_details_are_never_translated(tiny_agent, monkeypatch):
    # This deliberately Chinese RDF value must remain data, even in an English UI.
    text = '执行错误：原始值'
    action = BrickAction('Keep the original value', 'execute_sparql',
                        'SELECT ?value WHERE { VALUES ?value { "'+text+'" } }')
    result, _ = tiny_agent.execute_action(action)
    assert text in result.observation and 'Execution error:' not in result.observation
    original = 'namespace diagnostic: 原始错误'
    def fail(*args, **kwargs):
        raise RuntimeError(original)
    monkeypatch.setattr(BrickSparqlQuery, 'execute', fail)
    failed, _ = tiny_agent.execute_action(BrickAction('Keep details', 'execute_sparql', 'SELECT * WHERE {}'))
    assert failed.observation == ('PREFIX error: '+original+
        '\n\nWrite every PREFIX URI inside angle brackets.\nRequired prefixes: brick:, bldg:, ref:, xsd:')



def test_retry_translation_is_only_in_browser_and_keeps_source():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('ui/app.js','utf8');
const code=source.slice(source.indexOf('function recordedFeedback('),source.indexOf('function recordedMessage('));
const original='ERROR: Reply with exactly one Thought: and one Action: label. Use Action: execute_sparql(query) or stop(). Do not include Observation:.';
for(const language of ['zh','en']){
 const ctx={BrickI18n:{language}};vm.createContext(ctx);vm.runInContext(code,ctx);
 const shown=ctx.recordedFeedback(original);
 assert.equal(language==='en'?shown:shown.startsWith('格式错误：'),language==='en'?original:true);
 assert.ok(original.startsWith('ERROR:'));
 const detail='Error executing action: CaseSensitive URI urn:keep:Value';
 const translated=ctx.recordedFeedback(detail);
 assert.ok(translated.endsWith('CaseSensitive URI urn:keep:Value'));
}
"""
    subprocess.run(['node', '-e', script], cwd=root, check=True, capture_output=True, text=True)
