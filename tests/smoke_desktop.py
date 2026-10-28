"""Real GUI interactions with synthetic local files and a mocked AI response."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'file-organizer'))
from app import App
from folder_organizer import OUTPUT_NAME
from test_local_ai import fake_ollama


def wait(root, app):
    deadline = time.monotonic() + 20
    while app.busy:
        root.update()
        if time.monotonic() > deadline:
            raise RuntimeError('Desktop operation timed out')
        time.sleep(0.02)
    root.update()
    if app.status.get().startswith('작업 실패'):
        raise RuntimeError(app.status.get())


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def capture(root, name):
    destination = os.environ.get('HOCHI_SCREENSHOT')
    if destination:
        from PIL import ImageGrab
        root.update()
        path = Path(destination)
        if name:
            path = path.with_name(path.stem + '-' + name + path.suffix)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(path)


with tempfile.TemporaryDirectory() as directory:
    root = tk.Tk()
    app = App(root)
    app.provider.set('openai')
    root.update()
    assert app.tabs.index(app.tabs.select()) == 4
    assert app.primary_button.instate(['disabled'])
    assert not app.detail_actions.winfo_ismapped()
    assert not app.cancel_button.winfo_ismapped()
    capture(root, 'empty')
    # Settings use drafts: cancelling must not change live options or discard a plan.
    app.open_settings()
    root.update()
    settings = app.settings_dialog
    settings_controls = list(widgets(settings))
    next(w for w in settings_controls if isinstance(w, ttk.Checkbutton)).invoke()
    next(w for w in settings_controls if isinstance(w, ttk.Button) and w.cget('text') == '취소').invoke()
    assert app.recursive.get()
    folder = Path(directory)
    (folder / '수업').mkdir()
    source = folder / '수업' / '강의노트.txt'
    source.write_text('이번 주 물리학 강의와 과제 정리', encoding='utf-8')
    duplicate = folder / '추가노트.txt'
    duplicate.write_bytes(source.read_bytes())
    sensitive = folder / '계약서.txt'
    sensitive.write_text('민감 문서 예시 내용', encoding='utf-8')
    email = folder / '연락메모.txt'
    email.write_text('연락 담당 person@example.com', encoding='utf-8')
    relative = str(source.relative_to(folder))
    app.folder.set(str(folder))
    app.key.set('mock-only-not-a-real-key')
    fake_ai = json.dumps({'folder': ['학습', '물리학'], 'reason': '물리학 강의 및 과제 내용',
                          'summary': '물리학 수업과 과제에 관한 노트다.', 'tags': ['물리학', '수업', '과제'], 'confidence': 0.96}, ensure_ascii=False)
    with patch.dict(os.environ), patch('folder_organizer.ai_text', return_value=fake_ai) as ai, patch('app.messagebox.askyesno', return_value=True), patch('app.messagebox.showerror') as errors:
        app.primary_button.invoke()
        assert app.primary_button.instate(['disabled'])
        wait(root, app)
        assert ai.call_count == 2, 'Sensitive files must never be sent automatically'
        assert source.exists() and sensitive.exists()
        assert len(app.table.get_children()) == 4
        assert [v.get() for v in app.metrics] == ['4', '2', '2', '0']
        assert app.primary_button.cget('text') == '2개 파일 이동'
        app.table.selection_set(app.rows[relative])
        root.update()
        assert not app.external_button.winfo_ismapped(), 'Only review files need an AI override'
        capture(root, 'proposals')
        # A key-only change keeps the reviewed plan intact.
        plan_id = app.engine.plan['id']
        app.open_settings()
        root.update()
        capture(root, 'settings')
        settings_controls = list(widgets(app.settings_dialog))
        key_entry = next(w for w in settings_controls if isinstance(w, ttk.Entry))
        key_entry.delete(0, 'end')
        key_entry.insert(0, 'mock-second-key')
        next(w for w in settings_controls if isinstance(w, ttk.Button) and w.cget('text') == '저장').invoke()
        assert app.engine.plan['id'] == plan_id
        app.table.selection_set((app.rows[relative], app.rows['추가노트.txt']))
        root.update()
        assert app.toggle_button.winfo_ismapped()
        assert not app.edit_button.winfo_ismapped()
        app.toggle_button.invoke()
        assert app.metrics[1].get() == '0'
        app.toggle_button.invoke()
        assert app.metrics[1].get() == '2'
        app.filter.set('검토 대기')
        app.render()
        assert len(app.table.get_children()) == 2
        app.filter.set('전체')
        app.render()
        app.table.selection_set(app.rows['계약서.txt'])
        app.edit_selected()
        root.update()
        dialog = next(child for child in root.winfo_children() if isinstance(child, tk.Toplevel))
        controls = list(widgets(dialog))
        entries = [child for child in controls if isinstance(child, ttk.Entry)]
        entries[0].delete(0, 'end')
        entries[0].insert(0, '개인/검토완료')
        entries[1].delete(0, 'end')
        entries[1].insert(0, '확인한문서.txt')
        for control in controls:
            if isinstance(control, ttk.Checkbutton):
                control.invoke()
        next(child for child in controls if isinstance(child, ttk.Button) and child.cget('text') == '수정 저장').invoke()
        root.update()
        assert app.plan_item('계약서.txt')['approved_move']
        assert app.plan_item('계약서.txt')['selected']
        app.table.selection_set(app.rows['추가노트.txt'])
        app.toggle_selected()
        assert not app.plan_item('추가노트.txt')['selected']
        app.primary_button.invoke()
        wait(root, app)
        target = folder / OUTPUT_NAME / '학습/물리학' / source.name
        sensitive_target = folder / OUTPUT_NAME / '개인/검토완료/확인한문서.txt'
        assert target.exists() and not source.exists()
        assert sensitive_target.exists() and not sensitive.exists()
        assert email.exists() and duplicate.exists()
        assert ai.call_count == 2, 'Local move approval must not authorize AI transmission'
        app.nav_buttons[1].invoke()
        app.query.set('물리학 수업 자료 찾아줘')
        app.search_button.invoke()
        wait(root, app)
        assert len(app.library.get_children()) == 2
        capture(root, 'search')
        app.library_mode.set('중복 파일')
        app.library_mode_changed()
        assert app.search_entry.instate(['disabled'])
        app.search_button.invoke()
        wait(root, app)
        assert len(app.library.get_children()) == 2
        assert app.search_entry.instate(['disabled'])
        app.library_mode.set('유사 문서')
        app.library_mode_changed()
        app.search_button.invoke()
        wait(root, app)
        assert '유사 문서' in app.status.get()
        app.library_mode.set('파일 검색')
        app.library_mode_changed()
        assert not app.search_entry.instate(['disabled'])
        app.nav_buttons[2].invoke()
        wait(root, app)
        assert len(app.history_table.get_children()) >= 4
        capture(root, 'history')
        root.nametowidget(str(app.more_button['menu'])).invoke(0)
        wait(root, app)
        assert source.exists() and sensitive.exists()
        app.nav_buttons[0].invoke()
        app.primary_button.invoke()
        wait(root, app)
        assert source.exists(), 'Primary analysis must never automatically move originals'
        app.primary_button.invoke()
        wait(root, app)
        assert target.exists() and not source.exists()
        assert sensitive.exists() and email.exists()
        assert len(app.engine.plan['items']) == 2
        assert '이동 완료' in app.status.get()
        app.table.selection_set(app.rows['계약서.txt'])
        app.show_details()
        capture(root, '')
        root.geometry('1100x760')
        root.update()
        for widget in (app.primary_button, app.settings_button, app.table, app.details, app.status_label):
            assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
            assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        assert app.details.winfo_height() >= 70, 'Review explanation must remain readable at minimum size'
        capture(root, 'compact')
        assert app.external_button.winfo_ismapped()
        previous_calls = ai.call_count
        app.table.selection_set(app.rows['연락메모.txt'])
        app.external_button.invoke()
        wait(root, app)
        assert ai.call_count == previous_calls + 1
        assert not app.plan_item('연락메모.txt')['selected']
        app.undo()
        wait(root, app)
        assert source.exists() and duplicate.exists() and sensitive.exists() and email.exists()
        errors.assert_not_called()
    # Use the real HTTP adapter with a fake local Ollama server, never the cloud API.
    with (fake_ollama() as server, patch('runtime.urlopen', side_effect=AssertionError('Cloud fallback')),
          patch('app.messagebox.askyesno', return_value=True) as confirmations, patch('app.messagebox.showerror') as errors):
        app.key.set('')
        app.open_settings()
        root.update()
        controls = list(widgets(app.settings_dialog))
        provider = next(w for w in controls if isinstance(w, ttk.Combobox))
        provider.set('Ollama · 내 PC')
        provider.event_generate('<<ComboboxSelected>>')
        host = next(w for w in controls if isinstance(w, ttk.Entry) and w.get() == app.ollama_url.get())
        host.delete(0, 'end')
        host.insert(0, server['url'])
        next(w for w in controls if isinstance(w, ttk.Button) and w.cget('text') == '연결 확인').invoke()
        wait(root, app)
        assert '연결 확인' in app.status.get()
        assert all(r[0] == '/api/show' for r in server['requests'])
        capture(root, 'ollama-settings')
        next(w for w in controls if isinstance(w, ttk.Button) and w.cget('text') == '저장').invoke()
        assert app.provider.get() == 'ollama'
        assert app.engine is None, 'Provider switch must discard the previous plan'
        app.primary_button.invoke()
        wait(root, app)
        assert '내 PC의 Ollama' in confirmations.call_args.args[1]
        assert source.exists() and duplicate.exists()
        assert app.metrics[1].get() == '2'
        assert len([r for r in server['requests'] if r[0] == '/api/chat']) == 2
        app.table.selection_set(app.rows['연락메모.txt'])
        root.update()
        assert app.external_button.cget('text') == '이 파일의 로컬 분석 허용'
        app.external_button.invoke()
        wait(root, app)
        assert '내 PC의 Ollama' in confirmations.call_args.args[1]
        assert 'OpenAI' not in confirmations.call_args.args[1]
        assert not app.plan_item('연락메모.txt')['selected']
        capture(root, 'ollama')
        app.primary_button.invoke()
        wait(root, app)
        assert not source.exists() and sensitive.exists() and email.exists()
        app.undo()
        wait(root, app)
        assert source.exists() and duplicate.exists()
        errors.assert_not_called()
    print('PASS GUI: OpenAI regression; Ollama settings, local connection check, no-key HTTP analysis, provider invalidation, private-file approval, selected move and undo without cloud fallback (mock servers)')
    app.close()

# v6: independent output, reusable rules, local version review and search defaults.
with tempfile.TemporaryDirectory() as directory:
    root = tk.Tk()
    app = App(root)
    root.update()
    base = Path(directory)
    source = base / '작업'
    source.mkdir()
    output = base / '저장' / '자료'
    first = source / '보고서_최종.txt'
    second = source / '보고서_최최종.txt'
    first.write_text('물리학 보고서 초안', encoding='utf-8')
    second.write_text('물리학 보고서 수정안', encoding='utf-8')
    app.folder.set(str(source))
    app.provider.set('openai')
    app.key.set('mock-only')
    with (patch('folder_organizer.ai_text', return_value=fake_ai),
          patch('app.messagebox.askyesno', return_value=True),
          patch('app.messagebox.showerror') as errors):
        app.open_project_settings()
        root.update()
        assert app.tabs.index(app.tabs.select()) == 4
        assert root.grab_current() is None
        assert not app.settings_button.winfo_ismapped()
        app.project_output_draft.set(str(output))
        app.project_save_button.invoke()
        assert app.engine is None and not app.monitor_enabled.get()
        app.navigate(0)
        assert app.output_folder.get() == str(output)
        assert (source / '.hochi-project.json').exists()
        app.open_rules()
        root.update()
        dialog = root.grab_current()
        entries = [w for w in widgets(dialog) if isinstance(w, ttk.Entry)]
        entries[0].insert(0, r'학습\물리학')
        entries[1].insert(0, r'수정한내용\수정한내용')
        next(w for w in widgets(dialog) if isinstance(w, ttk.Button) and w.cget('text') == '규칙 저장').invoke()
        capture(root, 'rules')
        dialog.destroy()
        app.start(False)
        wait(root, app)
        assert all(i['folder'] == '수정한내용/수정한내용' for i in app.engine.plan['items'])
        app.table.selection_set(app.rows[first.name])
        app.edit_selected()
        root.update()
        dialog = root.grab_current()
        entries = [w for w in widgets(dialog) if isinstance(w, ttk.Entry)]
        entries[0].delete(0, 'end')
        entries[0].insert(0, '학교/내과목')
        next(w for w in widgets(dialog) if isinstance(w, ttk.Checkbutton) and '내 분류 규칙' in w.cget('text')).invoke()
        next(w for w in widgets(dialog) if isinstance(w, ttk.Button) and w.cget('text') == '수정 저장').invoke()
        assert app.engine.rules()['학습/물리학'] == '학교/내과목'
        app.navigate(3)
        app.monitor_enabled.set(True)
        app.toggle_monitor()
        wait(root, app)
        assert len(app.version_items) == 2
        app.version_table.selection_set(*app.version_table.get_children())
        with patch('project_ui.simpledialog.askstring', return_value='물리학 보고서'):
            app.version_action('group')
        wait(root, app)
        chosen = next(row for row, item in app.version_items.items() if item['path'] == str(first))
        app.version_table.selection_set(chosen)
        app.version_action('confirm')
        wait(root, app)
        assert any(i['version_state'] == '확정 최종본' for i in app.version_items.values())
        capture(root, 'versions')
        app.navigate(1)
        app.query.set('물리학')
        app.search()
        wait(root, app)
        assert len(app.library_items) == 1
        app.include_previous.set(True)
        app.search()
        wait(root, app)
        assert len(app.library_items) == 2
        newer = source / '보고서_최최최종.txt'
        newer.write_text('아직 묶지 않은 새 수정본', encoding='utf-8')
        app.navigate(3)
        app.refresh_versions()
        wait(root, app)
        assert any('새 버전 후보' in i['warning'] for i in app.version_items.values())
        capture(root, 'version-warning')
        newer.unlink()
        app.refresh_versions()
        wait(root, app)
        app.navigate(0)
        app.apply()
        wait(root, app)
        assert (output / '학교/내과목' / first.name).exists()
        assert (output / '수정한내용/수정한내용' / second.name).exists()
        app.navigate(3)
        app.refresh_versions()
        wait(root, app)
        assert any(i['version_state'] == '확정 최종본' for i in app.version_items.values())
        capture(root, 'versions-moved')
        app.undo()
        wait(root, app)
        assert first.exists() and second.exists()
        app.folder.set(str(base))
        assert not app.monitor_enabled.get()
        app.folder.set(str(source))
        assert app.output_folder.get() == str(output)
        errors.assert_not_called()
    app.close()
    print('PASS GUI v6: external destination persistence, slash/backslash rules, remembered edit, monitoring, explicit grouping/final, previous-version search, move/undo and source-switch reset')

# v6.2: an unsupported file must not discard the other files' analysis.
with tempfile.TemporaryDirectory() as directory:
    root = tk.Tk()
    app = App(root)
    root.update()
    folder = Path(directory)
    for name in ('a.txt', 'b.doc', 'c.docx', 'd.txt'):
        (folder / name).write_text('example', encoding='utf-8')
    app.folder.set(str(folder))
    app.provider.set('openai')
    app.key.set('mock-only')
    with (patch('folder_organizer.ai_text', return_value=fake_ai) as ai,
          patch('app.messagebox.askyesno', return_value=True),
          patch('app.messagebox.showerror') as errors):
        app.start(False)
        wait(root, app)
        assert ai.call_count == 2
        assert '건너뜀 2개' in app.status.get()
        assert len(app.view_items) == 4
        app.filter.set('건너뜀')
        app.render()
        assert len(app.table.get_children()) == 2
        app.table.selection_set(app.rows['b.doc'])
        app.show_details()
        detail = app.details.get('1.0', 'end')
        assert 'b.doc' in detail and 'Word 구형 문서' in detail and '내용 분석 불가' in detail
        assert not app.external_button.winfo_ismapped()
        with patch.object(app, 'open_path') as opened:
            app.open_selected_location()
            opened.assert_called_once_with(folder)
        capture(root, 'skipped')
        app.filter.set('전체')
        app.render()
        app.table.selection_set(app.rows['a.txt'])
        app.skip_selected()
        assert not app.plan_item('a.txt')['selected']
        assert app.plan_item('d.txt')['selected']
        app.apply()
        wait(root, app)
        assert (folder / 'a.txt').exists()
        assert (folder / 'b.doc').exists() and (folder / 'c.docx').exists()
        assert not (folder / 'd.txt').exists()
        app.undo()
        wait(root, app)
        assert (folder / 'd.txt').exists()
        errors.assert_not_called()
    app.close()
    print('PASS GUI v6.2: unsupported files continue, type/reason display, skipped filter, open location, manual skip, supported-only move and undo')

# v6.3: project setup is independent of AI and explicit monitoring actions.
with tempfile.TemporaryDirectory() as directory:
    root = tk.Tk()
    app = App(root)
    app.key.set('')
    app.provider.set('openai')
    root.update()
    base = Path(directory)
    source = base / '작업'
    source.mkdir()
    note = source / '강의노트.txt'
    note.write_text('물리학 수업', encoding='utf-8')
    output = base / '보관'
    with (patch('folder_organizer.ai_text', return_value=fake_ai) as ai,
          patch('local_ai.OllamaClient._request', side_effect=AssertionError('Settings must not call AI')),
          patch('app.messagebox.askyesno', return_value=True),
          patch('app.messagebox.showerror') as errors):
        app.nav_buttons[4].invoke()
        root.update()
        assert app.tabs.index(app.tabs.select()) == 4
        assert root.grab_current() is None
        assert not app.settings_button.winfo_ismapped()
        app.help_button.invoke()
        root.update()
        guide = app.help_dialog
        assert root.grab_current() == guide
        app.help_button.invoke()
        assert app.help_dialog == guide
        assert guide.winfo_height() < root.winfo_screenheight()
        capture(guide, 'usage-guide')
        next(w for w in widgets(guide) if isinstance(w, ttk.Button) and w.cget('text') == '닫기').invoke()
        root.update()
        assert root.grab_current() is None
        assert app.engine is None and not app.busy and not app.monitor_enabled.get()
        ai.assert_not_called()
        errors.assert_not_called()
        app.folder.set(str(source))
        app.project_output_draft.set(str(output))
        app.project_days_draft.set('3')
        app.project_save_button.invoke()
        assert app.output_folder.get() == str(output)
        assert app.quiet_days.get() == 3
        assert not app.busy and app.engine is None and not app.monitor_enabled.get()
        assert note.exists()
        ai.assert_not_called()
        capture(root, 'independent-settings')
        root.geometry('1100x800')
        root.update()
        assert app.project_save_button.winfo_rooty() + app.project_save_button.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        capture(root, 'settings-compact')
        app.project_output_draft.set(str(base / 'unsaved'))
        app.project_days_draft.set('20')
        app.reset_project_draft()
        assert app.project_output_draft.get() == str(output)
        assert app.project_days_draft.get() == '3'
        app.navigate(3)
        app.monitor_enabled.set(True)
        app.toggle_monitor()
        wait(root, app)
        ai.assert_not_called()
        assert app.monitor_enabled.get()
        app.monitor_enabled.set(False)
        app.toggle_monitor()
        app.navigate(0)
        root.update()
        assert app.settings_button.winfo_ismapped()
        app.key.set('mock-only')
        app.start(False)
        wait(root, app)
        plan_id = app.engine.plan['id']
        app.help_button.invoke()
        root.update()
        assert app.engine.plan['id'] == plan_id and note.exists()
        app.help_dialog.destroy()
        app.navigate(4)
        app.project_days_draft.set('5')
        app.project_save_button.invoke()
        assert app.engine.plan['id'] == plan_id, 'Changing quiet period must preserve the AI proposal'
        assert note.exists()
        app.project_save_button.invoke()
        assert app.engine.plan['id'] == plan_id, 'Saving unchanged settings must preserve the AI proposal'
        app.project_output_draft.set(str(base / '새보관'))
        app.project_save_button.invoke()
        assert app.engine is None and not app.monitor_enabled.get()
        assert not app.view_items
        assert note.exists()
        assert ai.call_count == 1
        errors.assert_not_called()
    app.close()
    print('PASS GUI v6.3: independent setup with no AI/key, saved drafts, explicit monitor start, minimum layout, preserve plan for period/unchanged saves, invalidate only on output change')
    print('PASS GUI v6.4: setup-first navigation, analysis opens results, explicit move action, help opens/closes without AI or plan changes, single help window and screen fit')
