import hashlib
import json
from pathlib import Path
import pytest
import prompting
from audit_react_run import audit_run
from evaluation_runner import evaluate_question
from react_baseline import ReActBaselineAgent
from test_language_and_metrics import tiny_agent
from test_react_baseline import raw_execution, scripted_client, WRITER, CRITIC, QUERY


@pytest.mark.parametrize('tamper', [None, 'snapshot', 'messages', 'score', 'stop'])
def test_saved_real_message_audit_detects_workflow_and_score_drift(tiny_agent, monkeypatch, raw_execution, tmp_path, tamper):
    monkeypatch.setattr(prompting, 'ROOT', tmp_path)
    tiny_agent.ttl_schema_content='# frozen context'
    scripted_client(monkeypatch,[WRITER(),CRITIC()])
    row=evaluate_question(ReActBaselineAgent(tiny_agent, backend='rdflib'),{'question':'List values','query_id':'test','gold_sparql':QUERY})
    row['question_index']=1
    path=tmp_path/'report.json'
    (tmp_path/'context.ttl').write_bytes(b'# frozen context')
    if tamper=='score':
        row['entity_set_f1']=0
    if tamper=='stop':
        row['stop_reason']='max_iterations'
    events=[json.loads(line) for line in Path(row['prompt_log']).read_text(encoding='utf-8').splitlines()]
    if tamper in ('snapshot','messages'):
        request=next(event for event in events if event['event']=='model_request')
        snapshot=Path(request['prompt_file'])
        messages=json.loads(snapshot.read_bytes());messages[-1]['content']='Changed question'
        snapshot.write_text(json.dumps(messages),encoding='utf-8')
        if tamper=='messages':
            request['prompt_sha256']=hashlib.sha256(snapshot.read_bytes()).hexdigest()
            Path(row['prompt_log']).write_text('\n'.join(json.dumps(event) for event in events),encoding='utf-8')
    path.write_text(json.dumps({'configuration':{'method':'react','baseline_reference':{'feedback_policy':'upstream_rdflib_row_count_only_v1'}},'results':[row]}),encoding='utf-8')
    result=audit_run(path)
    assert result['verified_questions']==(0 if tamper else 1)
    assert result['paper_environment_verified'] is False
    if not tamper:
        assert result['verified_calls']==2
    else:
        assert 'mismatch' in result['results'][0]['error']
