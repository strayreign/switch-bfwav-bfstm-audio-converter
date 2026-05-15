#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# BFWAV Little-Endian Converter
# GUI tool for converting Nintendo Switch BFWAV audio files
# from big-endian (Wii U) to little-endian (Switch) format.
#
# Based on BCFSTM-BCFWAV Converter v2.1 by AboodXD (GPL-3.0)
# GUI & packaging by Samuel Dyson
#

import os
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import windnd

from converter_core import process_file, get_bom

# ── palette ──────────────────────────────────────────────────────────────────
BG       = '#12121a'
PANEL    = '#1c1c2e'
ACCENT   = '#7c6af7'
ACCENT2  = '#a78bfa'
SUCCESS  = '#4ade80'
WARN     = '#facc15'
ERROR    = '#f87171'
SKIP     = '#94a3b8'
FG       = '#e2e8f0'
FG_DIM   = '#64748b'
BORDER   = '#2d2d44'
BTN_BG   = '#2d2d44'
BTN_HOV  = '#3d3d5c'


class HoverButton(tk.Label):
    """Flat button with hover highlight."""
    def __init__(self, parent, text, command, bg=BTN_BG, fg=FG,
                 hbg=BTN_HOV, pad=(18, 8), **kw):
        super().__init__(
            parent, text=text, bg=bg, fg=fg,
            padx=pad[0], pady=pad[1], cursor='hand2',
            font=('Segoe UI', 10, 'bold'), **kw
        )
        self._cmd  = command
        self._bg   = bg
        self._hbg  = hbg
        self.bind('<Enter>',    lambda e: self.config(bg=self._hbg))
        self.bind('<Leave>',    lambda e: self.config(bg=self._bg))
        self.bind('<Button-1>', lambda e: self._cmd())

    def set_state(self, enabled: bool):
        if enabled:
            self.config(cursor='hand2')
            self.bind('<Button-1>', lambda e: self._cmd())
        else:
            self.config(cursor='')
            self.unbind('<Button-1>')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('BFWAV Little-Endian Converter')
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(660, 480)

        self._files      = []   # list of absolute paths
        self._converting = False

        self._build_ui()
        self._set_icon('switch_purple.png')
        self._center()

    # ── layout ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # header
        hdr = tk.Frame(self, bg=PANEL, pady=16)
        hdr.grid(row=0, column=0, sticky='ew')
        tk.Label(hdr, text='BFWAV Little-Endian Converter',
                 bg=PANEL, fg=ACCENT2,
                 font=('Segoe UI', 18, 'bold')).pack()
        tk.Label(hdr, text='Big-endian → Little-endian  |  For Nintendo Switch mods',
                 bg=PANEL, fg=FG_DIM,
                 font=('Segoe UI', 9)).pack(pady=(2, 0))
        credit = tk.Label(hdr, text='Created by strayreign',
                          bg=PANEL, fg=FG_DIM, font=('Segoe UI', 8),
                          cursor='hand2')
        credit.pack(pady=(4, 0))
        credit.bind('<Button-1>', lambda e: webbrowser.open('https://www.strayreign.com'))

        # toolbar
        bar = tk.Frame(self, bg=BG, pady=10, padx=12)
        bar.grid(row=1, column=0, sticky='ew')

        HoverButton(bar, '＋ Add Files',   self._add_files,  bg=ACCENT,  hbg='#6d5ee0').pack(side='left', padx=(0, 6))
        HoverButton(bar, '📂 Add Folder',  self._add_folder).pack(side='left', padx=(0, 6))
        HoverButton(bar, '✕ Clear List',   self._clear_list).pack(side='left')

        self._convert_btn = HoverButton(
            bar, '⚡ Convert', self._start_conversion,
            bg=ACCENT, hbg='#6d5ee0', fg='#ffffff'
        )
        self._convert_btn.pack(side='right')

        # file list
        list_frame = tk.Frame(self, bg=PANEL, padx=1, pady=1)
        list_frame.grid(row=2, column=0, sticky='nsew', padx=12, pady=(0, 6))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        cols = ('file', 'endian', 'status')
        self._tree = ttk.Treeview(list_frame, columns=cols, show='headings',
                                   selectmode='extended')
        self._tree.heading('file',   text='File')
        self._tree.heading('endian', text='Current BOM')
        self._tree.heading('status', text='Status')
        self._tree.column('file',   width=360, stretch=True)
        self._tree.column('endian', width=120, anchor='center', stretch=False)
        self._tree.column('status', width=160, anchor='center', stretch=False)

        style = ttk.Style(self)
        style.theme_use('default')
        style.configure('Treeview',
                         background=PANEL, foreground=FG,
                         fieldbackground=PANEL, rowheight=26,
                         borderwidth=0, font=('Segoe UI', 9))
        style.configure('Treeview.Heading',
                         background=BG, foreground=ACCENT2,
                         borderwidth=0, font=('Segoe UI', 9, 'bold'))
        style.map('Treeview', background=[('selected', '#2d2d55')])

        vsb = ttk.Scrollbar(list_frame, orient='vertical',
                             command=self._tree.yview)
        self._tree.configure(yscrollcommand=self._autoscroll(vsb))
        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        vsb.grid_remove()

        self._tree.tag_configure('be',      foreground=WARN)
        self._tree.tag_configure('le',      foreground=SKIP)
        self._tree.tag_configure('done',    foreground=SUCCESS)
        self._tree.tag_configure('skipped', foreground=SKIP)
        self._tree.tag_configure('error',   foreground=ERROR)

        self._tree.bind('<Button-3>', self._on_right_click)

        windnd.hook_dropfiles(self, func=self._on_drop)

        # progress + status bar
        bot = tk.Frame(self, bg=BG, padx=12, pady=8)
        bot.grid(row=3, column=0, sticky='ew')
        bot.columnconfigure(0, weight=1)

        self._progress = ttk.Progressbar(bot, mode='determinate',
                                          style='custom.Horizontal.TProgressbar')
        style.configure('custom.Horizontal.TProgressbar',
                         troughcolor=BORDER, background=ACCENT,
                         thickness=6)
        self._progress.grid(row=0, column=0, sticky='ew', pady=(0, 4))

        self._status_var = tk.StringVar(value='Add .bfwav files or a folder to get started.')
        tk.Label(bot, textvariable=self._status_var,
                 bg=BG, fg=FG_DIM,
                 font=('Segoe UI', 9), anchor='w').grid(row=1, column=0, sticky='w')

        self._count_var = tk.StringVar(value='0 files')
        tk.Label(bot, textvariable=self._count_var,
                 bg=BG, fg=FG_DIM,
                 font=('Segoe UI', 9), anchor='e').grid(row=1, column=1, sticky='e')

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _autoscroll(vsb):
        def _set(lo, hi):
            if float(lo) <= 0.0 and float(hi) >= 1.0:
                vsb.grid_remove()
            else:
                vsb.grid()
            vsb.set(lo, hi)
        return _set

    def _on_right_click(self, event):
        if self._converting:
            return
        row = self._tree.identify_row(event.y)
        if not row:
            return
        if row not in self._tree.selection():
            self._tree.selection_set(row)
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=FG,
                       activebackground=ACCENT, activeforeground='#ffffff',
                       bd=0, font=('Segoe UI', 9))
        menu.add_command(label='Remove from list', command=self._remove_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _remove_selected(self):
        for iid in self._tree.selection():
            self._tree.delete(iid)
            if iid in self._files:
                self._files.remove(iid)
        self._refresh_count()

    # ── file management ───────────────────────────────────────────────────────

    def _bom_label(self, path):
        try:
            with open(path, 'rb') as fh:
                header = fh.read(6)
            bom = get_bom(header)
            if bom == '>':
                return 'Big-endian (BE)', 'be'
            elif bom == '<':
                return 'Little-endian (LE)', 'le'
            return 'Unknown', ''
        except Exception:
            return 'Read error', 'error'

    def _add_paths(self, paths):
        existing = set(self._files)
        added = 0
        for p in paths:
            if p not in existing and p.lower().endswith('.bfwav'):
                self._files.append(p)
                existing.add(p)
                bom_txt, tag = self._bom_label(p)
                self._tree.insert('', 'end', iid=p, values=(
                    os.path.basename(p), bom_txt, '—'
                ), tags=(tag,))
                added += 1
        if added:
            self._refresh_count()

    def _on_drop(self, files):
        found = []
        for f in files:
            p = f.decode('utf-8') if isinstance(f, bytes) else f
            if os.path.isdir(p):
                for root, _, names in os.walk(p):
                    for n in names:
                        if n.lower().endswith('.bfwav'):
                            found.append(os.path.join(root, n))
            elif p.lower().endswith('.bfwav'):
                found.append(p)
        self._add_paths(found)

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title='Select .bfwav files',
            filetypes=[('BFWAV files', '*.bfwav'), ('All files', '*.*')]
        )
        self._add_paths(list(paths))

    def _add_folder(self):
        folder = filedialog.askdirectory(title='Select folder containing .bfwav files')
        if not folder:
            return
        found = []
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith('.bfwav'):
                    found.append(os.path.join(root, f))
        if not found:
            messagebox.showinfo('No files found',
                                'No .bfwav files were found in the selected folder.')
            return
        self._add_paths(found)
        self._status(f'Added {len(found)} file(s) from folder.')

    def _clear_list(self):
        if self._converting:
            return
        self._files.clear()
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._refresh_count()
        self._progress['value'] = 0
        self._status('List cleared.')

    def _refresh_count(self):
        n = len(self._files)
        self._count_var.set(f'{n} file{"s" if n != 1 else ""}')

    def _status(self, msg):
        self._status_var.set(msg)

    # ── conversion ────────────────────────────────────────────────────────────

    def _start_conversion(self):
        if self._converting:
            return
        if not self._files:
            messagebox.showinfo('Nothing to convert',
                                'Add some .bfwav files first.')
            return

        be_files = []
        for p in self._files:
            try:
                with open(p, 'rb') as fh:
                    bom = get_bom(fh.read(6))
                if bom == '>':
                    be_files.append(p)
            except Exception:
                pass

        if not be_files:
            messagebox.showinfo('Nothing to convert',
                                'All files are already little-endian.')
            return

        self._converting = True
        self._convert_btn.set_state(False)
        self._convert_btn.config(fg=FG_DIM)
        self._progress['maximum'] = len(be_files)
        self._progress['value']   = 0

        threading.Thread(target=self._run_conversion,
                         args=(be_files,), daemon=True).start()

    def _run_conversion(self, files):
        done = 0
        errors = 0

        for path in files:
            self._status(f'Converting: {os.path.basename(path)}')
            try:
                converted, msg = process_file(path)
                tag    = 'done'    if converted else 'skipped'
                status = '✔ Done'  if converted else '↷ Skipped'
                bom_txt = 'Little-endian (LE)' if converted else self._bom_label(path)[0]
            except Exception as exc:
                tag     = 'error'
                status  = f'✘ Error'
                bom_txt = 'Error'
                errors += 1
                print(f'[ERROR] {path}: {exc}')

            self._tree.item(path, values=(os.path.basename(path), bom_txt, status),
                            tags=(tag,))
            done += 1
            self._progress['value'] = done
            self.update_idletasks()

        total = len(files)
        ok    = total - errors
        self._status(
            f'Done! {ok}/{total} file(s) converted successfully.'
            + (f'  ({errors} error(s) — check console)' if errors else '')
        )
        self._converting = False
        self._convert_btn.set_state(True)
        self._convert_btn.config(fg='#ffffff')

    # ── utils ─────────────────────────────────────────────────────────────────

    def _set_icon(self, filename):
        try:
            from PIL import Image, ImageTk
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
            path = os.path.join(base, filename)
            img  = Image.open(path)
            sizes = [16, 32, 48, 64, 128, 256]
            icons = [ImageTk.PhotoImage(img.resize((s, s), Image.LANCZOS)) for s in sizes]
            self.iconphoto(True, *icons)
            self._icons = icons  # prevent GC
        except Exception:
            pass

    def _center(self):
        self.update_idletasks()
        w, h = 700, 520
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')


if __name__ == '__main__':
    app = App()
    app.mainloop()
