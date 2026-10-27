"""An exact upstream prompt fragment is text, never an execution graph repair."""
import hashlib
from pathlib import Path
import pytest
from fastapi import HTTPException
import app
from brick_agent import AgentState
from prompting import build_controller_prompt
from test_language_and_metrics import tiny_agent

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT/'prompts/bldg11_sample_5000.ttl'


def test_pinned_fragment_preserves_bytes_and_reports_unknown_triple_count(monkeypatch):
    raw=FILE.read_bytes()
    monkeypatch.setattr(app, 'BASE_DIR', ROOT)
    monkeypatch.setattr(app, '_list_buildings', lambda:([{'ttl':str(FILE)}],[]))
    monkeypatch.setattr(app, 'graph_meta', {'ttl':str(ROOT/'data/buildings/bldg11.ttl')})
    snapshot=app._prepare_ttl_context(app.EvalRequest(context_ttl='prompts/bldg11_sample_5000.ttl'))
    assert snapshot['raw']==raw and snapshot['content'].encode('utf-8')==raw
    assert snapshot['triples'] is None and snapshot['line_count']==5000
    assert snapshot['kind']=='author_prompt_text_fragment'
    assert snapshot['parse_status']=='incomplete_upstream_turtle'
    assert snapshot['sha256']==hashlib.sha256(raw).hexdigest()
    assert app._context_metadata(snapshot)['triples'] is None
    assert FILE.read_bytes()==raw


def test_modified_fragment_is_not_silently_accepted(monkeypatch,tmp_path):
    folder=tmp_path/'prompts';folder.mkdir()
    path=folder/'bldg11_sample_5000.ttl'
    path.write_bytes(FILE.read_bytes()+b'\n# unreviewed change\n')
    monkeypatch.setattr(app,'BASE_DIR',tmp_path)
    monkeypatch.setattr(app,'_list_buildings',lambda:([{'ttl':str(path)}],[]))
    monkeypatch.setattr(app,'graph_meta',{'ttl':str(tmp_path/'data/buildings/bldg11.ttl')})
    with pytest.raises(HTTPException) as error:
        app._prepare_ttl_context(app.EvalRequest(context_ttl=str(path)))
    assert error.value.status_code==400


def test_fragment_reaches_prompt_without_becoming_execution_graph(tiny_agent):
    raw=FILE.read_bytes()
    before=set(tiny_agent.brick_graph.get_graph())
    tiny_agent.ttl_schema_content=raw.decode('utf-8')
    prompt,_=build_controller_prompt(tiny_agent,AgentState('List the VAVs.'))
    assert raw.decode('utf-8') in prompt
    assert set(tiny_agent.brick_graph.get_graph())==before
