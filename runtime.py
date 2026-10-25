"""Small local-only HTTP runtime shared by the three prototypes."""
import argparse
import base64
import json
import os
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_REQUEST = 24 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024


def decode_file(value):
    if not isinstance(value, str):
        raise ValueError('파일 데이터가 올바르지 않습니다.')
    try:
        data = base64.b64decode(value, validate=True)
    except ValueError:
        raise ValueError('파일 인코딩이 올바르지 않습니다.') from None
    if not data or len(data) > MAX_FILE:
        raise ValueError('빈 파일 또는 8 MiB보다 큰 파일은 지원하지 않습니다.')
    return data


def ai_text(content, instructions):
    key = os.environ.get('HOCHI_AI_KEY')
    if not key:
        raise ValueError('실제 AI 기능을 사용하려면 서버에 HOCHI_AI_KEY를 설정하세요.')
    payload = {'model': os.environ.get('HOCHI_AI_MODEL', 'gpt-4.1-mini'),
               'instructions': instructions, 'input': [{'role': 'user', 'content': content}],
               'max_output_tokens': 1800, 'store': False}
    request = Request('https://api.openai.com/v1/responses',
                      data=json.dumps(payload).encode(),
                      headers={'Authorization': 'Bearer ' + key,
                               'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as error:
        raise ValueError(f'AI 서비스 요청 실패 (HTTP {error.code}). 키·모델·사용 한도를 확인하세요.') from None
    except (URLError, TimeoutError):
        raise ValueError('AI 서비스에 연결할 수 없습니다. 네트워크 설정을 확인하세요.') from None
    parts = [part['text'] for item in result.get('output', [])
             for part in item.get('content', []) if part.get('type') == 'output_text']
    if result.get('status') != 'completed' or not parts:
        raise ValueError('AI가 완성된 답변을 반환하지 않았습니다. 다시 시도하세요.')
    return '\n'.join(parts)


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/api/status':
            self.send_json(200, {'ok': True, 'ai': bool(os.environ.get('HOCHI_AI_KEY'))})
        elif self.path.startswith('/api/'):
            self.send_json(404, {'error': '없는 API입니다.'})
        else:
            super().do_GET()

    def do_POST(self):
        # Disallow browser requests originating from other websites.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            self.send_json(403, {'error': '다른 사이트에서 보낸 요청은 허용하지 않습니다.'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > MAX_REQUEST:
                raise ValueError('요청 크기는 0보다 크고 24 MiB 이하여야 합니다.')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('JSON 요청이 필요합니다.')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('JSON 객체가 필요합니다.')
            self.send_json(200, self.handle_api(self.path, payload))
        except (ValueError, KeyError, TypeError) as error:
            self.send_json(400, {'error': str(error)})
        except OSError:
            self.send_json(500, {'error': '파일 작업에 실패했습니다. 저장 공간과 권한을 확인하세요.'})

    def handle_api(self, path, payload):
        raise ValueError('없는 API입니다.')


def serve(handler, directory, port):
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=port)
    args = parser.parse_args()
    server = HTTPServer(('127.0.0.1', args.port), partial(handler, directory=str(Path(directory))))
    print(f'로컬 개발 서버 시작: 포트 {args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
