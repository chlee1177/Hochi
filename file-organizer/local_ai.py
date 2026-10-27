"""Ollama adapter for local file classification, with no cloud fallback."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_MODEL = 'qwen3:14b'
DEFAULT_URL = 'http://127.0.0.1:11434'
RESPONSE_LIMIT = 4 * 1024 * 1024
CLASSIFICATION_SCHEMA = {
    'type': 'object',
    'properties': {
        'folder': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 3},
        'reason': {'type': 'string'}, 'summary': {'type': 'string'},
        'tags': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 8},
        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
    },
    'required': ['folder', 'reason', 'summary', 'tags', 'confidence'],
    'additionalProperties': False,
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Ollama 주소가 다른 곳으로 연결됩니다. 로컬 서버 주소를 확인하세요.')


class OllamaClient:
    def __init__(self, base_url=DEFAULT_URL, model=DEFAULT_MODEL):
        address = urlsplit(base_url.strip())
        if (address.scheme != 'http' or address.hostname not in {'localhost', '127.0.0.1', '::1'}
                or address.username is not None or address.password is not None
                or address.path not in ('', '/') or address.query or address.fragment):
            raise ValueError('Ollama는 내 PC의 http://localhost:11434 또는 루프백 주소만 사용할 수 있습니다.')
        port = 11434 if address.port is None else address.port
        if not 1 <= port <= 65535:
            raise ValueError('Ollama 포트 번호가 올바르지 않습니다.')
        host = '[::1]' if address.hostname == '::1' else '127.0.0.1'
        self.base_url = f'http://{host}:{port}'
        self.model = model.strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', self.model):
            raise ValueError('Ollama 모델 이름을 입력하세요. 예: qwen3:14b')
        if 'cloud' in self.model.lower():
            raise ValueError('로컬 모드에서는 cloud 모델을 사용할 수 없습니다. 다운로드한 모델을 선택하세요.')
        # Loopback traffic must stay on this machine, even with a system HTTP proxy.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.capabilities = None

    def _request(self, endpoint, payload=None, timeout=15):
        request = Request(self.base_url + endpoint,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(RESPONSE_LIMIT + 1)
            if len(raw) > RESPONSE_LIMIT:
                raise ValueError('Ollama 응답이 너무 큽니다. 모델과 서버를 확인하세요.')
            result = json.loads(raw)
        except HTTPError as error:
            if error.code == 404:
                raise ValueError(f'모델을 찾을 수 없습니다. PowerShell에서 ollama pull {self.model} 실행 후 다시 확인하세요.') from None
            if error.code in (401, 403):
                raise ValueError('Ollama 로컬 서버 접근이 거부되었습니다. cloud 모델과 서버 주소를 확인하세요.') from None
            raise ValueError(f'Ollama 요청 실패 (HTTP {error.code}). 모델 호환성·GPU 메모리와 Ollama 로그를 확인하세요.') from None
        except (URLError, TimeoutError, ConnectionError, OSError):
            raise ValueError('Ollama에 연결하지 못했거나 응답 시간이 초과되었습니다. Ollama 앱 실행과 서버 주소를 확인하세요. 모델 첫 로딩은 시간이 걸릴 수 있습니다.') from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError('Ollama 서버가 올바른 JSON을 반환하지 않았습니다.') from None
        if not isinstance(result, dict) or result.get('error'):
            raise ValueError('Ollama가 오류를 반환했습니다. 설치한 모델과 Ollama 로그를 확인하세요.')
        return result

    def check(self):
        """Check installed model metadata only; never send file contents."""
        result = self._request('/api/show', {'model': self.model})
        if result.get('remote_host') or result.get('remote_model'):
            raise ValueError('이 모델은 원격 서비스를 사용합니다. 로컬 가중치가 설치된 모델을 선택하세요.')
        capabilities = result.get('capabilities', [])
        # Require local weight metadata, including for aliases of cloud models.
        if (not isinstance(result.get('model_info'), dict) or not result['model_info']
                or not isinstance(capabilities, list) or 'completion' not in capabilities):
            raise ValueError('로컬 텍스트 모델 정보를 확인할 수 없습니다. Ollama를 업데이트하고 로컬 모델을 설치하세요.')
        self.capabilities = capabilities
        return f'{self.model} 연결 확인 · ' + ('텍스트·이미지 지원' if 'vision' in capabilities else '텍스트 지원 · 이미지 내용 분석 미지원')

    def __call__(self, content, instructions):
        if self.capabilities is None:
            self.check()
        texts, images = [], []
        for part in content:
            if part['type'] == 'input_text':
                texts.append(part['text'])
            elif part['type'] == 'input_image':
                if 'vision' not in self.capabilities:
                    raise ValueError(f'{self.model}은 이미지 입력을 지원하지 않습니다. 이미지 지원 모델을 선택하거나 내용 분석을 끄고 다시 분석하세요.')
                url = part['image_url']
                if not isinstance(url, str) or not re.match(r'^data:image/(png|jpeg|webp|gif);base64,', url):
                    raise ValueError('로컬 AI에는 파일에서 읽은 이미지 데이터만 전달할 수 있습니다.')
                images.append(url.split(',', 1)[1])
            else:
                raise ValueError('지원하지 않는 AI 입력 형식입니다.')
        message = {'role': 'user', 'content': '\n\n'.join(texts)}
        if images:
            message['images'] = images
        payload = {'model': self.model, 'messages': [{'role': 'system', 'content': instructions}, message],
                   'stream': False, 'format': CLASSIFICATION_SCHEMA, 'keep_alive': '5m',
                   'options': {'temperature': 0.2, 'num_ctx': 16384, 'num_predict': 2048}}
        if 'thinking' in self.capabilities:
            payload['think'] = False
        result = self._request('/api/chat', payload, timeout=180)
        message = result.get('message')
        text = message.get('content') if isinstance(message, dict) else None
        if result.get('done') is not True or result.get('done_reason') == 'length' or not isinstance(text, str) or not text.strip():
            raise ValueError('로컬 AI 답변이 완성되지 않았습니다. 더 짧은 문서나 다른 모델로 다시 분석하세요.')
        return text
