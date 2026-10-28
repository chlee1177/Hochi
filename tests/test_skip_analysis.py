import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'file-organizer'))
from folder_organizer import FolderOrganizer, Cancelled
from local_ai import OllamaClient
from analysis_errors import UnsupportedFile

ANSWER = json.dumps({'folder': ['학습'], 'reason': '학습 자료', 'summary': '물리학 과제',
                     'tags': ['물리학'], 'confidence': .9})
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXZkAAAAASUVORK5CYII=')


class SkipAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ai = Mock(return_value=ANSWER)
        self.engine = FolderOrganizer(self.root, ai=self.ai)

    def write(self, name, value=b'notes'):
        path = self.root / name
        path.write_bytes(value)
        return path

    def test_mixed_folder_continues_skips_and_moves_only_supported(self):
        self.write('a.txt')
        unknown = self.write('b.doc')
        broken = self.write('c.docx', b'bad zip')
        self.write('d.txt')
        progress = []
        plan = self.engine.analyze(lambda stage, index, total, item: progress.append(item['status']))
        self.assertEqual(self.ai.call_count, 2)
        self.assertEqual(progress, ['analyzed', 'skipped', 'skipped', 'analyzed'])
        skipped = [i for i in plan['items'] if i['analysis_skipped']]
        self.assertEqual(len(skipped), 2)
        self.assertIn('.doc', skipped[0]['file_type'])
        self.assertIn('추출 불가', skipped[1]['skip_reason'])
        self.assertTrue(all(not i['selected'] and not i['approved_move'] for i in skipped))
        result = self.engine.apply(plan['id'])
        self.assertEqual(len(result['moves']), 2)
        self.assertTrue(unknown.exists() and broken.exists())
        self.assertEqual(self.engine.undo(), 2)
        records = FolderOrganizer(self.root).search()
        self.assertEqual(sum(r.get('analysis_skipped', False) for r in records), 2)

    def test_all_unsupported_is_successful_empty_move_and_preserves_originals(self):
        self.write('a.hwp')
        self.write('b.mp3')
        plan = self.engine.analyze()
        self.ai.assert_not_called()
        self.assertTrue(all(i['status'] == 'skipped' for i in plan['items']))
        self.assertEqual(self.engine.apply(plan['id'])['moves'], [])
        self.assertTrue((self.root / 'a.hwp').exists())

    def test_explicit_filename_mode_can_classify_unknown_format(self):
        self.write('a.doc')
        self.engine.use_content = False
        item = self.engine.analyze()['items'][0]
        self.assertFalse(item['analysis_skipped'])
        self.assertTrue(item['selected'])
        self.ai.assert_called_once()

    def test_manual_skip_invalidates_plan_and_can_be_explicitly_approved(self):
        self.write('a.txt')
        self.write('b.txt')
        old_id = self.engine.analyze()['id']
        self.engine.skip_items(['a.txt', 'b.txt'])
        with self.assertRaises(ValueError):
            self.engine.apply(old_id)
        with self.assertRaisesRegex(ValueError, '승인'):
            self.engine.edit_item('a.txt', '직접/분류', 'a.txt', True)
        item = self.engine.edit_item('a.txt', '직접/분류', 'a.txt', True, approve_review=True)
        self.assertFalse(item['analysis_skipped'])
        result = self.engine.apply(self.engine.plan['id'])
        self.assertEqual(len(result['moves']), 1)
        self.assertTrue((self.root / 'b.txt').exists())
        self.assertIn('건너뛰기', [e['kind'] for e in self.engine.history()])

    def test_typed_input_rejection_does_not_abort_later_files(self):
        self.write('a.txt')
        self.write('b.txt')
        self.write('c.txt')
        self.ai.side_effect = [ANSWER, UnsupportedFile('지원하지 않는 입력 형식'), ANSWER]
        items = self.engine.analyze()['items']
        self.assertEqual([i['status'] for i in items], ['analyzed', 'skipped', 'analyzed'])

    def test_service_error_invalid_json_path_and_cancel_still_abort(self):
        self.write('a.txt')
        self.write('b.txt')
        for failure in (ValueError('service unavailable'), Cancelled('취소')):
            self.ai.side_effect = [ANSWER, failure]
            with self.assertRaises(ValueError):
                self.engine.analyze()
            self.assertIsNone(self.engine.plan)
        self.ai.side_effect = None
        for answer in ('not json', json.dumps({**json.loads(ANSWER), 'folder': ['..', 'escape']})):
            self.ai.return_value = answer
            with self.assertRaises(ValueError):
                self.engine.analyze()
            self.assertIsNone(self.engine.plan)
        self.assertTrue((self.root / 'a.txt').exists())

    def test_changed_file_is_not_silently_skipped(self):
        path = self.write('a.txt')
        def reject(*args):
            path.write_bytes(b'changed')
            raise UnsupportedFile('unsupported')
        self.ai.side_effect = reject
        with self.assertRaisesRegex(ValueError, '바뀌었습니다'):
            self.engine.analyze()
        self.assertIsNone(self.engine.plan)

    def test_image_rejection_after_permission_keeps_other_results(self):
        self.write('a.png', PNG)
        self.write('b.txt')
        client = OllamaClient()
        client.capabilities = ['completion']
        self.engine.ai = client
        with patch.object(client, '_request', return_value={'done': True, 'message': {'content': ANSWER}}):
            self.engine.analyze()
            item = self.engine.analyze_reviewed('a.png', allow_external=True)
        self.assertTrue(item['analysis_skipped'])
        self.assertIn('이미지 입력', item['skip_reason'])
        self.assertTrue(next(i for i in self.engine.plan['items'] if i['relative'] == 'b.txt')['selected'])

    def test_known_media_http_error_is_skippable_without_server_body_leak(self):
        for code in (400, 415, 422, 500):
            client = OllamaClient()
            error = HTTPError('http://127.0.0.1/api/chat', code, 'error', {},
                              io.BytesIO(json.dumps({'error': 'unable to decode image: private-data'}).encode()))
            with patch.object(client.opener, 'open', side_effect=error):
                with self.assertRaises(UnsupportedFile) as caught:
                    client._request('/api/chat', {})
            self.assertNotIn('private-data', str(caught.exception))

    def test_general_http_and_metadata_errors_are_not_skippable(self):
        for endpoint, code, detail in (('/api/chat', 500, 'GPU out of memory'),
                                       ('/api/chat', 400, 'invalid JSON schema'),
                                       ('/api/show', 400, 'unsupported image format'),
                                       ('/api/chat', 429, 'unsupported image format')):
            client = OllamaClient()
            error = HTTPError('http://127.0.0.1' + endpoint, code, 'error', {},
                              io.BytesIO(json.dumps({'error': detail}).encode()))
            with patch.object(client.opener, 'open', side_effect=error):
                with self.assertRaises(ValueError) as caught:
                    client._request(endpoint, {})
            self.assertNotIsInstance(caught.exception, UnsupportedFile)


if __name__ == '__main__':
    unittest.main()
