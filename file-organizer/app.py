"""Desktop UI for private review, AI organization, and local retrieval."""
import os
import json
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from folder_organizer import Cancelled, FolderOrganizer, OUTPUT_NAME


class App:
    def __init__(self, root):
        self.root = root
        self.engine = None
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.folder = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.use_content = tk.BooleanVar(value=True)
        self.sensitive_terms = tk.StringVar()
        self.key = tk.StringVar(value=os.environ.get('HOCHI_AI_KEY', ''))
        self.status = tk.StringVar(value='폴더를 선택하세요. 민감 후보는 외부 전송·자동 이동 전에 보류합니다.')
        self.query = tk.StringVar()
        self.filter = tk.StringVar(value='전체')
        self.view_items = {}
        self.rows = {}
        self.library_items = {}
        self.controls = []
        root.title('Hochi · AI 파일 정리와 로컬 검색')
        root.geometry('1200x850')
        root.minsize(1000, 740)
        style = ttk.Style()
        style.theme_use('clam')
        family = '맑은 고딕' if os.name == 'nt' else 'Noto Sans CJK KR'
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
            tkfont.nametofont(name).configure(family=family, size=10)
        style.configure('.', font=(family, 10))
        style.configure('Title.TLabel', font=(family, 22, 'bold'))
        style.configure('TButton', padding=6)
        style.configure('Treeview', rowheight=29)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(6, weight=1)
        ttk.Label(frame, text='정리하고, 검토하고, 다시 찾으세요.', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(frame, text='로컬 사전 검사 → AI 분류·요약·태그 → 선택 실행 → 검색 · 마지막 작업 되돌리기').grid(row=1, column=0, sticky='w', pady=(4, 12))
        location = ttk.Frame(frame)
        location.grid(row=2, column=0, sticky='ew')
        location.columnconfigure(1, weight=1)
        ttk.Label(location, text='대상 폴더').grid(row=0, column=0, padx=(0, 8))
        entry = ttk.Entry(location, textvariable=self.folder)
        entry.grid(row=0, column=1, sticky='ew')
        browse = ttk.Button(location, text='폴더 선택', command=self.choose_folder)
        browse.grid(row=0, column=2, padx=(8, 0))
        self.controls += [entry, browse]
        options = ttk.Frame(frame)
        options.grid(row=3, column=0, sticky='ew', pady=8)
        for title, variable in [('하위 폴더 포함', self.recursive), ('지원되는 내용도 분석', self.use_content)]:
            control = ttk.Checkbutton(options, text=title, variable=variable)
            control.pack(side='left', padx=(0, 14))
            self.controls.append(control)
        ttk.Label(options, text='추가 민감 키워드').pack(side='left', padx=(8, 6))
        terms_entry = ttk.Entry(options, textvariable=self.sensitive_terms, width=35)
        terms_entry.pack(side='left', fill='x', expand=True)
        self.controls.append(terms_entry)
        ttk.Label(options, text='쉼표로 구분').pack(side='left', padx=6)
        credentials = ttk.Frame(frame)
        credentials.grid(row=4, column=0, sticky='ew')
        ttk.Label(credentials, text='OpenAI API 키').pack(side='left', padx=(0, 8))
        key_entry = ttk.Entry(credentials, textvariable=self.key, show='•', width=38)
        key_entry.pack(side='left')
        self.controls.append(key_entry)
        ttk.Label(credentials, text='키는 파일에 저장하지 않습니다. AI 분석에는 비용이 발생합니다.').pack(side='left', padx=8)
        ttk.Label(frame, text='로컬 규칙으로 감지한 민감 후보와 검사할 수 없는 이미지는 검토 대기합니다. 자동 탐지는 완전하지 않습니다.', wraplength=950).grid(row=5, column=0, sticky='w', pady=(8, 10))
        self.tabs = ttk.Notebook(frame)
        self.tabs.grid(row=6, column=0, sticky='nsew')
        review = ttk.Frame(self.tabs, padding=10)
        library = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(review, text='분류와 검토')
        self.tabs.add(library, text='로컬 검색과 중복')
        review.columnconfigure(0, weight=1)
        review.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(review)
        toolbar.grid(row=0, column=0, sticky='ew')
        for title, action in [
            ('AI 분석 후 자동 정리', lambda: self.start(True)), ('분석만', lambda: self.start(False)),
            ('선택한 파일 이동', self.apply), ('마지막 정리 되돌리기', self.undo), ('결과 폴더', self.open_folder)]:
            self.button(toolbar, title, action)
        self.cancel_button = ttk.Button(toolbar, text='취소', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left')
        editing = ttk.Frame(review)
        editing.grid(row=1, column=0, sticky='ew', pady=8)
        combo = ttk.Combobox(editing, textvariable=self.filter, values=['전체', '검토 대기', '이동 선택', '이동 완료'], width=11, state='readonly')
        combo.pack(side='left', padx=(0, 8))
        combo.bind('<<ComboboxSelected>>', lambda _: self.render())
        self.controls.append(combo)
        self.button(editing, '선택 파일 수정·승인', self.edit_selected)
        self.button(editing, '이동 포함 / 제외', self.toggle_selected)
        self.button(editing, '이 파일의 AI 전송 허용', self.allow_external)
        ttk.Label(editing, text='행 선택 후 수정 · 여러 행 선택 가능').pack(side='left', padx=8)
        self.table = self.make_table(review, [('selected', '이동', 55), ('file', '원래 경로', 220),
                  ('category', '분류 / 새 파일명', 220), ('scope', '분석 근거', 260), ('state', '상태', 130)], row=2)
        self.table.bind('<<TreeviewSelect>>', lambda _: self.show_details())
        self.table.bind('<Double-1>', lambda _: self.edit_selected())
        self.details = tk.Text(review, height=4, wrap='word', font=(family, 10), relief='flat', state='disabled')
        self.details.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        library.columnconfigure(0, weight=1)
        library.rowconfigure(2, weight=1)
        searchbar = ttk.Frame(library)
        searchbar.grid(row=0, column=0, sticky='ew')
        search_entry = ttk.Entry(searchbar, textvariable=self.query, width=35)
        search_entry.pack(side='left', fill='x', expand=True, padx=(0, 6))
        search_entry.bind('<Return>', lambda _: self.search())
        self.controls.append(search_entry)
        self.button(searchbar, '검색', self.search)
        self.button(searchbar, '중복 파일', self.duplicates)
        self.button(searchbar, '유사 문서', self.similar)
        self.button(searchbar, '작업 기록', self.history)
        self.button(searchbar, '선택 파일 위치', self.open_search_location)
        ttk.Label(library, text='파일명·분류·요약·태그를 로컬에서 검색합니다. 중복은 파일 내용 해시, 유사는 요약·태그의 공통 단어 기준입니다.', wraplength=950).grid(row=1, column=0, sticky='w', pady=8)
        self.library = self.make_table(library, [('path', '현재 경로', 320), ('folder', '분류 / 그룹', 160),
                      ('tags', '태그 / 일치도', 180), ('summary', '요약 / 관련 파일', 400)], row=2)
        self.progress = ttk.Progressbar(frame, mode='determinate')
        self.progress.grid(row=7, column=0, sticky='ew', pady=(10, 6))
        ttk.Label(frame, textvariable=self.status, wraplength=950).grid(row=8, column=0, sticky='w')
        for variable in (self.folder, self.recursive, self.use_content, self.sensitive_terms):
            variable.trace_add('write', self.invalidate)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(80, self.poll)

    def button(self, parent, title, action):
        button = ttk.Button(parent, text=title, command=action)
        button.pack(side='left', padx=(0, 6))
        self.controls.append(button)
        return button

    def make_table(self, parent, columns, row):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky='nsew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table = ttk.Treeview(frame, columns=tuple(key for key, _, _ in columns), show='headings', height=5)
        for key, title, width in columns:
            table.heading(key, text=title)
            table.column(key, width=width, minwidth=45)
        vertical = ttk.Scrollbar(frame, orient='vertical', command=table.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=table.xview)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        return table

    def invalidate(self, *_):
        if not self.busy:
            self.engine = None
            self.clear_table()
            self.library.delete(*self.library.get_children())
            self.library_items.clear()
            self.status.set('폴더 또는 옵션이 변경되었습니다. 다시 분석하거나 저장된 색인을 검색하세요.')

    def clear_table(self):
        self.view_items.clear()
        self.render()
        self.progress['value'] = 0

    def render(self):
        selection = {relative for relative, row in self.rows.items() if row in self.table.selection()}
        self.table.delete(*self.table.get_children())
        self.rows.clear()
        for relative, item in self.view_items.items():
            state = item.get('display_state') or ('검토 승인' if item.get('approved_move') else '검토 대기' if item.get('review_required') else '분석 완료')
            if self.filter.get() == '검토 대기' and not (item.get('review_required') and not item.get('approved_move') and state != '이동 완료'):
                continue
            if self.filter.get() == '이동 선택' and (not item.get('selected') or state == '이동 완료'):
                continue
            if self.filter.get() == '이동 완료' and state != '이동 완료':
                continue
            destination = item['folder'] + '/' + item['new_name']
            row = self.table.insert('', 'end', values=('✓' if item['selected'] and state != '이동 완료' else '—',
                       relative, destination, item['scope'], state))
            self.rows[relative] = row
            if relative in selection:
                self.table.selection_add(row)
        self.show_details()

    def selected_paths(self):
        chosen = set(self.table.selection())
        return [relative for relative, row in self.rows.items() if row in chosen]

    def show_details(self):
        paths = self.selected_paths()
        text = ''
        if paths:
            item = self.view_items[paths[0]]
            text = f"요약: {item.get('summary') or '저장된 요약 없음'}\n태그: {', '.join(item.get('tags', []))}\n이유: {item['reason']}\n검토: {'; '.join(item.get('review_reasons', [])) or '로컬 규칙에서 감지 없음'}"
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def choose_folder(self):
        selected = filedialog.askdirectory(title='정리할 폴더 선택')
        if selected:
            self.folder.set(selected)

    def new_engine(self):
        if not self.folder.get().strip():
            raise ValueError('대상 폴더를 선택하세요.')
        return FolderOrganizer(self.folder.get().strip(), self.recursive.get(), self.use_content.get(),
                               sensitive_terms=[term.strip() for term in self.sensitive_terms.get().split(',') if term.strip()])

    def report(self, stage, index, total, item):
        self.events.put(('progress', stage, index, total, dict(item)))

    def run(self, task, done, cancellable=True):
        if self.busy:
            return
        self.busy = True
        self.cancel_event.clear()
        for control in self.controls:
            control.state(['disabled'])
        if cancellable:
            self.cancel_button.state(['!disabled'])
        self.status.set('작업 중…')
        def work():
            try:
                self.events.put(('done', done, task(), None))
            except Exception as error:
                self.events.put(('done', done, None, error))
        self.worker.submit(work)

    def start(self, automatic):
        if self.busy:
            return
        try:
            engine = self.new_engine()
        except (ValueError, OSError) as error:
            messagebox.showerror('시작할 수 없음', str(error))
            return
        action = '검토 대기 파일을 제외하고 원본을 자동 이동합니다.' if automatic else '원본을 이동하지 않고 분석 결과를 표시합니다.'
        if not messagebox.askyesno('AI 분석 시작', f'{engine.root}\n\n로컬 사전 검사 후 허용 대상의 파일명·상대 경로와 선택한 지원 내용을 OpenAI로 전송합니다. API 비용이 발생합니다.\n{action}\n계속할까요?'):
            return
        os.environ['HOCHI_AI_KEY'] = self.key.get().strip()
        self.engine = engine
        self.clear_table()
        def task():
            plan = engine.analyze(self.report, self.cancel_event)
            return engine.apply(plan['id'], self.report, self.cancel_event) if automatic else plan
        def done(result):
            moved = len(result.get('moves', []))
            pending = len(engine.plan['items']) if engine.plan else 0
            self.status.set(f'{"자동 정리 완료" if automatic else "분석 완료"} · 이동 {moved}개 · 남은 검토/분석 {pending}개 · 링크/특수 파일 제외 {len(engine.skipped)}개')
        self.run(task, done)

    def apply(self):
        if self.busy:
            return
        if not self.engine or not self.engine.plan:
            messagebox.showinfo('분석 필요', '먼저 AI 분석을 실행하세요.')
            return
        count = sum(item['selected'] for item in self.engine.plan['items'])
        if not count:
            messagebox.showinfo('선택 필요', '이동할 파일을 포함하거나 검토 후 승인하세요.')
            return
        if not messagebox.askyesno('원본 이동', f'이동에 포함한 {count}개 파일을 표시된 경로와 이름으로 이동할까요?'):
            return
        engine, plan_id = self.engine, self.engine.plan['id']
        self.run(lambda: engine.apply(plan_id, self.report, self.cancel_event),
                 lambda result: self.status.set(f"{len(result['moves'])}개 이동 완료 · 남은 파일 {result['held']}개"))

    def plan_item(self, relative):
        if not self.engine or not self.engine.plan:
            raise ValueError('먼저 분석하세요. 이미 이동한 파일은 되돌린 뒤 수정할 수 있습니다.')
        item = next((item for item in self.engine.plan['items'] if item['relative'] == relative), None)
        if item is None:
            raise ValueError('이미 이동한 파일입니다. 되돌린 뒤 다시 분석하세요.')
        return item

    def edit_selected(self):
        if self.busy:
            return
        paths = self.selected_paths()
        if len(paths) != 1:
            messagebox.showinfo('파일 선택', '수정할 파일 하나를 선택하세요.')
            return
        try:
            item = self.plan_item(paths[0])
        except ValueError as error:
            messagebox.showinfo('수정 불가', str(error))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('분류 수정 및 이동 승인')
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=paths[0], wraplength=550).pack(anchor='w')
        folder, name = tk.StringVar(value=item['folder']), tk.StringVar(value=item['new_name'])
        selected, approved = tk.BooleanVar(value=item['selected']), tk.BooleanVar(value=item['approved_move'])
        ttk.Label(frame, text='분류 경로 (예: 업무/프로젝트 · 최대 3단계)').pack(anchor='w', pady=(12, 4))
        ttk.Entry(frame, textvariable=folder, width=58).pack(fill='x')
        ttk.Label(frame, text='이동 후 파일명').pack(anchor='w', pady=(10, 4))
        ttk.Entry(frame, textvariable=name).pack(fill='x')
        ttk.Checkbutton(frame, text='이 파일을 이동 대상에 포함', variable=selected).pack(anchor='w', pady=10)
        if item['review_required']:
            ttk.Label(frame, text='검토 사유: ' + '; '.join(item['review_reasons']), wraplength=550).pack(anchor='w')
            ttk.Checkbutton(frame, text='파일을 직접 검토했으며 로컬 이동을 승인합니다', variable=approved).pack(anchor='w', pady=8)
        ttk.Label(frame, text='이 승인은 AI 전송을 허용하지 않습니다.', wraplength=550).pack(anchor='w', pady=6)
        def save():
            try:
                changed = self.engine.edit_item(paths[0], folder.get(), name.get(), selected.get(), approved.get())
                self.view_items[paths[0]] = dict(changed)
                self.render()
                dialog.destroy()
            except (ValueError, OSError) as error:
                messagebox.showerror('수정 실패', str(error), parent=dialog)
        ttk.Button(frame, text='수정 저장', command=save).pack(anchor='e', pady=(10, 0))

    def toggle_selected(self):
        if self.busy:
            return
        try:
            for relative in self.selected_paths():
                item = self.plan_item(relative)
                updated = self.engine.edit_item(relative, item['folder'], item['new_name'], not item['selected'])
                self.view_items[relative] = dict(updated)
        except (ValueError, OSError) as error:
            messagebox.showinfo('검토 필요', str(error))
        self.render()

    def allow_external(self):
        if self.busy:
            return
        paths = self.selected_paths()
        if len(paths) != 1:
            messagebox.showinfo('파일 선택', 'AI 전송을 허용할 파일 하나를 선택하세요.')
            return
        try:
            self.plan_item(paths[0])
            if not self.key.get().strip():
                raise ValueError('OpenAI API 키를 입력하세요.')
        except ValueError as error:
            messagebox.showerror('전송 불가', str(error))
            return
        if not messagebox.askyesno('이 파일의 외부 전송 허용', f'{paths[0]}\n\n이 파일의 파일명·상대 경로와 선택한 지원 내용/이미지가 OpenAI로 전송됩니다. 민감정보가 포함될 수 있습니다.\n이 파일에 한해 전송을 허용할까요?\n이동 승인은 별도로 필요합니다.'):
            return
        os.environ['HOCHI_AI_KEY'] = self.key.get().strip()
        engine = self.engine
        def done(item):
            self.view_items[item['relative']] = dict(item)
            self.render()
            self.status.set('개별 AI 분석 완료. 분류를 확인하고 이동 승인 여부를 선택하세요.')
        self.run(lambda: engine.analyze_reviewed(paths[0], allow_external=True, cancel=self.cancel_event), done)

    def undo(self):
        if self.busy:
            return
        try:
            engine = self.new_engine()
        except (ValueError, OSError) as error:
            messagebox.showerror('되돌리기 실패', str(error))
            return
        if not messagebox.askyesno('정리 되돌리기', '선택한 폴더의 마지막 이동과 검색 색인의 경로를 원래대로 복구할까요?'):
            return
        self.engine = engine
        def done(count):
            self.clear_table()
            self.status.set(f'{count}개 파일과 검색 경로를 복구했습니다.')
        self.run(engine.undo, done, cancellable=False)

    def search(self):
        if self.busy:
            return
        try:
            engine = self.new_engine()
        except (ValueError, OSError) as error:
            messagebox.showerror('검색 실패', str(error))
            return
        query = self.query.get()
        def done(records):
            self.clear_library()
            for record in records:
                row = self.library.insert('', 'end', values=(record['current_path'], record['folder'], ', '.join(record['tags']), record['summary'] or record['reason']))
                self.library_items[row] = record['current_path']
            self.status.set(f'로컬 검색 {len(records)}개 결과 · 수정되거나 사라진 파일은 제외 · 검색어와 색인은 외부 전송 안 함')
        self.run(lambda: engine.search(query), done, cancellable=False)

    def clear_library(self):
        self.library.delete(*self.library.get_children())
        self.library_items.clear()

    def duplicates(self):
        if self.busy:
            return
        try:
            engine = self.new_engine()
        except (ValueError, OSError) as error:
            messagebox.showerror('검사 실패', str(error))
            return
        def done(groups):
            self.clear_library()
            for number, group in enumerate(groups, 1):
                for path in group['files']:
                    row = self.library.insert('', 'end', values=(path, f'중복 그룹 {number}', '내용 동일', f"{len(group['files'])}개 파일 · 자동 삭제하지 않음"))
                    self.library_items[row] = path
            self.status.set(f'중복 {len(groups)}그룹 발견 · SHA-256 내용 비교 · 파일은 변경하지 않았습니다.')
        self.run(lambda: engine.duplicates(self.cancel_event), done)

    def similar(self):
        if self.busy:
            return
        try:
            engine = self.new_engine()
        except (ValueError, OSError) as error:
            messagebox.showerror('검사 실패', str(error))
            return
        def done(pairs):
            self.clear_library()
            for pair in pairs:
                row = self.library.insert('', 'end', values=(pair['first'], '유사 문서', f"{pair['score']:.0%} 공통 단어", pair['second']))
                self.library_items[row] = pair['first']
            self.status.set(f'유사 문서 {len(pairs)}쌍 · 요약·태그의 단어 유사도이며 의미 검색 모델의 정확도가 아닙니다.')
        self.run(engine.similar, done, cancellable=False)

    def open_search_location(self):
        selection = self.library.selection()
        if not selection or selection[0] not in self.library_items:
            return
        try:
            engine = self.new_engine()
            path = engine._safe(engine.root / self.library_items[selection[0]], engine.root)
            self.open_path(path.parent)
        except (OSError, ValueError) as error:
            messagebox.showerror('위치 열기 실패', str(error))

    def history(self):
        if self.busy:
            return
        try:
            engine = self.new_engine()
        except (ValueError, OSError) as error:
            messagebox.showerror('기록 조회 실패', str(error))
            return
        def done(events):
            self.clear_library()
            for event in events:
                self.library.insert('', 'end', values=(event['time'], event['kind'], '', json.dumps(event['detail'], ensure_ascii=False)))
            self.status.set(f'최근 작업 기록 {len(events)}개 · 시각은 UTC · 원문 내용은 기록하지 않습니다.')
        self.run(engine.history, done, cancellable=False)

    def cancel(self):
        self.cancel_event.set()
        self.cancel_button.state(['disabled'])
        self.status.set('취소 요청됨. 진행 중인 AI 응답을 기다린 뒤 중단하고 이동한 파일은 복구합니다.')

    def poll(self):
        redraw = False
        for _ in range(100):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == 'progress':
                _, stage, index, total, item = event
                if stage == 'move':
                    item['display_state'] = '이동 완료'
                self.view_items[item['relative']] = item
                redraw = True
                self.progress.configure(maximum=total, value=index)
                self.status.set(f'{"분석·검토" if stage == "analyze" else "이동"} {index}/{total}: {item["relative"]}')
            else:
                _, done, result, error = event
                self.busy = False
                for control in self.controls:
                    control.state(['!disabled'])
                self.cancel_button.state(['disabled'])
                if redraw:
                    self.render()
                    redraw = False
                if error:
                    for item in self.view_items.values():
                        item['display_state'] = '작업 중단'
                    self.render()
                    self.status.set(('취소: ' if isinstance(error, Cancelled) else '작업 실패: ') + str(error))
                    if not isinstance(error, Cancelled):
                        messagebox.showerror('작업 실패', str(error))
                else:
                    done(result)
        if redraw:
            self.render()
        self.root.after(80, self.poll)

    def open_path(self, path):
        if not path.is_dir():
            raise ValueError('폴더가 없습니다.')
        if sys.platform == 'win32':
            os.startfile(str(path))
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])

    def open_folder(self):
        try:
            self.open_path(self.new_engine().output)
        except (OSError, ValueError) as error:
            messagebox.showinfo('결과 폴더', str(error))

    def close(self):
        if self.busy:
            messagebox.showinfo('작업 진행 중', '취소를 누른 뒤 현재 작업과 복구가 끝나면 종료하세요.')
            return
        self.worker.shutdown(wait=False)
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
