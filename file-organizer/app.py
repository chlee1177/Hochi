"""Desktop workspace for AI proposals, explicit review, and local retrieval."""
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from folder_organizer import Cancelled, FolderOrganizer, OUTPUT_NAME
from local_ai import OllamaClient, DEFAULT_MODEL, DEFAULT_URL
from project_ui import ProjectUI
from ui_theme import configure, BG, SURFACE, INK, MUTED, LINE, BLUE, NAVY


class App(ProjectUI):
    def __init__(self, root):
        self.root = root
        self.engine = None
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.folder = tk.StringVar()
        self.init_project()
        self.recursive = tk.BooleanVar(value=True)
        self.use_content = tk.BooleanVar(value=True)
        self.sensitive_terms = tk.StringVar()
        self.key = tk.StringVar(value=os.environ.get('HOCHI_AI_KEY', ''))
        self.provider = tk.StringVar(value=os.environ.get('HOCHI_AI_PROVIDER', 'openai' if self.key.get() else 'ollama'))
        if self.provider.get() not in ('openai', 'ollama'):
            self.provider.set('ollama')
        self.ollama_url = tk.StringVar(value=os.environ.get('HOCHI_OLLAMA_URL', DEFAULT_URL))
        self.ollama_model = tk.StringVar(value=os.environ.get('HOCHI_OLLAMA_MODEL', DEFAULT_MODEL))
        self.status = tk.StringVar(value='폴더를 선택하고 AI 분석을 시작하세요.')
        self.query = tk.StringVar()
        self.filter = tk.StringVar(value='전체')
        self.library_mode = tk.StringVar(value='파일 검색')
        self.connection = tk.StringVar()
        self.page_title = tk.StringVar(value='파일 정리')
        self.page_description = tk.StringVar(value='흩어진 파일을, 다시 찾기 좋은 구조로.')
        self.step = tk.StringVar(value='01  폴더 선택    →    02  AI 분석    →    03  검토 후 정리')
        self.selection_title = tk.StringVar(value='파일 미리보기')
        self.library_hint = tk.StringVar(value='파일명·요약·태그로 찾으세요. 검색어는 내 PC에만 머뭅니다.')
        self.metrics = [tk.StringVar(value='0') for _ in range(4)]
        self.view_items, self.rows, self.library_items = {}, {}, {}
        self.controls = []
        self.settings_dialog = None
        root.title('FileNest · AI 파일 정리')
        root.geometry('1240x850')
        root.minsize(1100, 800)
        self.family = configure(root)
        self.build_sidebar()
        frame = ttk.Frame(root, padding=(26, 18, 26, 14))
        frame.pack(side='left', fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky='ew', pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.page_title, style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(header, textvariable=self.page_description, style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(4, 0))
        self.settings_button = ttk.Button(header, text='분석 설정', command=self.open_settings)
        self.settings_button.grid(row=0, column=1, rowspan=2, sticky='e')
        self.controls.append(self.settings_button)

        location = ttk.Frame(frame, style='Card.TFrame', padding=(16, 12))
        location.grid(row=1, column=0, sticky='ew', pady=(0, 14))
        location.columnconfigure(0, weight=1)
        ttk.Label(location, text='작업 폴더', style='Section.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 8))
        ttk.Label(location, textvariable=self.connection, style='CardMuted.TLabel').grid(row=0, column=1, sticky='e')
        self.folder_entry = ttk.Entry(location, textvariable=self.folder)
        self.folder_entry.grid(row=1, column=0, sticky='ew', padx=(0, 10))
        self.browse_button = ttk.Button(location, text='폴더 선택', command=self.choose_folder)
        self.browse_button.grid(row=1, column=1)
        ttk.Label(location, textvariable=self.destination_hint, style='CardMuted.TLabel', wraplength=650).grid(row=2, column=0, sticky='w', pady=(8, 0))
        project_button = ttk.Button(location, text='저장·감시 설정', command=self.open_project_settings)
        project_button.grid(row=2, column=1, pady=(8, 0))
        self.controls += [self.folder_entry, self.browse_button, project_button]

        self.tabs = ttk.Notebook(frame, style='Workspace.TNotebook')
        self.tabs.grid(row=2, column=0, sticky='nsew')
        review, library, history, versions = (ttk.Frame(self.tabs) for _ in range(4))
        for panel, title in [(review, '파일 정리'), (library, '파일 검색'), (history, '작업 기록'), (versions, '버전 관리')]:
            self.tabs.add(panel, text=title)
        self.tabs.bind('<<NotebookTabChanged>>', self.page_changed)
        self.build_review(review)
        self.build_library(library)
        self.build_history(history)
        self.build_versions(versions)

        footer = ttk.Frame(frame)
        footer.grid(row=3, column=0, sticky='ew', pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode='determinate')
        self.progress.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        self.progress.grid_remove()
        self.status_label = ttk.Label(footer, textvariable=self.status, style='Muted.TLabel', wraplength=800)
        self.status_label.grid(row=1, column=0, sticky='w')
        self.cancel_button = ttk.Button(footer, text='작업 취소', command=self.cancel, state='disabled')
        self.cancel_button.grid(row=1, column=1, padx=(10, 0))
        self.cancel_button.grid_remove()
        footer.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(200, event.width - 120)))
        for variable in (self.folder, self.recursive, self.use_content, self.sensitive_terms,
                         self.provider, self.ollama_url, self.ollama_model):
            variable.trace_add('write', self.invalidate)
        for variable in (self.provider, self.ollama_model):
            variable.trace_add('write', lambda *_: self.update_connection())
        self.key.trace_add('write', lambda *_: self.update_connection())
        self.folder.trace_add('write', self.project_changed)
        self.output_folder.trace_add('write', self.invalidate)
        self.update_connection()
        self.render()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = root.after(80, self.poll)
        self.monitor_id = root.after(30000, self.monitor_tick)

    def build_sidebar(self):
        rail = tk.Frame(self.root, bg=NAVY, width=172)
        rail.pack(side='left', fill='y')
        rail.pack_propagate(False)
        tk.Label(rail, text='FileNest', font=(self.family, 22, 'bold'), fg='white', bg=NAVY).pack(anchor='w', padx=22, pady=(25, 0))
        tk.Label(rail, text='AI FILE ORGANIZER', font=(self.family, 8), fg='#8FA4C3', bg=NAVY).pack(anchor='w', padx=24, pady=(0, 32))
        self.nav_buttons = []
        for index, title in enumerate(('파일 정리', '파일 검색', '작업 기록', '버전 관리')):
            button = tk.Button(rail, text=title, anchor='w', padx=18, pady=12, relief='flat', bd=0,
                               bg=NAVY, fg='#B9C8DF', activebackground='#253D60', activeforeground='white',
                               font=(self.family, 11), cursor='hand2', highlightbackground=NAVY, highlightcolor=BLUE,
                               command=lambda i=index: self.navigate(i))
            button.pack(fill='x', padx=12, pady=3)
            self.nav_buttons.append(button)

    def build_review(self, review):
        review.columnconfigure(0, weight=1)
        review.rowconfigure(2, weight=1)
        ttk.Label(review, textvariable=self.step, style='Muted.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 12))
        cards = ttk.Frame(review)
        cards.grid(row=1, column=0, sticky='ew', pady=(0, 12))
        for i, (label, style) in enumerate(zip(('분석한 파일', '정리할 파일', '검토 대기', '이동 완료'),
                                              ('Metric.TLabel', 'Blue.Metric.TLabel', 'Amber.Metric.TLabel', 'Green.Metric.TLabel'))):
            cards.columnconfigure(i, weight=1, uniform='metric')
            card = ttk.Frame(cards, style='Card.TFrame', padding=(16, 7))
            card.grid(row=0, column=i, sticky='ew', padx=(0, 10 if i < 3 else 0))
            ttk.Label(card, text=label, style='CardMuted.TLabel').pack(anchor='w')
            ttk.Label(card, textvariable=self.metrics[i], style=style).pack(anchor='w')

        content = ttk.Frame(review)
        content.grid(row=2, column=0, sticky='nsew')
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, minsize=258)
        content.rowconfigure(0, weight=1)
        table_card = ttk.Frame(content, style='Card.TFrame', padding=(12, 14))
        table_card.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        table_card.columnconfigure(0, weight=1)
        table_card.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(table_card, style='Card.TFrame')
        toolbar.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        ttk.Label(toolbar, text='분류 제안', style='Section.TLabel').pack(side='left')
        combo = ttk.Combobox(toolbar, textvariable=self.filter, values=['전체', '검토 대기', '이동 선택', '이동 완료'], width=11, state='readonly')
        combo.pack(side='right')
        combo.bind('<<ComboboxSelected>>', lambda _: self.render())
        self.controls.append(combo)
        self.table = self.make_table(table_card, [('selected', '이동', 45), ('file', '현재 파일', 175),
                                                ('category', '정리할 위치', 190), ('state', '상태', 90)], row=1)
        self.table.tag_configure('held', foreground='#A76608')
        self.table.tag_configure('moved', foreground='#15806A')
        self.table.bind('<<TreeviewSelect>>', lambda _: self.show_details())
        self.table.bind('<Double-1>', lambda _: self.edit_selected())
        self.empty = ttk.Frame(self.table, style='Card.TFrame', padding=12)
        icon = tk.Canvas(self.empty, width=84, height=66, bg=SURFACE, highlightthickness=0)
        icon.pack(pady=(0, 12))
        icon.create_polygon(8, 15, 34, 15, 42, 23, 76, 23, 76, 57, 8, 57, fill='#DCE8FF', outline='')
        icon.create_rectangle(8, 29, 76, 57, fill='#AFCBFF', outline='')
        self.empty_title = ttk.Label(self.empty, text='폴더 하나로 시작하세요', style='Section.TLabel')
        self.empty_title.pack()
        self.empty_copy = ttk.Label(self.empty, text='AI가 분류를 제안하면, 확인 후 정리할 수 있어요.', style='CardMuted.TLabel', wraplength=310, justify='center')
        self.empty_copy.pack(pady=(6, 0))

        detail = ttk.Frame(content, style='Card.TFrame', padding=16, width=258)
        detail.grid(row=0, column=1, sticky='nsew')
        detail.grid_propagate(False)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(1, weight=1)
        ttk.Label(detail, textvariable=self.selection_title, style='Section.TLabel', wraplength=226).grid(row=0, column=0, sticky='w', pady=(0, 10))
        self.details = tk.Text(detail, height=6, width=24, wrap='word', font=(self.family, 10), bg=SURFACE,
                               fg=MUTED, relief='flat', bd=0, highlightthickness=0, state='disabled', cursor='arrow')
        self.details.grid(row=1, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(detail, orient='vertical', command=self.details.yview)
        scrollbar.grid(row=1, column=1, sticky='ns')
        self.details.configure(yscrollcommand=scrollbar.set)
        self.detail_actions = ttk.Frame(detail, style='Card.TFrame')
        self.detail_actions.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(12, 0))
        self.edit_button = ttk.Button(self.detail_actions, text='분류·파일명 수정', command=self.edit_selected)
        self.edit_button.pack(fill='x', pady=(0, 6))
        self.toggle_button = ttk.Button(self.detail_actions, text='이동 포함 / 제외', command=self.toggle_selected)
        self.toggle_button.pack(fill='x')
        self.external_button = ttk.Button(self.detail_actions, text='이 파일의 AI 전송 허용', command=self.allow_external)
        self.controls += [self.edit_button, self.toggle_button, self.external_button]

        actions = ttk.Frame(review)
        actions.grid(row=3, column=0, sticky='ew', pady=(16, 0))
        self.more_button = ttk.Menubutton(actions, text='더 보기')
        menu = tk.Menu(self.more_button, tearoff=False)
        menu.add_command(label='마지막 정리 되돌리기', command=self.undo)
        menu.add_command(label='결과 폴더 열기', command=self.open_folder)
        menu.add_command(label='내 분류 규칙', command=self.open_rules)
        self.more_button.configure(menu=menu)
        self.more_button.pack(side='left')
        self.controls.append(self.more_button)
        self.primary_button = ttk.Button(actions, text='AI 분석 시작', style='Primary.TButton', command=self.primary_action)
        self.primary_button.pack(side='right')
        self.reanalyze_button = ttk.Button(actions, text='다시 분석', command=lambda: self.start(False))
        self.controls += [self.primary_button, self.reanalyze_button]

    def build_library(self, library):
        library.columnconfigure(0, weight=1)
        library.rowconfigure(2, weight=1)
        searchbar = ttk.Frame(library)
        searchbar.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        mode = ttk.Combobox(searchbar, textvariable=self.library_mode, values=['파일 검색', '중복 파일', '유사 문서'], width=10, state='readonly')
        mode.pack(side='left', padx=(0, 8))
        mode.bind('<<ComboboxSelected>>', lambda _: self.library_mode_changed())
        self.search_entry = ttk.Entry(searchbar, textvariable=self.query)
        self.search_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.search_entry.bind('<Return>', lambda _: self.run_library())
        self.search_button = ttk.Button(searchbar, text='검색', style='Primary.TButton', command=self.run_library)
        self.search_button.pack(side='left')
        previous = ttk.Checkbutton(searchbar, text='이전 버전 포함', variable=self.include_previous)
        previous.pack(side='left', padx=(8, 0))
        self.controls.append(previous)
        self.controls += [mode, self.search_entry, self.search_button]
        ttk.Label(library, textvariable=self.library_hint, style='Muted.TLabel', wraplength=800).grid(row=1, column=0, sticky='w', pady=(0, 12))
        self.library = self.make_table(library, [('path', '현재 경로', 260), ('folder', '분류 / 그룹', 145),
                                                ('tags', '태그 / 일치도', 150), ('summary', '요약 / 관련 파일', 290)], row=2)
        self.location_button = ttk.Button(library, text='선택 파일 위치 열기', command=self.open_search_location, state='disabled')
        self.location_button.grid(row=3, column=0, sticky='e', pady=(12, 0))
        self.library.bind('<<TreeviewSelect>>', lambda _: self.update_actions())
        self.controls.append(self.location_button)

    def build_history(self, history):
        history.columnconfigure(0, weight=1)
        history.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(history)
        toolbar.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        ttk.Label(toolbar, text='최근 100개 기록 · 시간은 UTC 기준입니다.', style='Muted.TLabel').pack(side='left')
        button = ttk.Button(toolbar, text='새로고침', command=self.history)
        button.pack(side='right')
        self.controls.append(button)
        self.history_table = self.make_table(history, [('time', '시각 (UTC)', 180), ('action', '작업', 110), ('detail', '내용', 500)], row=1)
        undo = ttk.Button(history, text='마지막 정리 되돌리기', command=self.undo)
        undo.grid(row=2, column=0, sticky='e', pady=(12, 0))
        self.controls.append(undo)

    def navigate(self, index):
        self.tabs.select(index)
        if index == 2 and self.folder.get().strip() and not self.busy:
            self.history()

    def page_changed(self, _=None):
        index = self.tabs.index(self.tabs.select())
        self.page_title.set(('파일 정리', '파일 검색', '작업 기록', '버전 관리')[index])
        self.page_description.set(('흩어진 파일을, 다시 찾기 좋은 구조로.', '정리한 자료를 내 PC에서 빠르게 찾아보세요.', '정리의 과정과 결과를 한눈에 확인하세요.', '변경을 살펴보고, 사용할 최종본을 직접 지정하세요.')[index])
        for i, button in enumerate(self.nav_buttons):
            button.configure(bg='#294977' if i == index else NAVY, fg='white' if i == index else '#B9C8DF')

    def update_connection(self):
        if self.provider.get() == 'ollama':
            self.connection.set('로컬 AI · ' + self.ollama_model.get())
        else:
            self.connection.set('OpenAI · API 키 입력됨' if self.key.get().strip() else '분석 설정에서 API 키를 연결하세요')

    def open_settings(self):
        if self.busy:
            return
        if self.settings_dialog and self.settings_dialog.winfo_exists():
            self.settings_dialog.lift()
            return
        dialog = self.settings_dialog = tk.Toplevel(self.root)
        dialog.title('분석 설정')
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='분석 설정', style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame, text='설정은 이번 실행 동안만 유지됩니다.', style='Muted.TLabel').pack(anchor='w', pady=(4, 12))
        key = tk.StringVar(value=self.key.get())
        recursive = tk.BooleanVar(value=self.recursive.get())
        content = tk.BooleanVar(value=self.use_content.get())
        terms = tk.StringVar(value=self.sensitive_terms.get())
        provider = tk.StringVar(value='Ollama · 내 PC' if self.provider.get() == 'ollama' else 'OpenAI · 클라우드')
        host = tk.StringVar(value=self.ollama_url.get())
        model = tk.StringVar(value=self.ollama_model.get())
        check_status = tk.StringVar(value='연결 확인은 모델 설치 여부를 확인하며 파일을 보내지 않습니다.')
        ttk.Label(frame, text='AI 실행 방식').pack(anchor='w', pady=(0, 4))
        provider_box = ttk.Combobox(frame, textvariable=provider, values=['Ollama · 내 PC', 'OpenAI · 클라우드'], state='readonly', width=50)
        provider_box.pack(fill='x', pady=(0, 12))
        connection_area = ttk.Frame(frame)
        connection_area.pack(fill='x')
        cloud = ttk.Frame(connection_area)
        ttk.Label(cloud, text='OpenAI API 키').pack(anchor='w', pady=(0, 4))
        key_entry = ttk.Entry(cloud, textvariable=key, show='•', width=52)
        key_entry.pack(fill='x')
        ttk.Label(cloud, text='키는 파일에 저장하지 않습니다. API 비용은 별도입니다.', style='Muted.TLabel').pack(anchor='w', pady=(4, 12))
        local = ttk.Frame(connection_area)
        local.columnconfigure(0, weight=1)
        local.columnconfigure(1, weight=1)
        ttk.Label(local, text='Ollama 서버 주소').grid(row=0, column=0, sticky='w')
        ttk.Label(local, text='설치한 모델').grid(row=0, column=1, sticky='w')
        host_entry = ttk.Entry(local, textvariable=host, width=27)
        host_entry.grid(row=1, column=0, sticky='ew', padx=(0, 8), pady=4)
        model_entry = ttk.Entry(local, textvariable=model, width=23)
        model_entry.grid(row=1, column=1, sticky='ew', pady=4)
        check_button = ttk.Button(local, text='연결 확인')
        check_button.grid(row=2, column=1, sticky='e', pady=4)
        ttk.Label(local, textvariable=check_status, style='Muted.TLabel', wraplength=480).grid(row=3, column=0, columnspan=2, sticky='w', pady=(0, 10))
        note = tk.StringVar()
        def select_provider(_=None):
            cloud.pack_forget()
            local.pack_forget()
            is_local = provider.get() == 'Ollama · 내 PC'
            (local if is_local else cloud).pack(fill='x')
            note.set('내 PC에 설치한 모델로 분석합니다. API 키와 API 요금이 필요 없습니다.\n민감 후보는 로컬 모드에서도 승인 후 분석·이동합니다.\nQwen3 14B는 텍스트 모델이며 이미지 내용 분석은 지원하지 않습니다.' if is_local else
                     '허용된 파일명과 지원 내용이 OpenAI로 전송됩니다.\n민감 후보와 로컬 검사 불가 이미지는 먼저 검토 대기합니다.\n규칙 기반 검사여서 개인정보를 모두 탐지하지는 못합니다.')
        provider_box.bind('<<ComboboxSelected>>', select_provider)
        select_provider()
        def check_connection():
            if self.busy:
                return
            try:
                client = OllamaClient(host.get(), model.get())
            except ValueError as error:
                check_status.set(str(error))
                return
            check_status.set('Ollama 연결 확인 중…')
            inputs = (check_button, host_entry, model_entry, provider_box)
            for control in inputs:
                control.state(['disabled'])
            def task():
                try:
                    return client.check()
                except ValueError as error:
                    return str(error)
            def done(message):
                if dialog.winfo_exists():
                    check_status.set(message)
                    for control in inputs:
                        control.state(['!disabled'])
                self.status.set(message)
            self.run(task, done, cancellable=False)
        check_button.configure(command=check_connection)
        ttk.Checkbutton(frame, text='하위 폴더 포함', variable=recursive).pack(anchor='w')
        ttk.Checkbutton(frame, text='지원되는 파일 내용도 분석', variable=content).pack(anchor='w', pady=(4, 10))
        ttk.Label(frame, text='추가 민감 키워드').pack(anchor='w', pady=(0, 4))
        ttk.Entry(frame, textvariable=terms).pack(fill='x')
        ttk.Label(frame, text='쉼표로 구분하세요. 예: 회사명, 내부 프로젝트명', style='Muted.TLabel').pack(anchor='w', pady=(4, 10))
        ttk.Label(frame, textvariable=note,
                  style='Muted.TLabel', wraplength=480).pack(anchor='w')
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(16, 0))
        def save():
            if self.busy:
                return
            selected_provider = 'ollama' if provider.get() == 'Ollama · 내 PC' else 'openai'
            if selected_provider == 'ollama':
                try:
                    OllamaClient(host.get(), model.get())
                except ValueError as error:
                    check_status.set(str(error))
                    return
            self.key.set(key.get().strip())
            for target, draft in ((self.recursive, recursive), (self.use_content, content), (self.sensitive_terms, terms)):
                if target.get() != draft.get():
                    target.set(draft.get())
            for target, value in ((self.provider, selected_provider), (self.ollama_url, host.get().strip()),
                                  (self.ollama_model, model.get().strip())):
                if target.get() != value:
                    target.set(value)
            dialog.destroy()
        ttk.Button(actions, text='저장', style='Primary.TButton', command=save).pack(side='right')
        ttk.Button(actions, text='취소', command=dialog.destroy).pack(side='right', padx=8)
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        (model_entry if self.provider.get() == 'ollama' else key_entry).focus_set()

    def primary_action(self):
        if self.engine and self.engine.plan:
            self.apply()
        else:
            self.start(False)

    def update_actions(self):
        pending = self.engine.plan['items'] if self.engine and self.engine.plan else []
        count = sum(bool(i['selected']) for i in pending)
        has_plan = bool(self.engine and self.engine.plan)
        self.primary_button.configure(text=f'{count}개 파일 정리' if count else '검토 후 정리하세요' if has_plan else 'AI 분석 시작')
        self.primary_button.state(['disabled'] if self.busy or not self.folder.get().strip() or (has_plan and not count) else ['!disabled'])
        if self.view_items:
            self.reanalyze_button.pack(side='right', padx=(0, 8))
        else:
            self.reanalyze_button.pack_forget()
        self.location_button.state(['!disabled'] if not self.busy and self.library.selection() else ['disabled'])
        self.search_entry.state(['disabled'] if self.busy or self.library_mode.get() != '파일 검색' else ['!disabled'])

    def library_mode_changed(self):
        mode = self.library_mode.get()
        self.clear_library()
        self.search_button.configure(text='검색' if mode == '파일 검색' else '검사 시작')
        self.library_hint.set({'파일 검색': '파일명·요약·태그로 찾으세요. 검색어는 내 PC에만 머뭅니다.',
                               '중복 파일': '내용이 완전히 같은 파일을 찾습니다. 파일을 자동 삭제하지 않습니다.',
                               '유사 문서': '저장된 요약·태그의 공통 단어로 관련 문서를 찾습니다.'}[mode])
        self.update_actions()

    def run_library(self):
        {'파일 검색': self.search, '중복 파일': self.duplicates, '유사 문서': self.similar}[self.library_mode.get()]()

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
            self.clear_library()
            self.history_table.delete(*self.history_table.get_children())
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
            tag = 'moved' if state == '이동 완료' else 'held' if state == '검토 대기' else 'ready'
            row = self.table.insert('', 'end', values=('✓' if item['selected'] and state != '이동 완료' else '—',
                       relative, destination, state), tags=(tag,))
            self.rows[relative] = row
            if relative in selection:
                self.table.selection_add(row)
        items = list(self.view_items.values())
        moved = sum(item.get('display_state') == '이동 완료' for item in items)
        held = sum(item.get('review_required') and not item.get('approved_move') and item.get('display_state') != '이동 완료' for item in items)
        pending = self.engine.plan['items'] if self.engine and self.engine.plan else []
        for variable, value in zip(self.metrics, (len(items), sum(bool(i['selected']) for i in pending), held, moved)):
            variable.set(str(value))
        self.step.set('03  검토 후 정리 · 제안된 위치와 이름을 확인하세요' if pending else
                      '정리 완료 · 더 보기에서 마지막 작업을 되돌릴 수 있어요' if moved else
                      '01  폴더 선택    →    02  AI 분석    →    03  검토 후 정리')
        if not self.table.get_children():
            self.empty_title.configure(text='표시할 파일이 없어요' if items else '폴더 하나로 시작하세요')
            self.empty_copy.configure(text='다른 필터를 선택해 보세요.' if items else 'AI가 분류를 제안하면, 확인 후 정리할 수 있어요.')
            self.empty.place(relx=.5, rely=.52, anchor='center')
        else:
            self.empty.place_forget()
        self.show_details()
        self.update_actions()

    def selected_paths(self):
        chosen = set(self.table.selection())
        return [relative for relative, row in self.rows.items() if row in chosen]

    def show_details(self):
        paths = self.selected_paths()
        text = '목록에서 파일을 선택하면\n요약과 분류 이유를 확인할 수 있어요.\n\n민감 후보는 검토 대기로 남겨두며,\n직접 확인한 파일만 정리할 수 있습니다.'
        self.selection_title.set('파일 미리보기')
        self.detail_actions.grid_remove()
        self.edit_button.pack_forget()
        self.toggle_button.pack_forget()
        self.external_button.pack_forget()
        if paths:
            item = self.view_items[paths[0]]
            name = item['new_name']
            self.selection_title.set(f'{len(paths)}개 파일 선택' if len(paths) > 1 else name if len(name) <= 32 else name[:29] + '…')
            text = f"요약\n{item.get('summary') or '아직 저장된 요약이 없습니다.'}\n\n태그\n{', '.join(item.get('tags', [])) or '—'}\n\n현재 파일\n{paths[0]}\n\n정리할 위치\n{self.engine.output if self.engine else self.output_folder.get() or OUTPUT_NAME}/{item['folder']}/{name}\n\n분류 이유\n{item['reason']}\n\n분석 범위\n{item['scope']}\n\n검토 사유\n{'; '.join(item.get('review_reasons', [])) or '로컬 규칙에서 감지 없음'}"
            if item.get('review_required') and not item.get('approved_move'):
                text = '검토가 필요해요\n' + '; '.join(item.get('review_reasons', [])) + '\n\n' + text
            pending = {i['relative'] for i in self.engine.plan['items']} if self.engine and self.engine.plan else set()
            if all(path in pending for path in paths):
                self.detail_actions.grid()
                if len(paths) == 1:
                    self.edit_button.configure(text='검토·이동 승인' if item.get('review_required') else '분류·파일명 수정')
                    self.edit_button.pack(fill='x')
                else:
                    self.toggle_button.pack(fill='x')
                self.edit_button.state(['!disabled'] if len(paths) == 1 and not self.busy else ['disabled'])
                self.toggle_button.state(['disabled'] if self.busy else ['!disabled'])
                if len(paths) == 1 and item.get('review_required'):
                    self.external_button.configure(text='이 파일의 로컬 분석 허용' if self.provider.get() == 'ollama' else '이 파일의 AI 전송 허용')
                    self.external_button.pack(fill='x', pady=(6, 0))
                    self.external_button.state(['disabled'] if self.busy else ['!disabled'])
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def choose_folder(self):
        selected = filedialog.askdirectory(title='정리할 폴더 선택')
        if selected:
            self.folder.set(selected)

    def new_engine(self, ai=None):
        if not self.folder.get().strip():
            raise ValueError('대상 폴더를 선택하세요.')
        return FolderOrganizer(self.folder.get().strip(), self.recursive.get(), self.use_content.get(),
                               ai=ai, output=self.output_folder.get().strip() or None,
                               sensitive_terms=[term.strip() for term in self.sensitive_terms.get().split(',') if term.strip()])

    def report(self, stage, index, total, item):
        self.events.put(('progress', stage, index, total, dict(item)))

    def run(self, task, done, cancellable=True):
        if self.busy:
            return
        self.busy = True
        self.progress.grid()
        self.progress.configure(value=0)
        self.cancel_event.clear()
        for control in self.controls:
            control.state(['disabled'])
        if cancellable:
            self.cancel_button.state(['!disabled'])
            self.cancel_button.grid()
        self.update_actions()
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
        local = self.provider.get() == 'ollama'
        if not local and not self.key.get().strip():
            self.status.set('분석 설정에서 OpenAI API 키를 입력한 뒤 시작하세요.')
            self.open_settings()
            return
        try:
            client = OllamaClient(self.ollama_url.get(), self.ollama_model.get()) if local else None
            engine = self.new_engine(ai=client)
        except (ValueError, OSError) as error:
            messagebox.showerror('시작할 수 없음', str(error))
            return
        action = '검토 대기 파일을 제외하고 원본을 자동 이동합니다.' if automatic else '원본을 이동하지 않고 분석 결과를 표시합니다.'
        destination = f'내 PC의 Ollama ({client.model})로 파일명과 지원 내용을 분석합니다. 외부 AI로 자동 전환하지 않습니다.' if local else '로컬 사전 검사 후 허용 대상의 파일명·상대 경로와 선택한 지원 내용을 OpenAI로 전송합니다. API 비용이 발생합니다.'
        if not messagebox.askyesno('AI 분석 시작', f'{engine.root}\n\n{destination}\n{action}\n계속할까요?'):
            return
        if not local:
            os.environ['HOCHI_AI_KEY'] = self.key.get().strip()
        self.engine = engine
        self.clear_table()
        def task():
            if client:
                client.check()
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
        original_folder = item.get('ai_folder', item['folder'])
        selected, approved = tk.BooleanVar(value=item['selected']), tk.BooleanVar(value=item['approved_move'])
        ttk.Label(frame, text='분류 경로 (예: 수정한내용/수정한내용 · / 또는 \\ 사용 · 최대 3단계)').pack(anchor='w', pady=(12, 4))
        ttk.Entry(frame, textvariable=folder, width=58).pack(fill='x')
        ttk.Label(frame, text='이동 후 파일명').pack(anchor='w', pady=(10, 4))
        ttk.Entry(frame, textvariable=name).pack(fill='x')
        ttk.Checkbutton(frame, text='이 파일을 이동 대상에 포함', variable=selected).pack(anchor='w', pady=10)
        if item['review_required']:
            ttk.Label(frame, text='검토 사유: ' + '; '.join(item['review_reasons']), wraplength=550).pack(anchor='w')
            ttk.Checkbutton(frame, text='파일을 직접 검토했으며 로컬 이동을 승인합니다', variable=approved).pack(anchor='w', pady=8)
        remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='이 경로 수정을 내 분류 규칙으로 저장 (다음 분석부터 적용)', variable=remember).pack(anchor='w', pady=6)
        ttk.Label(frame, text='이 승인은 AI 분석을 허용하지 않습니다.', wraplength=550).pack(anchor='w', pady=6)
        def save():
            try:
                changed = self.engine.edit_item(paths[0], folder.get(), name.get(), selected.get(), approved.get())
                if remember.get():
                    self.engine.save_rule(original_folder, folder.get())
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
            local = self.provider.get() == 'ollama'
            if not local and not self.key.get().strip():
                raise ValueError('OpenAI API 키를 입력하세요.')
        except ValueError as error:
            messagebox.showerror('전송 불가', str(error))
            return
        destination = '내 PC의 Ollama에서 분석됩니다.' if local else 'OpenAI로 전송됩니다.'
        if not messagebox.askyesno('이 파일의 AI 분석 허용', f'{paths[0]}\n\n이 파일의 파일명·상대 경로와 선택한 지원 내용/이미지가 {destination} 민감정보가 포함될 수 있습니다.\n이 파일에 한해 분석을 허용할까요?\n이동 승인은 별도로 필요합니다.'):
            return
        if not local:
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
        include_previous = self.include_previous.get()
        def done(records):
            self.clear_library()
            for record in records:
                row = self.library.insert('', 'end', values=(record['current_path'], record['folder'], ', '.join(record['tags']), record['summary'] or record['reason']))
                self.library_items[row] = record['current_path']
            self.status.set(f'로컬 검색 {len(records)}개 결과 · 수정되거나 사라진 파일은 제외 · 검색어와 색인은 외부 전송 안 함')
        self.run(lambda: engine.search(query, include_previous), done, cancellable=False)

    def clear_library(self):
        self.library.delete(*self.library.get_children())
        self.library_items.clear()
        self.location_button.state(['disabled'])

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
            path = engine.resolve_record(self.library_items[selection[0]])
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
            self.history_table.delete(*self.history_table.get_children())
            for event in events:
                detail = event['detail']
                if 'moves' in detail:
                    moves = detail['moves']
                    description = f"{len(moves)}개 이동 · " + ' / '.join(f"{move['source']} → {move['target']}" for move in moves[:3])
                    if len(moves) > 3:
                        description += f" 외 {len(moves) - 3}개"
                elif 'folder' in detail:
                    description = f"{detail['file']} → {detail['folder']}/{detail['new_name']} · " + ('이동 포함' if detail['selected'] else '이동 제외')
                elif 'files' in detail:
                    description = f"{detail['files']}개 파일" + (f" · 검토 대기 {detail['held']}개" if 'held' in detail else '')
                else:
                    description = detail.get('file', '작업 완료')
                self.history_table.insert('', 'end', values=(event['time'][:19].replace('T', ' '), event['kind'], description))
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
                self.cancel_button.grid_remove()
                self.progress.grid_remove()
                if redraw:
                    self.render()
                    redraw = False
                if error:
                    if done == self.show_versions:
                        self.monitor_enabled.set(False)
                        self.monitor_hint.set('감시 중지: ' + str(error))
                    for item in self.view_items.values():
                        item['display_state'] = '작업 중단'
                    self.render()
                    self.status.set(('취소: ' if isinstance(error, Cancelled) else '작업 실패: ') + str(error))
                    if not isinstance(error, Cancelled):
                        messagebox.showerror('작업 실패', str(error))
                else:
                    done(result)
                    self.render()
                self.update_actions()
        if redraw:
            self.render()
        self.poll_id = self.root.after(80, self.poll)

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
        self.root.after_cancel(self.poll_id)
        self.root.after_cancel(self.monitor_id)
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
