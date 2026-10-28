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
        self.monitor_hint = tk.StringVar(value='감시는 선택 기능이에요. 켜면 원본·보관 폴더의 변경을 30초마다 확인합니다.')
        self.destination_hint = tk.StringVar(value='저장 위치: 작업 폴더/AI_정리')
        self.include_previous = tk.BooleanVar(value=False)
        self.version_items = {}
        self.project_output_draft = tk.StringVar()
        self.project_days_draft = tk.StringVar(value='7')
        self.project_notice = tk.StringVar(value='상단에서 작업 폴더를 선택한 뒤 설정을 저장하세요.')

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
        self.reset_project_draft()

    def open_project_settings(self):
        self.navigate(4)

    def reset_project_draft(self):
        source = self.folder.get().strip()
        self.project_output_draft.set(self.output_folder.get() or (str(Path(source).expanduser() / OUTPUT_NAME) if source else ''))
        self.project_days_draft.set(str(self.quiet_days.get()))
        self.project_notice.set('① 상단에서 원본 폴더 선택  ② 보관 폴더 지정  ③ 설정 저장 후 파일 정리 화면으로 이동')

    def build_project_settings(self, panel):
        panel.columnconfigure(0, weight=1)
        frame = ttk.Frame(panel, style='Card.TFrame', padding=20)
        frame.grid(row=0, column=0, sticky='ew')
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text='정리한 파일을 보관할 폴더', style='Section.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(frame, text='파일 이동을 누르면 이곳에 분류별 폴더가 만들어집니다.', style='CardMuted.TLabel').grid(row=1, column=0, sticky='w', pady=(4, 10))
        output_entry = ttk.Entry(frame, textvariable=self.project_output_draft)
        output_entry.grid(row=2, column=0, sticky='ew', padx=(0, 8))
        def browse():
            selected = filedialog.askdirectory(parent=self.root, title='저장할 디스크와 폴더 선택')
            if selected:
                self.project_output_draft.set(selected)
        browse_button = ttk.Button(frame, text='저장 폴더 선택', command=browse)
        browse_button.grid(row=2, column=1)
        ttk.Label(frame, text='버전 관리 · 최종본 후보 대기 기간', style='Section.TLabel').grid(row=3, column=0, sticky='w', pady=(18, 8))
        period = ttk.Frame(frame, style='Card.TFrame')
        period.grid(row=4, column=0, sticky='w')
        days = ttk.Spinbox(period, from_=1, to=365, textvariable=self.project_days_draft, width=8)
        days.pack(side='left')
        ttk.Label(period, text='일 동안 수정이 없으면 최종본 후보로 표시 (1~365일)', style='CardMuted.TLabel').pack(side='left', padx=10)
        ttk.Label(frame, text='후보는 추천이에요. 실제 사용할 최종본은 직접 선택하세요.\n'
                  '저장 위치를 바꿔도 기존 파일과 기록은 이전 위치에 남습니다.',
                  style='CardMuted.TLabel').grid(row=5, column=0, columnspan=2, sticky='w', pady=(14, 0))
        actions = ttk.Frame(panel)
        actions.grid(row=1, column=0, sticky='ew', pady=14)
        self.project_save_button = ttk.Button(actions, text='설정 저장', style='Primary.TButton', command=self.save_project_settings)
        self.project_save_button.pack(side='right')
        ttk.Button(actions, text='파일 정리 화면으로 →', command=lambda: self.navigate(0)).pack(side='left')
        reset = ttk.Button(actions, text='변경 취소', command=self.reset_project_draft)
        reset.pack(side='right', padx=8)
        self.controls += [output_entry, browse_button, days, self.project_save_button, reset]
        ttk.Label(panel, textvariable=self.project_notice, style='Muted.TLabel', wraplength=850).grid(row=2, column=0, sticky='w')

    def save_project_settings(self):
        if self.busy:
            return
        try:
            source = self.folder.get().strip()
            if not source:
                raise ValueError('상단에서 작업 폴더를 먼저 선택하세요.')
            output = self.project_output_draft.get().strip()
            if not output:
                raise ValueError('저장할 폴더를 지정하세요.')
            updated = FolderOrganizer(source, output=output)
            previous_output = Path(self.output_folder.get()).expanduser().absolute() if self.output_folder.get() else updated.root / OUTPUT_NAME
            output_changed = updated.output != previous_output
            had_plan = bool(self.engine and self.engine.plan)
            save_project(updated, self.project_days_draft.get())
            self.quiet_days.set(int(self.project_days_draft.get()))
            if output_changed:
                self.monitor_enabled.set(False)
                self.output_folder.set(str(updated.output))
                self.version_table.delete(*self.version_table.get_children())
                self.version_items.clear()
                self.monitor_hint.set('저장 위치 변경 · 버전 관리에서 감시를 다시 시작하세요.')
            self.destination_hint.set('저장 위치: ' + str(updated.output))
            self.reset_project_draft()
            message = '저장 완료 · AI 분석은 파일 정리, 감시는 버전 관리에서 시작하세요.'
            if output_changed and had_plan:
                message += ' 저장 위치가 바뀌어 기존 분류 계획은 다시 분석해야 합니다.'
            self.project_notice.set(message)
            self.status.set('저장·감시 설정 저장 완료')
        except (ValueError, OSError) as error:
            self.project_notice.set('저장 실패: ' + str(error))
            messagebox.showerror('설정 저장 실패', str(error))

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
                              f'{self.quiet_days.get()}일 변경 없음 → 후보 표시 · Ctrl/Shift로 여러 파일을 골라 묶으세요.')
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
