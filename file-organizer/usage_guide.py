"""Short in-app instructions; opening help does not start a task."""
import tkinter as tk
from tkinter import ttk


def show_guide(app):
    existing = getattr(app, 'help_dialog', None)
    if existing and existing.winfo_exists():
        existing.lift()
        return
    if app.root.grab_current():
        return
    dialog = app.help_dialog = tk.Toplevel(app.root)
    dialog.title('FileNest 사용 안내')
    dialog.transient(app.root)
    dialog.resizable(False, False)
    dialog.grab_set()
    frame = ttk.Frame(dialog, padding=22)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='처음이라면 이 순서로', style='Title.TLabel').pack(anchor='w', pady=(0, 14))
    steps = [
        ('1. 저장 위치 설정', '왼쪽 저장·감시 설정에서 원본 폴더와 보관 폴더를 고르고 설정 저장을 누르세요.'),
        ('2. AI 연결 확인', '파일 정리 → AI 연결·분석 설정에서 모델을 확인하세요. Ollama는 연결 확인 후 저장합니다.'),
        ('3. 분석하고 확인한 파일만 이동', 'AI 분석 시작은 제안만 만듭니다. 목록에서 분류를 수정한 뒤 N개 파일 이동을 누르세요.'),
        ('4. 버전 감시는 필요할 때', '버전 관리에서 감시를 켜세요. 같은 문서를 묶고 사용할 최종본을 직접 선택합니다.'),
    ]
    for title, copy in steps:
        card = ttk.Frame(frame, style='Card.TFrame', padding=(14, 10))
        card.pack(fill='x', pady=(0, 8))
        ttk.Label(card, text=title, style='Section.TLabel').pack(anchor='w')
        ttk.Label(card, text=copy, style='CardMuted.TLabel', wraplength=480).pack(anchor='w', pady=(4, 0))
    ttk.Label(frame, text='검토 대기: 직접 확인이 필요해요.  건너뜀: 원래 위치에 남아요.\n'
              '최종본 후보는 추천일 뿐이에요. 잘못 이동했다면 작업 기록에서 되돌릴 수 있어요.',
              style='Muted.TLabel', wraplength=510).pack(anchor='w', pady=(6, 12))
    ttk.Button(frame, text='닫기', command=dialog.destroy).pack(anchor='e')
    dialog.bind('<Escape>', lambda _: dialog.destroy())
