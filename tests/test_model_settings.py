import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app
import llm_client
import model_settings
from model_settings import GEMINI_URL, ModelRegistry, protect, unprotect


@pytest.fixture
def registry(monkeypatch, tmp_path):
    monkeypatch.setenv('LLM_MODEL', 'qwen-plus')
    monkeypatch.setenv('LLM_BASE_URL', model_settings.QWEN_URL)
    monkeypatch.setenv('LLM_API_KEY', 'offline-qwen-key')
    monkeypatch.delenv('DASHSCOPE_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    value = ModelRegistry(tmp_path / 'models.json')
    monkeypatch.setattr(model_settings, 'get_registry', lambda: value)
    monkeypatch.setattr(app, 'get_registry', lambda: value)
    monkeypatch.setattr(app, '_active_tid', None)
    monkeypatch.setattr(app, '_eval_running', False)
    monkeypatch.setattr(app, '_loading', False)
    monkeypatch.setattr(app, 'agent', None)
    llm_client.close_thread_client()
    yield value
    llm_client.close_thread_client()


@pytest.mark.skipif(os.name != 'nt', reason='Windows user DPAPI integration')
def test_windows_protection_round_trips_without_plaintext():
    key = 'offline-gemini-test-key'
    encrypted = protect(key)
    assert key not in encrypted and unprotect(encrypted) == key


def test_model_switch_persists_encrypted_keys_and_restores_separate_qwen(registry):
    registry.activate('gemini-2.5-flash', 'offline-gemini-key')
    assert registry.current().model == 'gemini-2.5-flash'
    assert registry.current().base_url == GEMINI_URL
    raw = registry.path.read_text(encoding='utf-8')
    assert 'offline-gemini-key' not in raw and 'offline-qwen-key' not in raw
    assert 'offline-gemini-key' not in repr(registry.current())
    restored = ModelRegistry(registry.path)
    assert restored.current().api_key == 'offline-gemini-key'
    assert restored.current().profile_id == 'gemini-2.5-flash'
    restored.activate('qwen')
    assert restored.current().model == 'qwen-plus-2025-12-01'
    assert restored.current().api_key == 'offline-qwen-key'
    assert restored.current().base_url == model_settings.QWEN_URL


def test_catalog_and_status_never_return_api_keys(registry):
    client = TestClient(app.app)
    response = client.post('/api/models/select', json={'profile_id':'gemini-2.5-flash','api_key':'offline-gemini-key'})
    assert response.status_code == 200
    for path in ['/api/models','/api/status']:
        result = client.get(path)
        assert result.status_code == 200
        assert 'offline-gemini-key' not in result.text and 'offline-qwen-key' not in result.text
    assert client.get('/api/status').json()['model'] == 'gemini-2.5-flash'
    assert client.get('/api/status').json()['base_url'] == GEMINI_URL


@pytest.mark.parametrize('busy_field', ['_active_tid','_eval_running','_loading'])
def test_switch_is_rejected_during_any_running_task(registry, monkeypatch, busy_field):
    monkeypatch.setattr(app, busy_field, 'task' if busy_field == '_active_tid' else True)
    response = TestClient(app.app).post('/api/models/select', json={'profile_id':'gemini-2.5-flash','api_key':'offline-gemini-key'})
    assert response.status_code == 409
    assert registry.current().profile_id == 'qwen' and not registry.path.exists()


def test_clients_are_recreated_after_model_or_key_changes(registry, monkeypatch):
    class OfflineClient:
        def __init__(self):
            active = registry.current()
            self.model, self.base_url = active.model, active.base_url
            self.client = Mock()
    monkeypatch.setattr(llm_client, 'LLMClient', OfflineClient)
    first = llm_client.get_client()
    registry.activate('gemini-2.5-flash', 'offline-gemini-key')
    second = llm_client.get_client()
    assert first is not second and second.model == 'gemini-2.5-flash'
    first.client.close.assert_called_once()
    registry.activate('gemini-2.5-flash', 'offline-rotated-key')
    third = llm_client.get_client()
    assert third is not second
    second.client.close.assert_called_once()


def test_connection_check_releases_busy_and_redacts_key(registry, monkeypatch):
    registry.activate('gemini-2.5-flash', 'offline-gemini-key')
    client = SimpleNamespace(generate_text=Mock(side_effect=RuntimeError('failure offline-gemini-key')))
    monkeypatch.setattr(llm_client, 'get_client', lambda: client)
    response = TestClient(app.app).post('/api/models/test')
    assert response.status_code == 400
    assert 'offline-gemini-key' not in response.text and '[redacted]' in response.text
    assert not app._loading


def test_unconfigured_model_and_unknown_destination_are_rejected(registry):
    client = TestClient(app.app)
    assert client.post('/api/models/select', json={'profile_id':'gemini-2.5-flash'}).status_code == 400
    assert client.post('/api/models/select', json={'profile_id':'unknown','api_key':'offline-test-key'}).status_code == 422
    assert client.post('/api/models/select', json={'profile_id':'gemini-2.5-flash','base_url':'https://other.invalid'}).status_code == 422


def test_saved_floating_alias_migrates_and_actual_request_is_pinned(registry, monkeypatch):
    registry.activate('qwen')
    saved = json.loads(registry.path.read_text(encoding='utf-8'))
    saved['existing_profile']['model'] = 'qwen-plus'
    registry.path.write_text(json.dumps(saved), encoding='utf-8')
    restored = ModelRegistry(registry.path)
    assert restored.current().model == model_settings.QWEN_MODEL
    monkeypatch.setattr(model_settings, 'get_registry', lambda: restored)
    create = Mock(return_value=SimpleNamespace(model=model_settings.QWEN_MODEL, usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content='OK'))]))
    monkeypatch.setattr(llm_client, 'OpenAI', lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    client = llm_client.LLMClient()
    client.generate_text('offline', max_retries=1)
    assert create.call_args.kwargs['model'] == 'qwen-plus-2025-12-01'


def test_missing_model_defaults_to_fixed_version(monkeypatch, tmp_path):
    monkeypatch.delenv('LLM_MODEL', raising=False)
    monkeypatch.setenv('LLM_BASE_URL', model_settings.QWEN_URL)
    assert ModelRegistry(tmp_path/'absent.json').current().model == model_settings.QWEN_MODEL


@pytest.mark.parametrize('override,expected', [(None,300.0), ('600',600.0)])
def test_model_timeout_reaches_sdk_and_react_metadata(registry, monkeypatch, override, expected):
    from react_reference import reference
    if override is None:
        monkeypatch.delenv('LLM_TIMEOUT', raising=False)
    else:
        monkeypatch.setenv('LLM_TIMEOUT', override)
    sdk = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(llm_client, 'OpenAI', sdk)
    client = llm_client.LLMClient()
    assert client.timeout_seconds == sdk.call_args.kwargs['timeout'] == expected
    assert sdk.call_args.kwargs['max_retries'] == 0
    assert reference()['model_timeout_seconds'] == expected


@pytest.mark.parametrize('value', ['0','-1','nan','inf','invalid'])
def test_model_timeout_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv('LLM_TIMEOUT', value)
    with pytest.raises(ValueError, match='LLM_TIMEOUT'):
        llm_client.llm_timeout_seconds()



def test_react_sdk_retries_transient_failures_without_changing_shared_client(monkeypatch):
    import httpx
    import openai._base_client
    from openai import OpenAI
    from react_reference import reference
    calls = []
    def handle(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, json={'error':{'message':'Transient upstream failure'}})
        return httpx.Response(200, json={'id':'offline','object':'chat.completion','created':0,
            'model':model_settings.QWEN_MODEL,'choices':[{'index':0,'finish_reason':'stop',
            'message':{'role':'assistant','content':'{"decision":"FINAL","feedback":"OK"}'}}]})
    monkeypatch.setattr(openai._base_client.time, 'sleep', lambda seconds:None)
    client = llm_client.LLMClient.__new__(llm_client.LLMClient)
    client.model = model_settings.QWEN_MODEL
    client.api_key = 'offline-key'
    client.base_url = 'https://offline.invalid/v1'
    client.timeout_seconds = 300
    client.client = OpenAI(api_key=client.api_key,base_url=client.base_url,timeout=300,max_retries=0,
                           http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        text = client.generate_messages([{'role':'user','content':'Return JSON.'}],
                    max_retries=1,sdk_max_retries=2,response_format={'type':'json_object'})
        assert json.loads(text)['decision'] == 'FINAL'
        assert len(calls) == 3
        assert client.client.max_retries == 0 and client.client.timeout == 300
        assert reference()['sdk_max_retries'] == 2
        assert 'paper_model_required' not in reference()
    finally:
        client.client.close()
