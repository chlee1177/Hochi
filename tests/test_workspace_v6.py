import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'file-organizer'))
from folder_organizer import Cancelled, FolderOrganizer
from project import load_project, save_project
from versions import VersionMonitor


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        self.output = self.base / 'another-disk' / 'archive'
        self.ai = Mock(return_value=json.dumps({'folder': ['대학교', '과목명'], 'reason': '수업 자료',
                       'summary': '물리학 수업 내용', 'tags': ['물리학'], 'confidence': .95}, ensure_ascii=False))
        self.engine = FolderOrganizer(self.source, output=self.output, ai=self.ai)
        self.now = 1000000.
        self.monitor = VersionMonitor(self.engine, quiet_days=2, clock=lambda: self.now)

    def write(self, name, content='physics notes'):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def files(self):
        a = self.write('보고서_최종.txt', 'first physics draft')
        b = self.write('보고서_최최종.txt', 'second physics draft')
        self.monitor.refresh()
        return a, b

    def test_destination_move_restart_search_duplicates_undo(self):
        a = self.write('a.txt')
        self.write('b.txt')
        save_project(self.engine, 2)
        plan = self.engine.analyze()
        self.engine.edit_item('a.txt', r'수정한내용\수정한내용', 'a.txt', True)
        self.engine.edit_item('b.txt', '대학교/과목명', 'b.txt', False)
        self.engine.apply(self.engine.plan['id'])
        target = self.output / '수정한내용/수정한내용/a.txt'
        self.assertTrue(target.exists())
        self.assertFalse(a.exists())
        restarted = FolderOrganizer(self.source)
        self.assertEqual(restarted.output, self.output)
        self.assertEqual(len(restarted.search('물리학')), 2)
        self.assertEqual(len(restarted.duplicates()), 1)
        restarted.undo()
        self.assertTrue(a.exists())
        self.assertFalse(target.exists())
        self.assertEqual(load_project(self.source)['quiet_days'], 2)
        self.assertEqual({r['relative'] for r in restarted.scan()}, {'a.txt', 'b.txt'})

    def test_destination_rejects_ancestor_links_and_other_project(self):
        for target in (self.source, self.base, self.source / '..' / 'escape'):
            with self.assertRaises(ValueError):
                FolderOrganizer(self.source, output=target)
        alias = self.base / 'alias'
        alias.symlink_to(self.output.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            FolderOrganizer(self.source, output=alias / 'archive')
        save_project(self.engine, 2)
        other = self.base / 'other'
        other.mkdir()
        with self.assertRaisesRegex(ValueError, '다른 작업'):
            FolderOrganizer(other, output=self.output)

    def test_destination_external_copy_failure_rolls_back(self):
        a = self.write('a.txt')
        b = self.write('b.txt')
        plan = self.engine.analyze()
        original = self.engine._copy_exclusive
        calls = 0
        def copy(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('disk full')
            return original(*args)
        with patch.object(self.engine, '_copy_exclusive', side_effect=copy):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.engine.apply(plan['id'])
        self.assertTrue(a.exists() and b.exists())
        self.assertEqual(len(self.engine.search('물리학')), 2)

    def test_rules_persist_and_do_not_bypass_review(self):
        self.write('a.txt')
        self.write('계약서.txt')
        self.engine.save_rule(r'대학교\과목명', r'수정한내용\수정한내용')
        restarted = FolderOrganizer(self.source, output=self.output, ai=self.ai)
        items = {r['relative']: r for r in restarted.analyze()['items']}
        self.assertEqual(items['a.txt']['folder'], '수정한내용/수정한내용')
        self.assertEqual(items['a.txt']['ai_folder'], '대학교/과목명')
        self.assertFalse(items['계약서.txt']['selected'])
        self.assertEqual(self.ai.call_count, 1)
        restarted.save_rule('대학교/과목명', None)
        self.assertEqual(restarted.rules(), {})

    def test_rule_validation_does_not_change_existing_rules(self):
        self.engine.save_rule('대학교/과목명', '학습/물리')
        for value in ('../escape', r'C:\escape', '/absolute', r'one\..\escape', 'A/B/C/D'):
            with self.assertRaises(ValueError):
                self.engine.save_rule('대학교/과목명', value)
        self.assertEqual(self.engine.rules(), {'대학교/과목명': '학습/물리'})

    def test_observation_age_not_old_creation_time(self):
        a = self.write('보고서.txt')
        os.utime(a, (1, 1))
        row = self.monitor.refresh()[0]
        self.assertEqual(row['version_state'], '최근 수정본')
        self.now += 2 * 86400
        self.assertEqual(self.monitor.refresh()[0]['version_state'], '최종본 후보')
        self.assertNotIn('확정 최종본', a.name)
        self.ai.assert_not_called()

    def test_names_are_only_suggestions_and_group_is_explicit(self):
        a, b = self.files()
        rows = self.monitor.rows()
        self.assertEqual(rows[0]['suggestion'], rows[1]['suggestion'])
        self.assertNotEqual(rows[0]['group'], rows[1]['group'])
        self.monitor.group([str(a), str(b)], '수업 보고서')
        self.assertEqual(len({r['group'] for r in self.monitor.rows()}), 1)

    def test_user_can_confirm_older_file_and_search_includes_previous_option(self):
        a, b = self.files()
        self.engine.analyze()
        self.monitor.group([str(a), str(b)], '보고서')
        self.monitor.confirm(str(a))
        results = self.engine.search('물리학')
        self.assertEqual([r['current_path'] for r in results], [a.name])
        self.assertIn('확정 최종본', results[0]['tags'])
        self.assertEqual(len(self.engine.search('물리학', include_previous=True)), 2)
        self.assertEqual(VersionMonitor(self.engine).rows()[0]['group_name'], '보고서')
        self.monitor.release([str(a)])
        self.assertEqual(len(self.engine.search('물리학')), 2)

    def test_modified_final_loses_confirmation_and_stale_summary(self):
        a, b = self.files()
        self.engine.analyze()
        self.monitor.group([str(a), str(b)], '보고서')
        self.monitor.confirm(str(a))
        self.now += 10
        a.write_text('unrelated replacement', encoding='utf-8')
        self.assertEqual(len(self.engine.search('물리학')), 1)  # only b's still valid summary
        rows = self.monitor.refresh()
        self.assertFalse(any(r['version_state'] == '확정 최종본' for r in rows))
        self.assertTrue(all(r['warning'] for r in rows))
        self.assertTrue(a.exists() and b.exists())

    def test_other_version_change_warns_and_prevents_silent_search_hiding(self):
        a, b = self.files()
        self.monitor.group([str(a), str(b)], '보고서')
        self.monitor.confirm(str(a))
        self.now += 10
        b.write_text('new content')
        rows = self.monitor.refresh()
        self.assertTrue(all(r['warning'] for r in rows))
        self.assertEqual(len(self.engine.search()), 2)
        self.monitor.confirm(str(a))
        self.assertEqual(len(self.engine.search()), 1)

    def test_same_size_same_mtime_change_detected(self):
        a = self.write('보고서.txt', 'first')
        self.monitor.refresh()
        self.engine.analyze()
        self.monitor.confirm(str(a))
        stat = a.stat()
        a.write_text('other')
        os.utime(a, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.now += 5
        self.assertEqual(self.engine.search('물리학'), [])
        self.assertNotEqual(self.monitor.refresh()[0]['version_state'], '확정 최종본')

    def test_rename_preserves_identity_and_final(self):
        a = self.write('보고서.txt')
        before = self.monitor.refresh()[0]
        self.monitor.confirm(str(a))
        b = a.rename(self.source / '제출.txt')
        rows = self.monitor.refresh()
        self.assertEqual(rows[0]['path'], str(b))
        self.assertEqual(rows[0]['id'], before['id'])
        self.assertEqual(rows[0]['version_state'], '확정 최종본')

    def test_copy_does_not_inherit_final(self):
        a = self.write('보고서.txt')
        self.monitor.refresh()
        self.monitor.confirm(str(a))
        b = self.write('사본.txt', a.read_text())
        rows = {r['path']: r for r in self.monitor.refresh()}
        self.assertNotEqual(rows[str(a)]['id'], rows[str(b)]['id'])
        self.assertNotEqual(rows[str(b)]['version_state'], '확정 최종본')

    def test_organized_move_and_undo_preserve_version_identity(self):
        a = self.write('보고서.txt')
        original = self.monitor.refresh()[0]['id']
        self.monitor.confirm(str(a))
        plan = self.engine.analyze()
        self.engine.apply(plan['id'])
        moved = self.monitor.refresh()[0]
        self.assertEqual(moved['id'], original)
        self.assertEqual(moved['version_state'], '확정 최종본')
        self.engine.undo()
        self.assertEqual(self.monitor.refresh()[0]['id'], original)

    def test_deleted_final_warns_remaining_versions(self):
        a, b = self.files()
        self.monitor.group([str(a), str(b)], '보고서')
        self.monitor.confirm(str(a))
        a.unlink()
        self.now += 10
        rows = self.monitor.refresh()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['warning'])
        self.assertEqual(len(self.engine.search()), 1)

    def test_ungroup_resets_final_without_deleting_files(self):
        a, b = self.files()
        self.monitor.group([str(a), str(b)], '보고서')
        self.monitor.confirm(str(a))
        rows = self.monitor.release([str(b)], ungroup=True)
        self.assertEqual(len({r['group'] for r in rows}), 2)
        self.assertFalse(any(r['version_state'] == '확정 최종본' for r in rows))
        self.assertTrue(a.exists() and b.exists())

    def test_missing_stale_or_single_selection_cannot_confirm_or_group(self):
        a, b = self.files()
        with self.assertRaises(ValueError):
            self.monitor.group([str(a)], 'bad')
        a.write_text('changed')
        with self.assertRaises(ValueError):
            self.monitor.confirm(str(a))
        b.unlink()
        with self.assertRaises(ValueError):
            self.monitor.confirm(str(b))

    def test_cancel_and_scan_error_keep_last_observation(self):
        self.files()
        before = self.monitor.path.read_bytes()
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            self.monitor.refresh(event)
        self.assertEqual(before, self.monitor.path.read_bytes())
        with patch.object(self.monitor, 'paths', side_effect=PermissionError('disk unavailable')):
            with self.assertRaises(PermissionError):
                self.monitor.refresh()
        self.assertEqual(before, self.monitor.path.read_bytes())

    def test_monitor_excludes_links_and_temporary_internal_files(self):
        self.write('real.txt')
        outside = self.base / 'outside.txt'
        outside.write_text('outside')
        (self.source / 'linked.txt').symlink_to(outside)
        self.write('~$editing.docx')
        self.write('download.part')
        save_project(self.engine, 2)
        rows = self.monitor.refresh()
        self.assertEqual([Path(r['path']).name for r in rows], ['real.txt'])
        self.ai.assert_not_called()

    def test_legacy_index_cannot_be_adopted_by_another_source(self):
        self.output.mkdir(parents=True)
        (self.output / '.hochi-index.sqlite3').write_bytes(b'old index')
        with self.assertRaisesRegex(ValueError, '기존 정리 기록'):
            FolderOrganizer(self.source, output=self.output)

    def test_summary_similarity_suggests_but_does_not_merge(self):
        self.write('강의.txt', 'first')
        self.write('다른이름.txt', 'second')
        self.engine.analyze()
        rows = self.monitor.refresh()
        self.assertTrue(all('요약·태그 유사 후보' in r.get('related', '') for r in rows))
        self.assertEqual(len({r['group'] for r in rows}), 2)

    def test_quiet_period_resets_when_any_group_member_changes(self):
        a, b = self.files()
        self.monitor.group([str(a), str(b)], '보고서')
        self.now += 2 * 86400
        self.assertEqual(sum(r['version_state'] == '최종본 후보' for r in self.monitor.refresh()), 1)
        a.write_text('revised original')
        self.now += 1
        self.assertFalse(any(r['version_state'] == '최종본 후보' for r in self.monitor.refresh()))

    def test_file_changed_during_read_waits_for_next_poll(self):
        a = self.write('보고서.txt')
        before = self.monitor.refresh()[0]
        from folder_organizer import snapshot
        calls = 0
        def unstable(path):
            nonlocal calls
            calls += 1
            value = list(snapshot(path))
            if calls == 2:
                value[0] += 1
            return value
        with patch('versions.snapshot', side_effect=unstable):
            rows = self.monitor.refresh()
        self.assertEqual(rows[0]['id'], before['id'])
        self.assertEqual(rows[0]['sha256'], before['sha256'])
        self.assertTrue(a.exists())

    def test_new_ungrouped_version_warns_confirmed_group_without_auto_merge(self):
        a, b = self.files()
        self.monitor.group([str(a), str(b)], '보고서')
        self.monitor.confirm(str(a))
        self.now += 10
        c = self.write('보고서_최최최종.txt', 'third version')
        rows = {r['path']: r for r in self.monitor.refresh()}
        self.assertIn('새 버전 후보', rows[str(a)]['warning'])
        self.assertNotEqual(rows[str(a)]['group'], rows[str(c)]['group'])
        self.assertEqual(len(self.engine.search()), 3)
        self.monitor.group([str(a), str(b), str(c)], '보고서')
        self.monitor.confirm(str(c))
        self.assertEqual([r['current_path'] for r in self.engine.search()], [c.name])


if __name__ == '__main__':
    unittest.main()
