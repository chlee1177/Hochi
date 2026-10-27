"""Exercise the Ollama wire protocol against a temporary loopback HTTP server."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'file-organizer'))
from local_ai import OllamaClient
from folder_organizer import FolderOrganizer

ANSWER = {'folder': ['학습', '물리학'], 'reason': '물리학 수업 자료', 'summary': '물리학 과제 노트',
          'tags': ['물리학', '과제'], 'confidence': 0.95}


@contextmanager
def fake_ollama():
    state = {'requests': [], 'status': 200, 'capabilities': ['completion', 'thinking'],
             'model_info': {'general.architecture': 'qwen3'}, 'answer': ANSWER,
             'done': True, 'done_reason': 'stop'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append((self.path, body, dict(self.headers)))
            self.send_response(state['status'])
            self.send_header('Content-Type', 'application/json')
            if state['status'] == 302:
                self.send_header('Location', 'https://example.com/api/chat')
            self.end_headers()
            if state['status'] != 200:
                result = {'error': 'private-server-detail-must-not-leak'}
            elif self.path == '/api/show':
                result = {key: state[key] for key in ('capabilities', 'model_info')}
                result.update(state.get('metadata', {}))
            elif self.path == '/api/chat':
                result = {'done': state['done'], 'done_reason': state['done_reason'],
                          'message': {'content': json.dumps(state['answer'], ensure_ascii=False)}}
            else:
                result = {'error': 'unexpected endpoint'}
            self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    state['url'] = f'http://127.0.0.1:{server.server_port}'
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class LocalAITests(unittest.TestCase):
    def test_local_protocol_no_key_schema_and_no_cloud_fallback(self):
        with fake_ollama() as server, patch.dict(os.environ, {'HOCHI_AI_KEY': 'must-not-send'}), patch('runtime.urlopen', side_effect=AssertionError('Cloud called')):
            client = OllamaClient(server['url'])
            result = client([{'type': 'input_text', 'text': '강의 노트'}], 'JSON으로 분류')
            self.assertEqual(json.loads(result), ANSWER)
            path, body, headers = server['requests'][-1]
            self.assertEqual(path, '/api/chat')
            self.assertNotIn('Authorization', headers)
            self.assertFalse(body['stream'])
            self.assertFalse(body['think'])
            self.assertEqual(body['format']['type'], 'object')
            self.assertEqual(body['messages'][1]['content'], '강의 노트')

    def test_check_sends_metadata_only(self):
        with fake_ollama() as server:
            self.assertIn('연결 확인', OllamaClient(server['url']).check())
            self.assertEqual(server['requests'][0][1], {'model': 'qwen3:14b'})
            self.assertEqual(len(server['requests']), 1)

    def test_missing_model_actionable_without_private_error_body(self):
        with fake_ollama() as server:
            server['status'] = 404
            with self.assertRaisesRegex(ValueError, 'ollama pull qwen3:14b') as error:
                OllamaClient(server['url']).check()
            self.assertNotIn('private-server', str(error.exception))

    def test_loopback_only(self):
        for url in ('https://ollama.com', 'http://192.168.1.2:11434', 'http://localhost.evil:11434',
                    'http://u:p@localhost', 'http://localhost/api', 'http://localhost?q=1',
                    'file:///tmp/data', 'http://localhost:99999', 'http://localhost:0', 'http://localhost/#fragment'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                OllamaClient(url)
        self.assertEqual(OllamaClient('http://localhost:11434/').base_url, 'http://127.0.0.1:11434')
        self.assertEqual(OllamaClient('http://[::1]:11434').base_url, 'http://[::1]:11434')

    def test_cloud_model_and_alias_rejected_before_file_send(self):
        with self.assertRaisesRegex(ValueError, 'cloud'):
            OllamaClient(model='qwen3:cloud')
        for metadata in ({'remote_host': 'https://ollama.com'}, {'remote_model': 'remote-model'}):
            with fake_ollama() as server:
                server['metadata'] = metadata
                with self.assertRaisesRegex(ValueError, '원격'):
                    OllamaClient(server['url'], 'my-alias')([{'type': 'input_text', 'text': 'private'}], 'test')
                self.assertEqual([r[0] for r in server['requests']], ['/api/show'])

    def test_missing_local_metadata_rejected(self):
        with fake_ollama() as server:
            server['model_info'] = {}
            with self.assertRaisesRegex(ValueError, '로컬 텍스트'):
                OllamaClient(server['url']).check()

    def test_redirect_cannot_send_content_elsewhere(self):
        with fake_ollama() as server:
            server['status'] = 302
            with self.assertRaisesRegex(ValueError, '다른 곳'):
                OllamaClient(server['url']).check()

    def test_image_rejected_for_text_model(self):
        with fake_ollama() as server:
            with self.assertRaisesRegex(ValueError, '이미지 입력'):
                OllamaClient(server['url'])([{'type': 'input_image', 'image_url': 'data:image/png;base64,YQ=='}], 'test')
            self.assertEqual([r[0] for r in server['requests']], ['/api/show'])

    def test_vision_payload_and_non_thinking_model(self):
        with fake_ollama() as server:
            server['capabilities'] = ['completion', 'vision']
            OllamaClient(server['url'], 'vision-model')([
                {'type': 'input_text', 'text': '사진'},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,YQ=='}], 'test')
            body = server['requests'][-1][1]
            self.assertEqual(body['messages'][1]['images'], ['YQ=='])
            self.assertNotIn('think', body)

    def test_incomplete_response_not_used(self):
        for done, reason in ((False, 'stop'), (True, 'length')):
            with fake_ollama() as server:
                server.update(done=done, done_reason=reason)
                with self.assertRaisesRegex(ValueError, '완성되지'):
                    OllamaClient(server['url'])([], 'test')

    def test_timeout_readable(self):
        client = OllamaClient()
        with patch.object(client.opener, 'open', side_effect=TimeoutError):
            with self.assertRaisesRegex(ValueError, 'Ollama 앱 실행'):
                client.check()

    def test_local_engine_privacy_move_search_and_undo(self):
        with fake_ollama() as server, tempfile.TemporaryDirectory() as directory, patch('runtime.urlopen', side_effect=AssertionError('Cloud called')):
            root = Path(directory)
            note = root / '강의.txt'
            note.write_text('물리학 과제 노트', encoding='utf-8')
            secret = root / '계약서.txt'
            secret.write_text('민감한 문서', encoding='utf-8')
            engine = FolderOrganizer(root, ai=OllamaClient(server['url']))
            plan = engine.analyze()
            self.assertTrue(note.exists())
            self.assertTrue(next(i for i in plan['items'] if i['relative'] == secret.name)['review_required'])
            chats = [r[1] for r in server['requests'] if r[0] == '/api/chat']
            self.assertEqual(len(chats), 1)
            self.assertNotIn('계약서', str(chats))
            engine.apply(plan['id'])
            self.assertFalse(note.exists())
            self.assertTrue(secret.exists())
            self.assertTrue(engine.search('물리학'))
            engine.undo()
            self.assertTrue(note.exists())

    def test_invalid_model_output_cannot_move_files(self):
        with fake_ollama() as server, tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / 'note.txt'
            note.write_text('physics')
            server['answer'] = {**ANSWER, 'folder': ['..', 'escape']}
            engine = FolderOrganizer(root, ai=OllamaClient(server['url']))
            with self.assertRaises(ValueError):
                engine.analyze()
            self.assertTrue(note.exists())
            self.assertIsNone(engine.plan)


if __name__ == '__main__':
    unittest.main()
