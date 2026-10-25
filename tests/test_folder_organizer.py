import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'file-organizer'))
from folder_organizer import Cancelled, FolderOrganizer, OUTPUT_NAME, digest, evidence


def response(category='학습'):
    return json.dumps({'category': category, 'reason': '학습 관련 내용입니다.', 'summary': '학습 자료', 'tags': ['학습'], 'confidence': 0.9}, ensure_ascii=False)


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ai = Mock(return_value=response())
        self.engine = FolderOrganizer(self.root, ai=self.ai)

    def write(self, name, data=b'example'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def apply(self):
        plan = self.engine.analyze()
        return self.engine.apply(plan['id'])

    def test_recursive_content_analysis_move_and_restart_undo(self):
        original = self.write('lecture/notes.txt', '물리학 시험 공부'.encode())
        self.write('empty.bin', b'')
        result = self.apply()
        self.assertEqual(self.ai.call_count, 2)
        sent = [part.get('text', '') for call in self.ai.call_args_list for part in call.args[0]]
        self.assertIn('물리학 시험 공부', sent)
        self.assertFalse(original.exists())
        self.assertEqual(len(result['moves']), 2)
        new = FolderOrganizer(self.root)
        self.assertEqual(new.undo(), 2)
        self.assertEqual(original.read_text(), '물리학 시험 공부')
        self.assertEqual((self.root / 'empty.bin').read_bytes(), b'')

    def test_excludes_output_and_optional_nested_folders(self):
        self.write('top.txt')
        self.write('nested/deep.txt')
        self.write(OUTPUT_NAME + '/학습/old.txt')
        self.engine.recursive = False
        self.assertEqual([x['relative'] for x in self.engine.scan()], ['top.txt'])
        self.engine.recursive = True
        self.assertEqual(len(self.engine.scan()), 2)

    def test_no_fifty_file_or_eight_mib_move_limit(self):
        for i in range(51):
            self.write(f'{i:02}.txt')
        large = self.write('large.bin', b'x' * (8 * 1024 * 1024 + 1))
        result = self.apply()
        self.assertEqual(len(result['moves']), 52)
        self.assertFalse(large.exists())
        self.engine.undo()
        self.assertEqual(large.stat().st_size, 8 * 1024 * 1024 + 1)

    def test_collision_never_overwrites_and_undo_preserves_existing(self):
        self.write('a/file.txt', b'first')
        self.write('b/file.txt', b'second')
        existing = self.write(OUTPUT_NAME + '/학습/file.txt', b'old')
        self.apply()
        self.assertEqual(existing.read_bytes(), b'old')
        self.assertEqual((existing.parent / 'file (1).txt').read_bytes(), b'first')
        self.assertEqual((existing.parent / 'file (2).txt').read_bytes(), b'second')
        self.engine.undo()
        self.assertEqual(existing.read_bytes(), b'old')
        self.assertEqual((self.root / 'b/file.txt').read_bytes(), b'second')

    def test_ai_failure_keeps_all_originals_and_no_plan(self):
        self.write('a.txt')
        self.write('b.txt')
        self.ai.side_effect = [response(), ValueError('AI service unavailable')]
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.engine.analyze()
        self.assertIsNone(self.engine.plan)
        self.assertTrue((self.root / 'a.txt').exists())
        self.assertFalse(self.engine.output.exists())

    def test_rejects_invalid_ai_category_and_json(self):
        self.write('report.txt')
        for output in (response('../../outside'), 'not json', '[]', '{"category":"학습"}'):
            self.ai.return_value = output
            with self.assertRaises(ValueError):
                self.engine.analyze()
            self.assertIsNone(self.engine.plan)

    def test_new_or_modified_files_invalidate_plan(self):
        original = self.write('a.txt')
        plan = self.engine.analyze()
        self.write('b.txt')
        with self.assertRaisesRegex(ValueError, '바뀌었습니다'):
            self.engine.apply(plan['id'])
        self.assertTrue(original.exists())
        plan = self.engine.analyze()
        original.write_text('new content')
        with self.assertRaisesRegex(ValueError, '바뀌었습니다'):
            self.engine.apply(plan['id'])

    def test_second_copy_failure_rolls_back_first_move(self):
        self.write('a.txt', b'first')
        self.write('b.txt', b'second')
        plan = self.engine.analyze()
        copy = self.engine._copy_exclusive
        def fail_second(source, target, checksum, cancel=None):
            if source == self.root / 'b.txt':
                raise OSError('simulated disk failure')
            return copy(source, target, checksum, cancel)
        with patch.object(self.engine, '_copy_exclusive', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                self.engine.apply(plan['id'])
        self.assertEqual((self.root / 'a.txt').read_bytes(), b'first')
        self.assertEqual((self.root / 'b.txt').read_bytes(), b'second')
        self.assertFalse(self.engine.journal.exists())

    def test_cancel_after_first_move_restores_originals(self):
        self.write('a.txt')
        self.write('b.txt')
        plan = self.engine.analyze()
        cancel = threading.Event()
        with self.assertRaises(Cancelled):
            self.engine.apply(plan['id'], lambda *_: cancel.set(), cancel)
        self.assertTrue((self.root / 'a.txt').exists())
        self.assertTrue((self.root / 'b.txt').exists())
        self.assertFalse(self.engine.journal.exists())

    def test_cancel_analysis_creates_no_plan_or_moves(self):
        self.write('a.txt')
        cancel = threading.Event()
        def ai(*_):
            cancel.set()
            return response()
        self.engine.ai = ai
        with self.assertRaises(Cancelled):
            self.engine.analyze(cancel=cancel)
        self.assertIsNone(self.engine.plan)
        self.assertTrue((self.root / 'a.txt').exists())

    def test_changed_destination_blocks_entire_undo(self):
        self.write('a.txt', b'a')
        self.write('b.txt', b'b')
        self.apply()
        target = self.engine.output / '학습/b.txt'
        target.write_bytes(b'edited after organizing')
        with self.assertRaisesRegex(ValueError, '변경되었습니다'):
            self.engine.undo()
        self.assertTrue((self.engine.output / '학습/a.txt').exists())
        self.assertFalse((self.root / 'a.txt').exists())
        self.assertTrue(self.engine.journal.exists())

    def test_source_collision_during_undo_is_not_overwritten(self):
        self.write('a.txt', b'original')
        self.apply()
        self.write('a.txt', b'new file')
        with self.assertRaisesRegex(ValueError, '다른 파일'):
            self.engine.undo()
        self.assertEqual((self.root / 'a.txt').read_bytes(), b'new file')
        self.assertEqual((self.engine.output / '학습/a.txt').read_bytes(), b'original')

    def test_interrupted_copy_before_source_removal_can_be_undone(self):
        original = self.write('a.txt', b'original')
        target = self.write(OUTPUT_NAME + '/학습/a.txt', b'original')
        self.engine._write_journal({'version': 1, 'root': str(self.root), 'state': 'active', 'moves': [{'source': 'a.txt', 'target': '학습/a.txt', 'sha256': digest(original)}]})
        self.assertEqual(FolderOrganizer(self.root).undo(), 1)
        self.assertTrue(original.exists())
        self.assertFalse(target.exists())

    def test_target_name_race_does_not_remove_other_writers_file(self):
        self.write('a.txt', b'identical')
        plan = self.engine.analyze()
        copy = self.engine._copy_exclusive
        def race(source, target, checksum, cancel=None):
            target.write_bytes(b'identical')
            return copy(source, target, checksum, cancel)
        with patch.object(self.engine, '_copy_exclusive', side_effect=race):
            with self.assertRaises(FileExistsError):
                self.engine.apply(plan['id'])
        self.assertEqual((self.engine.output / '학습/a.txt').read_bytes(), b'identical')
        self.assertTrue((self.root / 'a.txt').exists())

    @unittest.skipIf(os.name == 'nt', 'Symlinks require Windows privileges')
    def test_symlinks_skipped_and_output_link_rejected(self):
        self.write('nested/real.txt')
        (self.root / 'link.txt').symlink_to(self.root / 'nested/real.txt')
        (self.root / 'linked-dir').symlink_to(self.root / 'nested', target_is_directory=True)
        self.assertEqual(len(self.engine.scan()), 1)
        self.assertEqual(len(self.engine.skipped), 2)
        self.engine.output.symlink_to(self.root / 'nested', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '링크'):
            self.engine.analyze()
        self.assertTrue((self.root / 'nested/real.txt').exists())

    def test_tampered_journal_cannot_restore_outside_source_folder(self):
        self.write('a.txt')
        self.apply()
        journal = json.loads(self.engine.journal.read_text())
        journal['moves'][0]['source'] = '../outside.txt'
        self.engine._write_journal(journal)
        with self.assertRaisesRegex(ValueError, '허용 범위'):
            self.engine.undo()
        self.assertTrue((self.engine.output / '학습/a.txt').exists())

    def test_failed_later_run_preserves_previous_undo(self):
        self.write('first.txt')
        self.apply()
        previous = self.engine.journal.read_bytes()
        self.write('second.txt')
        plan = self.engine.analyze()
        with patch.object(self.engine, '_copy_exclusive', side_effect=OSError('no space')):
            with self.assertRaises(OSError):
                self.engine.apply(plan['id'])
        self.assertEqual(self.engine.journal.read_bytes(), previous)
        self.engine.undo()
        self.assertTrue((self.root / 'first.txt').exists())


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_text_excerpt_and_names_only_option(self):
        path = self.root / 'notes.txt'
        # The bounded byte read ends in the middle of a UTF-8 character.
        path.write_text('공부' * 30000, encoding='utf-8')
        content, scope = evidence(path)
        self.assertEqual(len(content[0]['text']), 12000)
        self.assertIn('앞부분', scope)
        self.assertEqual(evidence(path, False), ([], '파일명만 분석'))

    def test_docx_text_extraction(self):
        path = self.root / 'report.docx'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="urn:test"><w:t>월간 업무 보고서</w:t></w:document>')
        content, scope = evidence(path)
        self.assertEqual(content[0]['text'], '월간 업무 보고서')
        self.assertIn('DOCX', scope)

    def test_unsupported_and_invalid_documents_are_explicit(self):
        for name in ('audio.mp3', 'broken.docx', 'wrong.png'):
            path = self.root / name
            path.write_bytes(b'not a valid document')
            content, scope = evidence(path)
            self.assertEqual(content, [])
            self.assertIn('파일명만', scope)

    def test_image_payload_is_forwarded(self):
        path = self.root / 'pixel.png'
        # Real one-pixel PNG; no external service is called.
        path.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXZkAAAAASUVORK5CYII='))
        content, scope = evidence(path)
        self.assertEqual(scope, '이미지 분석')
        self.assertTrue(content[0]['image_url'].startswith('data:image/png;base64,'))

    def test_blank_pdf_has_explicit_fallback(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest('pypdf is optional')
        path = self.root / 'blank.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.write(path)
        content, scope = evidence(path)
        self.assertEqual(content, [])
        self.assertIn('텍스트 없음', scope)


if __name__ == '__main__':
    unittest.main()
