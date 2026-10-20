from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

import llm_client


def make_client(*responses):
    client = object.__new__(llm_client.LLMClient)
    client.base_url = 'https://user:private@example.com/v1?api_key=secret'
    client.model = 'test'
    create = Mock(side_effect=list(responses))
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, create


def connection_error(cause=None):
    error = APIConnectionError(request=httpx.Request('POST', 'https://example.com/v1/chat/completions'))
    error.__cause__ = cause
    return error


@pytest.mark.parametrize('cause', [
    OSError(13, 'Permission denied'),
    httpx.ConnectError('[WinError 10013] Socket access denied'),
])
def test_network_permission_error_fails_without_pointless_retries(cause, monkeypatch):
    error = connection_error(cause)
    client, create = make_client(error)
    sleep = Mock()
    monkeypatch.setattr(llm_client.time, 'sleep', sleep)
    with pytest.raises(RuntimeError, match='网络访问权限错误') as failure:
        client.generate_text('hello')
    assert failure.value.__cause__ is error
    assert create.call_count == 1
    sleep.assert_not_called()


def test_transient_connection_error_still_retries_and_records_usage(monkeypatch):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='OK'))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1, total_tokens=4),
    )
    client, create = make_client(connection_error(), response)
    monkeypatch.setattr(llm_client.time, 'sleep', Mock())
    assert client.generate_text('hello') == 'OK'
    assert create.call_count == 2
    assert client.last_usage['total_tokens'] == 4


@pytest.mark.parametrize('error, message', [
    (connection_error(), '无法连接模型服务'),
    (APITimeoutError(request=httpx.Request('POST', 'https://example.com')), '模型服务请求超时'),
])
def test_connection_failures_explain_cause_without_exposing_url_credentials(error, message, monkeypatch):
    client, create = make_client(error, error)
    monkeypatch.setattr(llm_client.time, 'sleep', Mock())
    with pytest.raises(RuntimeError, match=message) as failure:
        client.generate_text('hello')
    assert create.call_count == 2
    assert 'example.com' in str(failure.value)
    assert 'private' not in str(failure.value)
    assert 'secret' not in str(failure.value)
