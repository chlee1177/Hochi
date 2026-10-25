import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'file-organizer'))
from folder_organizer import FolderOrganizer, OUTPUT_NAME
from classification import folder_path, name_component


def reply(folder=None, summary='클라우드 프로젝트 회의에서 배포 일정을 논의했다.', tags=None, confidence=0.95):
    return json.dumps({'folder': folder or ['업무', '프로젝트'], 'reason': '프로젝트 회의 자료',
                       'summary': summary, 'tags': tags or ['클라우드', '회의', '배포'], 'confidence': confidence}, ensure_ascii=False)


class OrganizerV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ai = Mock(return_value=reply())
        self.engine = FolderOrganizer(self.root, ai=self.ai)

    def write(self, name, text='클라우드 프로젝트 회의 자료'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_sensitive_filename_never_reaches_ai_or_auto_move(self):
        source = self.write('주민등록등본.txt')
        plan = self.engine.analyze()
        self.ai.assert_not_called()
        item = plan['items'][0]
        self.assertTrue(item['sensitive'])
        self.assertFalse(item['selected'])
        self.assertEqual(self.engine.apply(plan['id'])['moves'], [])
        self.assertTrue(source.exists())

    def test_sensitive_text_is_screened_before_ai(self):
        source = self.write('notes.txt', '담당자 연락처 person@example.com')
        plan = self.engine.analyze()
        self.ai.assert_not_called()
        self.assertTrue(plan['items'][0]['review_required'])
        self.assertNotIn('person@example.com', self.engine._catalog().path.read_bytes().decode('utf-8', errors='ignore'))
        self.assertTrue(source.exists())

    def test_auth_file_and_custom_keyword_are_held(self):
        self.write('.env', 'API_KEY=placeholder')
        self.write('acme/notes.txt')
        self.engine.sensitive_terms = ('acme',)
        plan = self.engine.analyze()
        self.ai.assert_not_called()
        self.assertTrue(all(item['sensitive'] for item in plan['items']))

    def test_images_wait_for_separate_external_permission(self):
        path = self.root / 'picture.png'
        path.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXZkAAAAASUVORK5CYII='))
        self.engine.analyze()
        self.ai.assert_not_called()
        with self.assertRaises(ValueError):
            self.engine.analyze_reviewed('picture.png')
        item = self.engine.analyze_reviewed('picture.png', allow_external=True)
        self.ai.assert_called_once()
        self.assertTrue(any(part['type'] == 'input_image' for part in self.ai.call_args.args[0]))
        self.assertFalse(item['selected'])
        self.assertFalse(item['approved_move'])

    def test_sensitive_manual_move_does_not_authorize_ai(self):
        original = self.write('계약서.txt')
        self.engine.analyze()
        with self.assertRaisesRegex(ValueError, '승인'):
            self.engine.edit_item('계약서.txt', '개인/계약', '보관문서.txt', True)
        self.engine.edit_item('계약서.txt', '개인/계약', '보관문서.txt', True, approve_review=True)
        self.engine.apply(self.engine.plan['id'])
        self.ai.assert_not_called()
        self.assertFalse(original.exists())
        target = self.engine.output / '개인/계약/보관문서.txt'
        self.assertTrue(target.exists())
        self.engine.undo()
        self.assertTrue(original.exists())

    def test_low_confidence_stays_for_review(self):
        self.write('ambiguous.txt')
        self.ai.return_value = reply(confidence=0.3)
        plan = self.engine.analyze()
        self.assertTrue(plan['items'][0]['review_required'])
        self.assertFalse(plan['items'][0]['selected'])
        self.assertEqual(self.engine.apply(plan['id'])['moves'], [])

    def test_arbitrary_valid_hierarchy_not_bound_to_slide_examples(self):
        self.write('notes.txt')
        self.ai.return_value = reply(['연구', '천문학', '관측'])
        plan = self.engine.analyze()
        self.engine.apply(plan['id'])
        self.assertTrue((self.engine.output / '연구/천문학/관측/notes.txt').exists())

    def test_user_selects_subset_and_renames_file(self):
        self.write('a.txt')
        self.write('b.txt')
        self.engine.analyze()
        self.engine.edit_item('a.txt', '학교/프로젝트', '정리한노트.txt', True)
        self.engine.edit_item('b.txt', '업무', 'b.txt', False)
        self.engine.apply(self.engine.plan['id'])
        self.assertTrue((self.engine.output / '학교/프로젝트/정리한노트.txt').exists())
        self.assertTrue((self.root / 'b.txt').exists())
        self.assertEqual(len(self.engine.plan['items']), 1)
        self.engine.undo()
        self.assertTrue((self.root / 'a.txt').exists())

    def test_auto_move_keeps_review_items_available(self):
        self.write('meeting.txt')
        self.write('급여명세.txt')
        plan = self.engine.analyze()
        result = self.engine.apply(plan['id'])
        self.assertEqual(len(result['moves']), 1)
        self.assertEqual(result['held'], 1)
        self.assertEqual(self.engine.plan['items'][0]['relative'], '급여명세.txt')

    def test_summary_tags_and_search_survive_restart_move_and_undo(self):
        self.write('notes.txt')
        plan = self.engine.analyze()
        before = FolderOrganizer(self.root).search('클라우드 회의 자료 찾아줘')
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]['tags'], ['클라우드', '회의', '배포'])
        self.engine.apply(plan['id'])
        moved = FolderOrganizer(self.root).search('클라우드 회의')
        self.assertEqual(moved[0]['current_path'], str(Path(OUTPUT_NAME) / '업무/프로젝트/notes.txt'))
        FolderOrganizer(self.root).undo()
        restored = FolderOrganizer(self.root).search('클라우드')
        self.assertEqual(restored[0]['current_path'], 'notes.txt')

    def test_unrelated_search_does_not_return_all_files(self):
        self.write('notes.txt')
        self.engine.analyze()
        self.assertEqual(self.engine.search('바이올린 연주'), [])

    def test_missing_or_changed_files_not_returned_with_stale_summary(self):
        source = self.write('notes.txt')
        self.engine.analyze()
        source.write_text('Changed and longer document')
        self.assertEqual(self.engine.search('클라우드'), [])
        source.unlink()
        self.assertEqual(self.engine.search('클라우드'), [])

    def test_catalog_failure_rolls_back_files_and_metadata(self):
        source = self.write('notes.txt')
        plan = self.engine.analyze()
        catalog = self.engine._catalog()
        actual_upsert = catalog.upsert
        def fail_once(records, event=None):
            if records and records[0]['status'] == 'moved':
                raise OSError('simulated index failure')
            actual_upsert(records, event=event)
        with patch.object(self.engine, '_catalog', return_value=catalog), patch.object(catalog, 'upsert', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'index failure'):
                self.engine.apply(plan['id'])
        self.assertTrue(source.exists())
        self.assertEqual(self.engine.search('클라우드')[0]['current_path'], 'notes.txt')

    def test_duplicate_detection_uses_bytes_and_never_deletes(self):
        self.write('a.txt', 'same')
        self.write('b.txt', 'same')
        self.write('c.txt', 'different')
        self.write(OUTPUT_NAME + '/업무/sub/old.txt', 'same')
        groups = self.engine.duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]['files']), 3)
        self.assertTrue((self.root / 'a.txt').exists())
        self.ai.assert_not_called()

    def test_similar_docs_use_summary_tags_but_exclude_identical_files(self):
        self.write('a.txt', 'first project notes')
        self.write('b.txt', 'second project notes')
        self.write('c.txt', 'unrelated recipe')
        self.ai.side_effect = [reply(), reply(summary='클라우드 프로젝트 회의의 배포 일정 정리'), reply(['개인', '요리'], summary='파스타 조리 방법', tags=['파스타', '요리'])]
        self.engine.analyze()
        pairs = self.engine.similar()
        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0]['first'], pairs[0]['second']}, {'a.txt', 'b.txt'})

    def test_invalid_path_and_metadata_cannot_reach_filesystem(self):
        for path in ('../outside', '/tmp/outside', 'A/../../B', 'CON', 'x/y/z/w', 'x\\y', 'x/.hidden'):
            with self.assertRaises(ValueError, msg=path):
                folder_path(path)
        for name in ('../file.txt', 'NUL.txt', 'x:stream', 'name.', 'a/b.txt'):
            with self.assertRaises(ValueError, msg=name):
                name_component(name)
        self.write('a.txt')
        self.ai.return_value = json.dumps({'folder': ['업무'], 'reason': 'ok', 'tags': 'not-a-list'})
        with self.assertRaises(ValueError):
            self.engine.analyze()

    def test_same_stat_content_change_is_rejected_before_move(self):
        source = self.write('a.txt', 'first')
        plan = self.engine.analyze()
        original = source.stat()
        source.write_text('other')
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, '내용이 바뀌었습니다'):
            self.engine.apply(plan['id'])
        self.assertEqual(source.read_text(), 'other')

    def test_reanalysis_replaces_index_without_losing_identical_organized_file(self):
        self.write('a.txt', 'same')
        self.engine.analyze()
        self.engine.analyze()
        self.assertEqual(len(self.engine.search()), 1)
        self.engine.apply(self.engine.plan['id'])
        self.write('a.txt', 'same')
        self.engine.analyze()
        self.assertEqual(len(self.engine.search()), 2)

    def test_action_history_survives_restart(self):
        self.write('a.txt')
        self.engine.analyze()
        self.engine.edit_item('a.txt', '업무/회의', '회의록.txt', True)
        self.engine.apply(self.engine.plan['id'])
        self.engine.undo()
        kinds = [event['kind'] for event in FolderOrganizer(self.root).history()]
        self.assertEqual(kinds, ['되돌리기', '이동', '분류 수정', '분석'])

    def test_missing_ai_confidence_does_not_implicitly_approve_moving(self):
        self.write('a.txt')
        self.ai.return_value = json.dumps({'category': '업무', 'reason': '문서'})
        plan = self.engine.analyze()
        self.assertTrue(plan['items'][0]['review_required'])
        self.assertEqual(self.engine.apply(plan['id'])['moves'], [])

    def test_regular_hidden_filename_can_be_organized(self):
        self.write('.gitignore', '*.pyc')
        self.engine.analyze()
        self.engine.apply(self.engine.plan['id'])
        self.assertTrue((self.engine.output / '업무/프로젝트/.gitignore').exists())
        self.engine.undo()
        self.assertTrue((self.root / '.gitignore').exists())


if __name__ == '__main__':
    unittest.main()
