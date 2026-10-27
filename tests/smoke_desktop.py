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
    root.update()
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
        assert app.primary_button.cget('text') == '2개 파일 정리'
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
    print('PASS GUI: settings save/cancel, draft preservation, contextual actions, analysis without movement, metrics, review edit/approval, selected move, search/duplicates/history navigation, undo, compact layout, per-file AI permission (mock AI)')
    app.close()
