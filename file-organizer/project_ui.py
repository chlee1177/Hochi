"""Destination preferences, editable classification rules and version review UI."""
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from folder_organizer import FolderOrganizer, OUTPUT_NAME
from project import load_project, save_project
from versions import VersionMonitor


class ProjectUI:
    def init_project(self):
        self.output_folder = tk.StringVar()
        self.quiet_days = tk.IntVar(value=7)
        self.monitor_enabled = tk.BooleanVar(value=False)
        self.monitor_hint = tk.StringVar(value='감시를 시작하면 작업 폴더와 저장 폴더를 30초마다 확인합니다.')
        self.destination_hint = tk.StringVar(value='저장 위치: 작업 폴더/AI_정리')
        self.include_previous = tk.BooleanVar(value=False)
        self.version_items = {}

    def project_changed(self, *_):
        self.monitor_enabled.set(False)
        self.version_items.clear()
        self.version_table.delete(*self.version_table.get_children())
        self.output_folder.set('')
        self.quiet_days.set(7)
        self.monitor_hint.set('감시 중지 · 선택한 작업 폴더에서 감시를 시작하세요.')
        try:
            if self.folder.get().strip() and Path(self.folder.get().strip()).is_dir():
                config = load_project(self.folder.get().strip())
                self.output_folder.set(config['output'])
                self.quiet_days.set(config['quiet_days'])
        except (ValueError, OSError) as error:
            self.monitor_hint.set('설정 읽기 실패: ' + str(error))
        self.destination_hint.set('저장 위치: ' + (self.output_folder.get() or '작업 폴더/' + OUTPUT_NAME))

    def open_project_settings(self):
        if self.busy:
            return
        try:
            engine = self.new_engine()
        except (ValueError, OSError) as error:
            messagebox.showerror('설정 불가', str(error))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('저장 위치와 감시 설정')
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)
        output = tk.StringVar(value=str(engine.output))
        days = tk.StringVar(value=str(self.quiet_days.get()))
        ttk.Label(frame, text='분류한 파일을 저장할 폴더', style='Section.TLabel').pack(anchor='w')
        ttk.Entry(frame, textvariable=output, width=68).pack(fill='x', pady=8)
        def browse():
            selected = filedialog.askdirectory(parent=dialog, title='저장할 디스크와 폴더 선택')
            if selected:
                output.set(selected)
        ttk.Button(frame, text='저장 폴더 선택', command=browse).pack(anchor='e')
        ttk.Label(frame, text='최종본 후보 대기 기간 (1~365일)').pack(anchor='w', pady=(14, 6))
        ttk.Spinbox(frame, from_=1, to=365, textvariable=days, width=8).pack(anchor='w')
        ttk.Label(frame, text='감시를 시작한 뒤 변경이 없는 기간을 기준으로 후보를 표시합니다.\n'
                  '실제로 열거나 제출한 파일을 자동 판별하지 않습니다.\n'
                  '저장 위치를 바꿔도 기존 파일과 기록은 이전 위치에 남습니다.',
                  style='Muted.TLabel').pack(anchor='w', pady=14)
        def save():
            try:
                if not output.get().strip():
                    raise ValueError('저장할 폴더를 지정하세요.')
                updated = FolderOrganizer(engine.root, output=output.get().strip())
                save_project(updated, days.get())
                self.monitor_enabled.set(False)
                self.output_folder.set(str(updated.output))
                self.quiet_days.set(int(days.get()))
                self.destination_hint.set('저장 위치: ' + str(updated.output))
                self.invalidate()
                self.version_table.delete(*self.version_table.get_children())
                self.version_items.clear()
                self.monitor_hint.set('설정 저장 완료 · 감시를 다시 시작하세요.')
                dialog.destroy()
            except (ValueError, OSError) as error:
                messagebox.showerror('저장 실패', str(error), parent=dialog)
        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        ttk.Button(actions, text='저장', style='Primary.TButton', command=save).pack(side='right')
        ttk.Button(actions, text='취소', command=dialog.destroy).pack(side='right', padx=8)

    def open_rules(self):
        if self.busy:
            return
        try:
            engine = self.new_engine()
            rules = engine.rules()
        except (ValueError, OSError) as error:
            messagebox.showerror('분류 규칙', str(error))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('내 분류 규칙')
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='AI 제안 경로를 내가 정한 경로로 바꿉니다.', style='Section.TLabel').pack(anchor='w')
        table = ttk.Treeview(frame, columns=('source', 'target'), show='headings', height=7)
        table.heading('source', text='AI 제안 경로 (정확히 일치)')
        table.heading('target', text='내 분류 경로')
        table.pack(fill='both', expand=True, pady=12)
        original, target = tk.StringVar(), tk.StringVar()
        ttk.Label(frame, text='AI 제안 경로 · 예: 대학교/과목명').pack(anchor='w')
        ttk.Entry(frame, textvariable=original, width=65).pack(fill='x', pady=(4, 10))
        ttk.Label(frame, text='내 분류 경로 · 예: 수정한내용/수정한내용').pack(anchor='w')
        ttk.Entry(frame, textvariable=target).pack(fill='x', pady=(4, 10))
        ttk.Label(frame, text='슬래시(/)와 역슬래시(\\) 모두 사용 가능 · 최대 3단계\n'
                  '다음 AI 분석부터 적용합니다. 현재 검토 목록과 이미 이동한 파일은 바뀌지 않습니다.',
                  style='Muted.TLabel').pack(anchor='w')
        def render(values):
            table.delete(*table.get_children())
            for source, destination in values.items():
                table.insert('', 'end', values=(source, destination))
        def selected(_):
            if table.selection():
                a, b = table.item(table.selection()[0], 'values')
                original.set(a)
                target.set(b)
        table.bind('<<TreeviewSelect>>', selected)
        def save(delete=False):
            try:
                values = engine.save_rule(original.get(), None if delete else target.get())
                render(values)
                self.status.set('분류 규칙 저장 완료 · 다음 AI 분석부터 적용됩니다.')
            except (ValueError, OSError) as error:
                messagebox.showerror('규칙 저장 실패', str(error), parent=dialog)
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(12, 0))
        ttk.Button(actions, text='규칙 삭제', command=lambda: save(True)).pack(side='left')
        ttk.Button(actions, text='규칙 저장', style='Primary.TButton', command=save).pack(side='right')
        ttk.Button(actions, text='닫기', command=dialog.destroy).pack(side='right', padx=8)
        render(rules)

    def build_versions(self, panel):
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(panel)
        toolbar.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        toggle = ttk.Checkbutton(toolbar, text='폴더 감시 켜기', variable=self.monitor_enabled, command=self.toggle_monitor)
        toggle.pack(side='left')
        refresh = ttk.Button(toolbar, text='지금 확인', command=self.refresh_versions)
        refresh.pack(side='right')
        self.controls += [toggle, refresh]
        ttk.Label(panel, textvariable=self.monitor_hint, style='Muted.TLabel', wraplength=850).grid(row=1, column=0, sticky='w', pady=(0, 10))
        self.version_table = self.make_table(panel, [('file', '파일', 245), ('group', '문서 묶음 / 제안', 170),
                                                   ('state', '상태 태그', 115), ('date', '변경 관찰 시각', 145),
                                                   ('warning', '확인할 내용', 240)], row=2)
        self.version_table.bind('<<TreeviewSelect>>', self.version_selection)
        actions = ttk.Frame(panel)
        actions.grid(row=3, column=0, sticky='ew', pady=(12, 0))
        for label, command in [('같은 문서로 묶기', lambda: self.version_action('group')),
                               ('최종본 확정', lambda: self.version_action('confirm'))]:
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side='left', padx=(0, 8))
            self.controls.append(button)
        more = ttk.Menubutton(actions, text='더 보기')
        menu = tk.Menu(more, tearoff=False)
        menu.add_command(label='최종본 확정 해제', command=lambda: self.version_action('release'))
        menu.add_command(label='선택 파일 묶음에서 분리', command=lambda: self.version_action('ungroup'))
        more.configure(menu=menu)
        more.pack(side='right')
        self.controls.append(more)

    def toggle_monitor(self):
        if self.monitor_enabled.get():
            self.refresh_versions()
        else:
            self.monitor_hint.set('감시 중지 · 기록과 태그는 유지됩니다.')

    def monitor_tick(self):
        if self.monitor_enabled.get() and not self.busy and not self.root.grab_current():
            self.refresh_versions()
        self.monitor_id = self.root.after(30000, self.monitor_tick)

    def show_versions(self, rows):
        selected = {self.version_items[r]['path'] for r in self.version_table.selection() if r in self.version_items}
        self.version_table.delete(*self.version_table.get_children())
        self.version_items.clear()
        for item in rows:
            row = self.version_table.insert('', 'end', values=(Path(item['path']).name, item['group_name'] or '묶음 제안: ' + item['suggestion'],
                item['version_state'], datetime.fromtimestamp(item['changed_at']).strftime('%m-%d %H:%M'), item['warning'] or item.get('related', '')))
            self.version_items[row] = item
            if item['path'] in selected:
                self.version_table.selection_add(row)
        self.monitor_hint.set(f"{'감시 중 · 30초 간격' if self.monitor_enabled.get() else '수동 확인'} · {len(rows)}개 · "
                              f'{self.quiet_days.get()}일 변경 없음 → 최종본 후보 · 묶음 제안은 직접 확인 후 묶으세요.')
        self.status.set('버전 기록 갱신 완료 · 자동 AI 전송·파일 이동 없음 · 프로그램 종료 시 감시 중지')

    def version_selection(self, _=None):
        selected = [self.version_items[r] for r in self.version_table.selection() if r in self.version_items]
        if selected:
            self.status.set(f"{len(selected)}개 선택 · {selected[0]['path']}" +
                            (' · ' + selected[0]['warning'] if selected[0]['warning'] else ''))

    def refresh_versions(self):
        if self.busy:
            return
        try:
            monitor = VersionMonitor(self.new_engine(), self.quiet_days.get())
        except (ValueError, OSError) as error:
            self.monitor_enabled.set(False)
            messagebox.showerror('감시 시작 실패', str(error))
            return
        self.run(lambda: monitor.refresh(self.cancel_event), self.show_versions)

    def version_action(self, action):
        if self.busy:
            return
        paths = [self.version_items[row]['path'] for row in self.version_table.selection() if row in self.version_items]
        if not paths or (action == 'confirm' and len(paths) != 1):
            messagebox.showinfo('파일 선택', '최종본은 하나, 묶을 파일은 두 개 이상 선택하세요.')
            return
        try:
            monitor = VersionMonitor(self.new_engine(), self.quiet_days.get())
        except (ValueError, OSError) as error:
            messagebox.showerror('버전 관리', str(error))
            return
        if action == 'group':
            if len(paths) < 2:
                messagebox.showinfo('파일 선택', '같은 문서의 파일을 두 개 이상 선택하세요.')
                return
            name = simpledialog.askstring('같은 문서로 묶기', '직접 확인한 문서 묶음의 이름을 입력하세요.\n선택한 파일의 기존 최종본 지정은 새 묶음에 승계하지 않습니다.', parent=self.root)
            if name is None:
                return
            task = lambda: monitor.group(paths, name)
        elif action == 'confirm':
            if not messagebox.askyesno('최종본 확정', paths[0] + '\n\n이 파일을 해당 묶음의 최종본으로 지정할까요? 다른 버전은 기본 검색에서 제외됩니다.'):
                return
            task = lambda: monitor.confirm(paths[0])
        else:
            task = lambda: monitor.release(paths, ungroup=action == 'ungroup')
        self.run(task, self.show_versions, cancellable=False)
