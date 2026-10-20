"""Local model profiles; credentials are encrypted with Windows user DPAPI."""
from dataclasses import dataclass, field
from pathlib import Path
import base64
import ctypes
import json
import os
import threading

GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/openai/'
QWEN_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
CONFIG_PATH = Path(__file__).resolve().parent / '.local/model_profiles.json'


def _crypt(raw, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Encrypted credential storage requires Windows; configure provider keys through environment variables on other platforms')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError('Windows could not decrypt the local model credentials' if decrypt else 'Windows could not encrypt the model credentials')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def protect(value):
    return base64.b64encode(_crypt(value.encode('utf-8'))).decode('ascii')


def unprotect(value):
    return _crypt(base64.b64decode(value), decrypt=True).decode('utf-8')


@dataclass(frozen=True)
class ModelConfiguration:
    profile_id: str
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    revision: int = 0

    def public(self):
        return {'profile_id': self.profile_id, 'provider': self.provider, 'model': self.model,
                'base_url': self.base_url, 'configured': bool(self.api_key)}


class ModelRegistry:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.revision = 0
        model = os.getenv('LLM_MODEL', 'qwen-plus')
        url = os.getenv('LLM_BASE_URL', QWEN_URL)
        gemini_env = 'generativelanguage.googleapis.com' in url
        self.profiles = {
            'qwen': {'provider':'Qwen / OpenAI-compatible', 'model':'qwen-plus' if gemini_env else model,
                     'base_url':QWEN_URL if gemini_env else url},
            'gemini-2.5-flash': {'provider':'Google Gemini', 'model':'gemini-2.5-flash', 'base_url':GEMINI_URL},
        }
        self.keys = {'qwen':os.getenv('DASHSCOPE_API_KEY', '') or (os.getenv('LLM_API_KEY', '') if not gemini_env else ''),
                     'gemini-2.5-flash':os.getenv('GEMINI_API_KEY', '') or (os.getenv('LLM_API_KEY', '') if gemini_env else '')}
        self.active_id = 'gemini-2.5-flash' if gemini_env else 'qwen'
        if self.path.is_file():
            try:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                if saved.get('version') != 1 or saved['active_id'] not in self.profiles:
                    raise ValueError('Unsupported configuration')
                # Only the original existing endpoint is persisted. The Gemini
                # destination remains pinned to Google's documented endpoint.
                existing = saved.get('existing_profile')
                if existing:
                    self.profiles['qwen'] = existing
                self.keys.update({k:unprotect(v) for k,v in saved.get('encrypted_keys', {}).items() if k in self.profiles})
                self.active_id = saved['active_id']
            except Exception:
                raise RuntimeError('Local model settings could not be read/decrypted by this Windows user') from None
        self._export_environment()

    def current(self):
        with self.lock:
            return ModelConfiguration(self.active_id, **self.profiles[self.active_id],
                                      api_key=self.keys.get(self.active_id, ''), revision=self.revision)

    def catalog(self):
        with self.lock:
            return {'active':self.current().public(), 'profiles':[
                {'profile_id':key, **value, 'configured':bool(self.keys.get(key))}
                for key,value in self.profiles.items()]}

    def activate(self, profile_id, api_key=None):
        with self.lock:
            if profile_id not in self.profiles:
                raise ValueError('Unknown model profile')
            keys = dict(self.keys)
            if api_key is not None and api_key.strip():
                candidate = api_key.strip()
                if len(candidate) > 4096 or any(c.isspace() for c in candidate):
                    raise ValueError('API key must not contain whitespace')
                keys[profile_id] = candidate
            if not keys.get(profile_id):
                raise ValueError('Enter an API key for this provider first')
            saved = {'version':1, 'active_id':profile_id, 'existing_profile':self.profiles['qwen'],
                     'encrypted_keys':{k:protect(v) for k,v in keys.items() if v}}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
            self.active_id, self.keys = profile_id, keys
            self.revision += 1
            self._export_environment()
            return self.current().public()

    def _export_environment(self):
        active = self.current()
        os.environ.update(LLM_MODEL=active.model, LLM_BASE_URL=active.base_url, LLM_API_KEY=active.api_key)


_registry = None
_registry_lock = threading.RLock()


def get_registry():
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = ModelRegistry()
        return _registry
