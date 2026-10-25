import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runtime


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


organizer = load('organizer', 'file-organizer/organizer.py')
image = load('image_server', 'image-summary/backend/server.py')


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = organizer.Organizer(self.temp.name)

    def upload(self, name='report.pdf', data=b'example content'):
        return self.engine.handle('/api/upload', {'files': [{'name': name, 'data': base64.b64encode(data).decode()}]})

    def test_copy_plan_move_undo_preserves_bytes(self):
        self.upload()
        plan = self.engine.handle('/api/plan', {'mode': 'rules'})
        self.assertEqual(plan['items'][0]['category'], '문서')
        result = self.engine.handle('/api/apply', {'id': plan['id']})
        self.assertEqual(len(result['moved']), 1)
        target = Path(self.temp.name) / 'organized/문서/report.pdf'
        self.assertEqual(target.read_bytes(), b'example content')
        self.engine.handle('/api/undo', {})
        self.assertFalse(target.exists())
        self.assertEqual((self.engine.incoming / 'report.pdf').read_bytes(), b'example content')

    def test_collisions_and_undo_do_not_overwrite(self):
        self.upload(data=b'first')
        plan = self.engine.handle('/api/plan', {})
        self.engine.handle('/api/apply', {'id': plan['id']})
        self.upload(data=b'second')
        self.engine.handle('/api/undo', {})
        self.assertEqual((self.engine.incoming / 'report.pdf').read_bytes(), b'second')
        self.assertEqual((self.engine.incoming / 'report (1).pdf').read_bytes(), b'first')

    def test_stale_plan_rejected(self):
        self.upload()
        plan = self.engine.handle('/api/plan', {})
        self.upload('new.txt')
        with self.assertRaises(ValueError): self.engine.handle('/api/apply', {'id': plan['id']})

    def test_path_traversal_sanitized(self):
        self.upload('../../outside.txt')
        self.assertEqual(len(self.engine.files()), 1)
        self.assertNotIn('/', self.engine.files()[0]['name'])

    def test_invalid_batch_writes_nothing(self):
        with self.assertRaises(ValueError):
            self.engine.handle('/api/upload', {'files': [{'name': 'ok.txt', 'data': 'YQ=='}, {'name': 'bad.txt', 'data': '!'}]})
        self.assertEqual(self.engine.files(), [])

    def test_ai_classification_and_untrusted_folder(self):
        self.upload()
        with patch.object(organizer, 'ai_text', return_value='{"report.pdf":"문서"}'):
            self.assertEqual(self.engine.handle('/api/plan', {'mode': 'ai'})['mode'], 'ai')
        with patch.object(organizer, 'ai_text', return_value='{"report.pdf":"../../escape"}'):
            with self.assertRaises(ValueError): self.engine.handle('/api/plan', {'mode': 'ai'})
        self.assertIsNone(self.engine.plan)

    def test_rollback_on_second_move_failure(self):
        self.upload('first.pdf')
        self.upload('second.pdf')
        plan = self.engine.handle('/api/plan', {})
        rename = Path.rename
        def fail_once(source, target):
            if source.name == 'second.pdf': raise OSError('simulated failure')
            return rename(source, target)
        with patch.object(Path, 'rename', fail_once):
            with self.assertRaises(OSError): self.engine.handle('/api/apply', {'id': plan['id']})
        self.assertEqual(len(self.engine.files()), 2)


class ImageTests(unittest.TestCase):
    def test_image_forwarded_and_summary_returned(self):
        handler = object.__new__(image.ImageHandler)
        data = b'\x89PNG\r\n\x1a\nexample'
        with patch.object(image, 'ai_text', return_value='한국어 요약') as ai:
            result = handler.handle_api('/api/analyze', {'mime': 'image/png', 'data': base64.b64encode(data).decode()})
        self.assertEqual(result['summary'], '한국어 요약')
        self.assertTrue(ai.call_args.args[0][1]['image_url'].startswith('data:image/png;base64,'))

    def test_invalid_image_rejected_before_ai(self):
        handler = object.__new__(image.ImageHandler)
        with patch.object(image, 'ai_text') as ai:
            with self.assertRaises(ValueError): handler.handle_api('/api/analyze', {'mime': 'image/png', 'data': 'aGVsbG8='})
            ai.assert_not_called()


class AITests(unittest.TestCase):
    def test_missing_key_is_explicit(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'HOCHI_AI_KEY'): runtime.ai_text([], 'test')

    def test_completed_response_parsed(self):
        from io import BytesIO
        body = {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': 'summary'}]}]}
        with patch.dict(os.environ, {'HOCHI_AI_KEY': 'test-only-placeholder'}), patch.object(runtime, 'urlopen', return_value=BytesIO(json.dumps(body).encode())):
            self.assertEqual(runtime.ai_text([], 'test'), 'summary')

    def test_http_error_contains_no_key(self):
        with patch.dict(os.environ, {'HOCHI_AI_KEY': 'test-only-placeholder'}), patch.object(runtime, 'urlopen', side_effect=HTTPError('url', 401, 'unauthorized', {}, None)):
            with self.assertRaisesRegex(ValueError, 'HTTP 401') as error: runtime.ai_text([], 'test')
            self.assertNotIn('test-only-placeholder', str(error.exception))


if __name__ == '__main__':
    unittest.main()
