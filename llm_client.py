"""
Unified LLM client for BrickQA.

Replaces the original Vertex AI (Gemini) dependency with any
OpenAI-compatible chat completions API. Default target is Alibaba
DashScope (Qwen models), but aihubmix, Ollama, vLLM, etc. also work.

Configuration via environment variables:
    LLM_BASE_URL  - API base URL
                    (default: https://dashscope.aliyuncs.com/compatible-mode/v1)
    LLM_API_KEY   - API key (required for hosted APIs; any non-empty
                    string works for local Ollama/vLLM)
    LLM_MODEL     - Model name (default: qwen-plus)

Examples:
    DashScope : LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
                LLM_MODEL=qwen-plus | qwen-turbo | qwen-max | qwen-flash
    aihubmix  : LLM_BASE_URL=https://aihubmix.com/v1
                LLM_MODEL=qwen-plus (or any available model)
    Ollama    : LLM_BASE_URL=http://localhost:11434/v1
                LLM_MODEL=qwen2.5:7b  (LLM_API_KEY can be "ollama")
"""

import os
import time
import threading
from urllib.parse import urlsplit

try:
    from openai import OpenAI, APIConnectionError, APITimeoutError
    OPENAI_SDK_AVAILABLE = True
except ImportError:
    OPENAI_SDK_AVAILABLE = False

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"


def _network_access_denied(error: Exception) -> bool:
    """Find socket permission errors even when HTTP transports wrap them."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if (getattr(error, "winerror", None) == 10013
                or getattr(error, "errno", None) in (13, 10013)
                or "[WinError 10013]" in str(error)):
            return True
        error = error.__cause__ or error.__context__
    return False


class LLMClient:
    """OpenAI-compatible chat client with simple retry logic."""

    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        if not OPENAI_SDK_AVAILABLE:
            raise RuntimeError(
                "The 'openai' package is not installed. "
                "Run: pip install openai"
            )
        from model_settings import get_registry
        configuration = get_registry().current()
        self.base_url = base_url or configuration.base_url
        self.api_key = api_key or configuration.api_key
        self.model = model or configuration.model
        self.provider = configuration.provider
        self.profile_id = configuration.profile_id

        if not self.api_key:
            raise RuntimeError(
                "LLM_API_KEY environment variable is not set. "
                "Set it to your API key (DashScope: https://bailian.console.aliyun.com/). "
                "For local Ollama you may set it to any non-empty value, e.g. 'ollama'."
            )

        # Bound every request so a stalled upstream cannot block forever.
        # Default: 30s per attempt and two attempts. The eval harness adds
        # its own per-question wall-clock guard on top.
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key,
                             timeout=float(os.getenv("LLM_TIMEOUT", "30")), max_retries=0)

        # Token usage of the most recent call (dict), None before first call
        self.last_usage = None
        self.last_response_model = None

    def generate_text(self, prompt: str, temperature: float = 0.0,
                      max_retries: int = 2, max_tokens: int = 2048, cancel_event=None) -> str:
        """Send one user prompt, return the assistant text.

        Retries with exponential backoff on failure.
        Updates self.last_usage with token counts when available.
        """
        self.last_usage = None
        self.last_response_model = None
        last_err = None
        for attempt in range(1, max_retries + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("查询已取消")
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                # Record token usage if provided by the backend
                self.last_response_model = getattr(resp, 'model', None) or self.model
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    self.last_usage = {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                    }
                else:
                    self.last_usage = None

                content = resp.choices[0].message.content
                if not content or not content.strip():
                    raise RuntimeError("LLM returned empty content")
                return content
            except Exception as e:
                last_err = e
                if isinstance(e, APIConnectionError) and _network_access_denied(e):
                    raise RuntimeError(
                        "模型连接被系统拒绝（网络访问权限错误 / WinError 10013）。"
                        "请在允许联网的 PowerShell 终端运行 .\\start.ps1 重新启动 BrickQA；"
                        "受限进程需要在沙箱外启动。重复提交或重试无法解除此限制。"
                    ) from e
                code = getattr(e, "status_code", None)
                if code in (400, 401, 403, 404, 422):
                    raise RuntimeError(f"模型服务配置或请求错误（HTTP {code}），请检查模型、地址和 API Key") from e
                wait = min(2 ** attempt, 8)
                safe_error = str(e)
                if getattr(self, 'api_key', None):
                    safe_error = safe_error.replace(self.api_key, '[redacted]')
                print(f"[WARNING] LLM call failed (attempt {attempt}/{max_retries}): {safe_error}")
                if attempt < max_retries:
                    print(f"[INFO] Retrying in {wait}s ...")
                    if cancel_event is not None:
                        if cancel_event.wait(wait):
                            raise RuntimeError("查询已取消") from e
                    else:
                        time.sleep(wait)
        # Surface useful guidance without leaking credentials from an API URL.
        host = urlsplit(self.base_url).hostname or "已配置的模型服务"
        if isinstance(last_err, APITimeoutError):
            raise RuntimeError(
                f"模型服务请求超时（{host}，已尝试 {max_retries} 次）。"
                "请检查网络或稍后重试；必要时调整 LLM_TIMEOUT。"
            ) from last_err
        if isinstance(last_err, APIConnectionError):
            raise RuntimeError(
                f"无法连接模型服务（{host}，已尝试 {max_retries} 次）。"
                "请检查网络、代理和 LLM_BASE_URL。常用问题可切换为“自动”或“本地模板”查询。"
            ) from last_err
        safe_error = str(last_err)
        if getattr(self, 'api_key', None):
            safe_error = safe_error.replace(self.api_key, '[redacted]')
        raise RuntimeError(f"LLM call failed after {max_retries} attempts: {safe_error}") from last_err


_client_state = threading.local()


def get_client() -> LLMClient:
    """Reuse a client in this thread; usage and retries cannot leak between workers."""
    from model_settings import get_registry
    revision = get_registry().current().revision
    if hasattr(_client_state, 'client') and getattr(_client_state, 'revision', None) != revision:
        close_thread_client()
    if not hasattr(_client_state, 'client'):
        _client_state.client = LLMClient()
        _client_state.revision = revision
        print(f"✅ LLM client ready: model={_client_state.client.model} base_url={_client_state.client.base_url}")
    return _client_state.client


def close_thread_client():
    client = getattr(_client_state, 'client', None)
    if client is not None:
        client.client.close()
        del _client_state.client
