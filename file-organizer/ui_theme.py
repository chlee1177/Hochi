"""Shared desktop palette and native ttk styles; no extra UI dependency."""
import os
from tkinter import font as tkfont, ttk

BG = '#F4F7FB'
SURFACE = '#FFFFFF'
INK = '#17233A'
MUTED = '#607086'
LINE = '#E2E8F1'
BLUE = '#1E66F5'
NAVY = '#14243E'


def configure(root):
    family = '맑은 고딕' if os.name == 'nt' else 'Noto Sans CJK KR'
    root.configure(background=BG)
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
        tkfont.nametofont(name).configure(family=family, size=10)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=(family, 10), background=BG, foreground=INK)
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=SURFACE)
    style.configure('TLabel', background=BG)
    style.configure('Card.TLabel', background=SURFACE)
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('CardMuted.TLabel', background=SURFACE, foreground=MUTED, font=(family, 9))
    style.configure('Title.TLabel', font=(family, 24, 'bold'))
    style.configure('Section.TLabel', background=SURFACE, font=(family, 12, 'bold'))
    style.configure('Metric.TLabel', background=SURFACE, font=(family, 22, 'bold'))
    style.configure('Blue.Metric.TLabel', foreground=BLUE)
    style.configure('Amber.Metric.TLabel', foreground='#A76608')
    style.configure('Green.Metric.TLabel', foreground='#15806A')
    style.configure('TButton', padding=(14, 9), background=SURFACE, foreground=INK,
                    bordercolor=LINE, lightcolor=SURFACE, darkcolor=SURFACE, borderwidth=1)
    style.map('TButton', background=[('disabled', '#F1F4F8'), ('pressed', '#E3ECFC'), ('active', '#EDF3FF')],
              foreground=[('disabled', '#8794A7')], bordercolor=[('focus', BLUE)])
    style.configure('Primary.TButton', background=BLUE, foreground='white', bordercolor=BLUE,
                    lightcolor=BLUE, darkcolor=BLUE, font=(family, 10, 'bold'))
    style.map('Primary.TButton', background=[('disabled', '#E6EBF3'), ('pressed', '#174DB8'), ('active', '#1857D7')],
              foreground=[('disabled', '#7A879B'), ('!disabled', 'white')],
              bordercolor=[('disabled', '#E6EBF3'), ('!disabled', BLUE)])
    style.configure('Quiet.TButton', background=BG, borderwidth=0)
    style.configure('TMenubutton', padding=(12, 9), background=SURFACE, bordercolor=LINE)
    style.configure('TEntry', padding=9, fieldbackground=SURFACE, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE)
    style.map('TEntry', bordercolor=[('focus', BLUE)])
    style.configure('TCombobox', padding=7, fieldbackground=SURFACE, background=SURFACE,
                    bordercolor=LINE, arrowcolor=MUTED)
    style.map('TCombobox', fieldbackground=[('readonly', SURFACE)],
              foreground=[('readonly', INK)], selectbackground=[('readonly', SURFACE)],
              selectforeground=[('readonly', INK)])
    style.configure('TCheckbutton', padding=4)
    style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, foreground=INK,
                    rowheight=42, borderwidth=0, font=(family, 10))
    style.configure('Treeview.Heading', background='#F4F7FC', foreground=MUTED,
                    padding=(10, 10), borderwidth=0, font=(family, 9, 'bold'), relief='flat')
    style.map('Treeview', background=[('selected', '#E8F0FF')], foreground=[('selected', '#184EA4')])
    style.map('Treeview.Heading', background=[('active', '#EAF0FA')])
    style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
    style.configure('Horizontal.TProgressbar', background=BLUE, troughcolor='#E5EBF5',
                    borderwidth=0, lightcolor=BLUE, darkcolor=BLUE, thickness=4)
    style.layout('Workspace.TNotebook.Tab', [])
    style.configure('Workspace.TNotebook', background=BG, borderwidth=0, tabmargins=0,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.configure('Vertical.TScrollbar', arrowsize=12, background='#D4DDEB', borderwidth=0,
                    troughcolor=SURFACE)
    return family
