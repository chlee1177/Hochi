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
        ImageGrab.grab().save(path)


with tempfile.TemporaryDirectory() as directory:
    root = tk.Tk()
    app = App(root)
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
        app.start(False)
        wait(root, app)
        assert ai.call_count == 2, 'Sensitive files must never be sent automatically'
        assert source.exists() and sensitive.exists()
        assert len(app.table.get_children()) == 4
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
        app.apply()
        wait(root, app)
        target = folder / OUTPUT_NAME / '학습/물리학' / source.name
        sensitive_target = folder / OUTPUT_NAME / '개인/검토완료/확인한문서.txt'
        assert target.exists() and not source.exists()
        assert sensitive_target.exists() and not sensitive.exists()
        assert email.exists() and duplicate.exists()
        assert ai.call_count == 2, 'Local move approval must not authorize AI transmission'
        app.tabs.select(1)
        app.query.set('물리학 수업 자료 찾아줘')
        app.search()
        wait(root, app)
        assert len(app.library.get_children()) == 2
        capture(root, 'search')
        app.duplicates()
        wait(root, app)
        assert len(app.library.get_children()) == 2
        app.history()
        wait(root, app)
        assert len(app.library.get_children()) >= 4
        app.undo()
        wait(root, app)
        assert source.exists() and sensitive.exists()
        app.tabs.select(0)
        app.start(True)
        wait(root, app)
        assert target.exists() and not source.exists()
        assert sensitive.exists() and email.exists()
        assert len(app.engine.plan['items']) == 2
        assert '자동 정리 완료' in app.status.get()
        app.table.selection_set(app.rows['계약서.txt'])
        app.show_details()
        capture(root, '')
        previous_calls = ai.call_count
        app.table.selection_set(app.rows['연락메모.txt'])
        app.allow_external()
        wait(root, app)
        assert ai.call_count == previous_calls + 1
        assert not app.plan_item('연락메모.txt')['selected']
        app.undo()
        wait(root, app)
        assert source.exists() and duplicate.exists() and sensitive.exists() and email.exists()
        errors.assert_not_called()
    print('PASS GUI: local privacy hold, AI hierarchy/summary/tags, review filter, edit dialog, rename approval, selection, move, local search, duplicates, history, undo, automatic hold, per-file AI permission (mock AI)')
    app.close()
