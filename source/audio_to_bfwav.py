#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Switch BFSTM & BFWAV Converter
# GUI by Samuel Dyson
#

import os
import sys
import threading
import subprocess
import tempfile
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog
import windnd

from converter_core import process_file, get_bom

AUDIO_EXTS = {'.wav', '.mp3', '.ogg', '.flac', '.aif', '.aiff', '.m4a', '.opus', '.wma', '.aac', '.bfwav', '.bfstm'}
BFWAV_EXT  = '.bfwav'
BFSTM_EXT  = '.bfstm'


# ── BFWAV → WAV ───────────────────────────────────────────────────────────────

def _decode_dsp_adpcm(raw, coefficients, num_samples, yn1=0, yn2=0):
    samples = []
    pos = count = 0
    while pos < len(raw) and count < num_samples:
        header = raw[pos]; pos += 1
        scale  = 1 << (header & 0xF)
        ci     = (header >> 4) & 0x7
        c1, c2 = coefficients[ci * 2], coefficients[ci * 2 + 1]
        for i in range(14):
            if count >= num_samples:
                break
            if i % 2 == 0:
                if pos >= len(raw):
                    break
                nibble = (raw[pos] >> 4) & 0xF
            else:
                nibble = raw[pos] & 0xF
                pos += 1
            if nibble >= 8:
                nibble -= 16
            s = (((nibble * scale) << 11) + 1024 + c1 * yn1 + c2 * yn2) >> 11
            s = max(-32768, min(32767, s))
            samples.append(s)
            yn2 = yn1; yn1 = s; count += 1
    return samples


def bfwav_to_wav(bfwav_path, wav_path):
    import struct, wave
    with open(bfwav_path, 'rb') as fh:
        d = fh.read()
    bom = get_bom(d)
    if bom is None:
        raise ValueError('Not a valid BFWAV')
    num_blocks = struct.unpack_from(bom + 'H', d, 16)[0]
    info_off = data_off = data_blk_sz = None
    for i in range(num_blocks):
        bp  = 20 + 12 * i
        typ = struct.unpack_from(bom + 'H', d, bp)[0]
        off = struct.unpack_from(bom + 'i', d, bp + 4)[0]
        sz  = struct.unpack_from(bom + 'I', d, bp + 8)[0]
        if typ == 0x7000: info_off = off
        if typ == 0x7001: data_off = off; data_blk_sz = sz
    if info_off is None or data_off is None:
        raise ValueError('Missing INFO or DATA block')
    ip           = info_off + 8
    codec        = d[ip]
    sample_rate, _loop_start, num_samples = struct.unpack_from(bom + '3I', d, ip + 4)
    count_pos    = ip + 20
    num_channels = struct.unpack_from(bom + 'I', d, count_pos)[0]
    all_coeffs, all_yn1, all_yn2 = [], [], []
    for ch in range(num_channels):
        ref_pos   = count_pos + 4 + ch * 8
        ch_off    = struct.unpack_from(bom + 'i', d, ref_pos + 4)[0]
        chan_pos  = count_pos + ch_off
        adpcm_typ = struct.unpack_from(bom + 'H', d, chan_pos + 8)[0]
        adpcm_off = struct.unpack_from(bom + 'i', d, chan_pos + 12)[0]
        if adpcm_typ == 0x0300 and adpcm_off not in (0, -1):
            cp    = chan_pos + adpcm_off
            coeffs = list(struct.unpack_from(bom + '16h', d, cp))
            ctx   = struct.unpack_from(bom + '3H', d, cp + 32)
            yn1   = ctx[1] if ctx[1] < 32768 else ctx[1] - 65536
            yn2   = ctx[2] if ctx[2] < 32768 else ctx[2] - 65536
            all_coeffs.append(coeffs); all_yn1.append(yn1); all_yn2.append(yn2)
        else:
            all_coeffs.append([0] * 16); all_yn1.append(0); all_yn2.append(0)
    audio_start = data_off + 8
    audio_size  = data_blk_sz - 8
    raw         = d[audio_start : audio_start + audio_size]
    per_ch      = audio_size // max(num_channels, 1)
    if codec == 2:
        ch_samps = [
            _decode_dsp_adpcm(raw[ch * per_ch:(ch+1)*per_ch],
                               all_coeffs[ch], num_samples, all_yn1[ch], all_yn2[ch])
            for ch in range(num_channels)
        ]
    elif codec == 1:
        all_s = list(struct.unpack_from(bom + 'h' * (audio_size // 2), raw))
        ch_samps = [all_s] if num_channels == 1 else [all_s[:len(all_s)//2], all_s[len(all_s)//2:]]
    else:
        raise ValueError(f'Unsupported codec {codec}')
    trim        = min(len(s) for s in ch_samps)
    interleaved = [ch_samps[ch][i] for i in range(trim) for ch in range(num_channels)]
    pcm         = struct.pack('<' + 'h' * len(interleaved), *interleaved)
    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def _get_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return 'ffmpeg'


def to_wav(src_path, dst_path):
    ffmpeg = _get_ffmpeg()
    subprocess.run(
        [ffmpeg, '-y', '-i', src_path,
         '-ar', '48000', '-ac', '1', '-sample_fmt', 's16', dst_path],
        capture_output=True, check=True
    )


# ── palette ───────────────────────────────────────────────────────────────────
BG      = '#12080a'
PANEL   = '#1e0c0f'
ACCENT  = '#b91c1c'
ACCENT2 = '#f87171'
SUCCESS = '#4ade80'
ERROR   = '#fca5a5'
FG      = '#e2e8f0'
FG_DIM  = '#64748b'
BORDER  = '#3d1515'
BTN_BG  = '#3d1515'
BTN_HOV = '#5c1f1f'


def _find_exe(*names):
    dirs = []
    if hasattr(sys, '_MEIPASS'):
        dirs.append(sys._MEIPASS)
    dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    for d in dirs:
        for name in names:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None

def find_nw4f():      return _find_exe('NW4F_WaveConverter.exe')
def find_vgaudio():   return _find_exe('VGAudioCli.exe', 'vgaudio.exe')
def find_vgmstream(): return _find_exe('vgmstream-cli.exe', 'vgmstream.exe')


class HoverButton(tk.Label):
    def __init__(self, parent, text, command, bg=BTN_BG, fg=FG,
                 hbg=BTN_HOV, pad=(18, 8), **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg,
                         padx=pad[0], pady=pad[1], cursor='hand2',
                         font=('Segoe UI', 10, 'bold'), **kw)
        self._cmd = command
        self._bg  = bg
        self._hbg = hbg
        self.bind('<Enter>',    lambda e: self.config(bg=self._hbg))
        self.bind('<Leave>',    lambda e: self.config(bg=self._bg))
        self.bind('<Button-1>', lambda e: self._cmd())

    def set_state(self, enabled):
        if enabled:
            self.config(cursor='hand2')
            self.bind('<Button-1>', lambda e: self._cmd())
        else:
            self.config(cursor='')
            self.unbind('<Button-1>')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Switch BFSTM & BFWAV Converter')
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(660, 560)

        self._files        = []
        self._converting   = False
        self._fmt_var      = tk.StringVar(value='BFSTM')
        self._temp_wav     = None
        self._playing      = False
        self._mci_open     = False
        self._play_dur_ms  = 0
        self._user_seeking = False
        self._drag_anchor  = None
        self._rb_mode      = False   # rubber-band active
        self._rb_x0        = 0
        self._rb_y0        = 0
        self._rb_win       = None

        self._build_ui()
        self._set_icon('switch_red.png')
        self._center()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # header
        hdr = tk.Frame(self, bg=PANEL, pady=16)
        hdr.grid(row=0, column=0, sticky='ew')
        tk.Label(hdr, text='Switch BFSTM & BFWAV Converter',
                 bg=PANEL, fg=ACCENT2,
                 font=('Segoe UI', 18, 'bold')).pack()
        tk.Label(hdr, text='Audio File ↔ BFSTM & BFWAV',
                 bg=PANEL, fg=FG_DIM, font=('Segoe UI', 9)).pack(pady=(2, 0))
        tk.Label(hdr, text='Big-endian (Wii U) → Little-endian (Switch)',
                 bg=PANEL, fg=FG_DIM, font=('Segoe UI', 9)).pack()
        credit = tk.Label(hdr, text='Created by strayreign',
                          bg=PANEL, fg=FG_DIM, font=('Segoe UI', 8), cursor='hand2')
        credit.pack(pady=(4, 0))
        credit.bind('<Button-1>', lambda e: webbrowser.open('https://github.com/strayreign'))

        # toolbar
        bar = tk.Frame(self, bg=BG, pady=8, padx=12)
        bar.grid(row=1, column=0, sticky='ew')

        HoverButton(bar, '＋ Add Files',  self._add_files,  bg=ACCENT, hbg='#8f1515').pack(side='left', padx=(0, 6))
        HoverButton(bar, '📂 Add Folder', self._add_folder).pack(side='left', padx=(0, 6))
        HoverButton(bar, '✕ Clear All',   self._clear_list).pack(side='left')

        self._convert_btn = HoverButton(
            bar, '⚡ Convert', self._start_conversion,
            bg=ACCENT, hbg='#8f1515', fg='#ffffff'
        )
        self._convert_btn.pack(side='right')

        # Format toggle — BFSTM first, BFWAV second
        fmt_frame = tk.Frame(bar, bg=BG)
        fmt_frame.pack(side='right', padx=(0, 10))
        tk.Label(fmt_frame, text='Output:', bg=BG, fg=FG_DIM,
                 font=('Segoe UI', 8)).pack(side='left', padx=(0, 4))
        self._btn_bfstm = tk.Label(fmt_frame, text='BFSTM', bg=ACCENT, fg='#ffffff',
                                    padx=10, pady=4, cursor='hand2',
                                    font=('Segoe UI', 9, 'bold'))
        self._btn_bfstm.pack(side='left')
        self._btn_bfwav = tk.Label(fmt_frame, text='BFWAV', bg=BTN_BG, fg=FG,
                                    padx=10, pady=4, cursor='hand2',
                                    font=('Segoe UI', 9, 'bold'))
        self._btn_bfwav.pack(side='left', padx=(2, 0))
        self._btn_bfstm.bind('<Button-1>', lambda e: self._set_format('BFSTM'))
        self._btn_bfwav.bind('<Button-1>', lambda e: self._set_format('BFWAV'))

        # file list
        list_frame = tk.Frame(self, bg=PANEL, padx=1, pady=1)
        list_frame.grid(row=2, column=0, sticky='nsew', padx=12, pady=(0, 4))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        cols = ('file', 'format', 'convert')
        self._tree = ttk.Treeview(list_frame, columns=cols, show='headings',
                                   selectmode='extended')
        self._sort_rev = {'file': False, 'format': False, 'convert': False}
        self._tree.heading('file',    text='File',    command=lambda: self._sort_col('file'))
        self._tree.heading('format',  text='Format',  command=lambda: self._sort_col('format'))
        self._tree.heading('convert', text='Convert', command=lambda: self._sort_col('convert'))
        self._tree.column('file',    width=240, stretch=True)
        self._tree.column('format',  width=120, anchor='center', stretch=False)
        self._tree.column('convert', width=210, anchor='center', stretch=False)

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

        vsb = ttk.Scrollbar(list_frame, orient='vertical', command=self._tree.yview)
        self._tree.configure(yscrollcommand=self._autoscroll(vsb))
        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        vsb.grid_remove()

        self._tree.tag_configure('done',    foreground=SUCCESS)
        self._tree.tag_configure('error',   foreground=ERROR)
        self._tree.tag_configure('working', foreground=ACCENT2)
        self._tree.tag_configure('playing', foreground='#38bdf8')

        self._tree.bind('<Button-3>',      self._on_right_click)
        self._tree.bind('<Double-1>',      self._on_double_click)
        self._tree.bind('<ButtonPress-1>', self._on_click)
        self._tree.bind('<B1-Motion>',     self._on_drag)
        self._tree.bind('<ButtonRelease-1>', lambda e: self._rb_end())

        windnd.hook_dropfiles(self, func=self._on_drop)

        # ── player bar ────────────────────────────────────────────────────────
        player_frame = tk.Frame(self, bg=PANEL, padx=12, pady=8)
        player_frame.grid(row=3, column=0, sticky='ew', padx=12, pady=(0, 4))
        player_frame.columnconfigure(0, weight=1)

        # row 0: controls + now-playing
        ctrl_row = tk.Frame(player_frame, bg=PANEL)
        ctrl_row.grid(row=0, column=0, sticky='ew')
        ctrl_row.columnconfigure(2, weight=1)

        HoverButton(ctrl_row, '▶  Play', self._play_selected,
                    bg=ACCENT, hbg='#8f1515', fg='#ffffff', pad=(14, 5)
                    ).grid(row=0, column=0, padx=(0, 6))
        HoverButton(ctrl_row, '⏹  Stop', self._stop_playback,
                    pad=(14, 5)).grid(row=0, column=1, padx=(0, 10))

        self._now_playing_var = tk.StringVar(value='Select a file and press Play, or double-click')
        tk.Label(ctrl_row, textvariable=self._now_playing_var,
                 bg=PANEL, fg=FG_DIM, font=('Segoe UI', 9),
                 anchor='w').grid(row=0, column=2, sticky='ew')

        # row 1: time bar
        time_row = tk.Frame(player_frame, bg=PANEL)
        time_row.grid(row=1, column=0, sticky='ew', pady=(6, 0))
        time_row.columnconfigure(1, weight=1)

        self._cur_time_var = tk.StringVar(value='--:--')
        tk.Label(time_row, textvariable=self._cur_time_var,
                 bg=PANEL, fg=FG_DIM, font=('Segoe UI', 8),
                 width=5, anchor='e').grid(row=0, column=0, padx=(0, 6))

        self._time_var = tk.DoubleVar(value=0)
        style.configure('player.Horizontal.TScale',
                         background=PANEL, troughcolor=BORDER,
                         sliderlength=12, sliderrelief='flat')
        self._timescale = ttk.Scale(time_row, from_=0, to=1000,
                                     orient='horizontal', variable=self._time_var,
                                     style='player.Horizontal.TScale')
        self._timescale.grid(row=0, column=1, sticky='ew')
        self._timescale.bind('<ButtonPress-1>',   self._on_seek_press)
        self._timescale.bind('<ButtonRelease-1>', self._on_seek_release)
        self._timescale.state(['disabled'])   # disabled until something is loaded

        self._end_time_var = tk.StringVar(value='--:--')
        tk.Label(time_row, textvariable=self._end_time_var,
                 bg=PANEL, fg=FG_DIM, font=('Segoe UI', 8),
                 width=5, anchor='w').grid(row=0, column=2, padx=(6, 0))

        # progress + status bar
        bot = tk.Frame(self, bg=BG, padx=12, pady=8)
        bot.grid(row=4, column=0, sticky='ew')
        bot.columnconfigure(0, weight=1)

        self._progress = ttk.Progressbar(bot, mode='determinate',
                                          style='custom.Horizontal.TProgressbar')
        style.configure('custom.Horizontal.TProgressbar',
                         troughcolor=BORDER, background='#dc2626', thickness=6)
        self._progress.grid(row=0, column=0, sticky='ew', pady=(0, 4))

        self._status_var = tk.StringVar(value='Add audio files or a folder to get started.')
        tk.Label(bot, textvariable=self._status_var,
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9), anchor='w').grid(row=1, column=0, sticky='w')

        self._count_var = tk.StringVar(value='0 files')
        tk.Label(bot, textvariable=self._count_var,
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9)).grid(row=1, column=1, sticky='e')

    # ── helpers ───────────────────────────────────────────────────────────────

    def _format_label(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == BFWAV_EXT:
            try:
                with open(path, 'rb') as fh:
                    bom = get_bom(fh.read(6))
                if bom == '>': return 'BFWAV (BE)'
                if bom == '<': return 'BFWAV (LE)'
            except Exception:
                pass
            return 'BFWAV'
        if ext == BFSTM_EXT:
            return 'BFSTM'
        return ext.lstrip('.').upper()

    def _sort_col(self, col):
        rows = [(self._tree.set(iid, col), iid) for iid in self._tree.get_children()]
        rev  = self._sort_rev[col]
        rows.sort(key=lambda x: x[0].lower(), reverse=rev)
        for idx, (_, iid) in enumerate(rows):
            self._tree.move(iid, '', idx)
        self._sort_rev[col] = not rev

    def _set_row(self, iid, status, tag):
        name = self._tree.item(iid)['values'][0]
        fmt  = self._tree.set(iid, 'format')
        self._tree.item(iid, values=(name, fmt, status), tags=(tag,))

    def _set_format(self, fmt):
        self._fmt_var.set(fmt)
        if fmt == 'BFSTM':
            self._btn_bfstm.config(bg=ACCENT, fg='#ffffff')
            self._btn_bfwav.config(bg=BTN_BG,  fg=FG)
        else:
            self._btn_bfwav.config(bg=ACCENT, fg='#ffffff')
            self._btn_bfstm.config(bg=BTN_BG,  fg=FG)
        self._refresh_hints()

    def _file_hint(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == BFWAV_EXT:
            try:
                with open(path, 'rb') as fh:
                    bom = get_bom(fh.read(6))
                if bom == '>': return 'Big-endian (Wii U) → Little-endian (Switch)'
                if bom == '<': return 'Little-endian (Switch) → WAV'
            except Exception:
                pass
            return '—'
        if ext == BFSTM_EXT:
            return 'BFSTM → WAV'
        return f'→ .{self._fmt_var.get().lower()}'

    def _refresh_hints(self):
        for iid in self._tree.get_children():
            name = self._tree.item(iid)['values'][0]
            fmt  = self._tree.set(iid, 'format')
            self._tree.item(iid, values=(name, fmt, self._file_hint(iid)))

    @staticmethod
    def _autoscroll(vsb):
        def _set(lo, hi):
            if float(lo) <= 0.0 and float(hi) >= 1.0:
                vsb.grid_remove()
            else:
                vsb.grid()
            vsb.set(lo, hi)
        return _set

    # ── selection ─────────────────────────────────────────────────────────────

    def _on_click(self, event):
        if self._tree.identify_region(event.x, event.y) == 'heading':
            return
        row = self._tree.identify_row(event.y)
        if not row:
            # Empty space — start rubber-band selection
            self._rb_mode = True
            self._rb_x0   = event.x
            self._rb_y0   = event.y
            self._drag_anchor = None
            self._tree.selection_set([])
            return 'break'
        self._rb_mode = False
        ctrl  = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)
        if ctrl:
            sel = list(self._tree.selection())
            if row in sel:
                sel.remove(row)
            else:
                sel.append(row)
            self._tree.selection_set(sel)
            self._drag_anchor = row
        elif shift and self._drag_anchor:
            all_rows = self._tree.get_children()
            try:
                i1 = list(all_rows).index(self._drag_anchor)
                i2 = list(all_rows).index(row)
            except ValueError:
                self._tree.selection_set(row)
                self._drag_anchor = row
            else:
                lo, hi = min(i1, i2), max(i1, i2)
                self._tree.selection_set(all_rows[lo:hi + 1])
        else:
            self._tree.selection_set(row)
            self._drag_anchor = row
        return 'break'

    def _on_drag(self, event):
        if self._rb_mode:
            self._rb_draw(event.x, event.y)
            return 'break'
        if not self._drag_anchor:
            return 'break'
        all_rows = self._tree.get_children()
        if not all_rows:
            return 'break'
        row = self._tree.identify_row(event.y)
        if not row:
            last_bbox = self._tree.bbox(all_rows[-1])
            row = all_rows[-1] if (last_bbox and event.y >= last_bbox[1]) else all_rows[0]
        try:
            i1 = list(all_rows).index(self._drag_anchor)
            i2 = list(all_rows).index(row)
        except ValueError:
            return 'break'
        lo, hi = min(i1, i2), max(i1, i2)
        self._tree.selection_set(all_rows[lo:hi + 1])
        return 'break'

    def _rb_draw(self, x1, y1):
        """Draw the rubber-band rectangle and update row selection to match."""
        x0, y0 = self._rb_x0, self._rb_y0
        rx1, ry1 = min(x0, x1), min(y0, y1)
        rx2, ry2 = max(x0, x1), max(y0, y1)

        # Create or update the Toplevel overlay
        if self._rb_win is None:
            self._rb_win = tk.Toplevel(self)
            self._rb_win.overrideredirect(True)
            self._rb_win.wm_attributes('-topmost', True)
            self._rb_win.wm_attributes('-alpha', 0.30)
            # Blue fill + slightly darker border using nested frames
            outer = tk.Frame(self._rb_win, bg='#1d4ed8', padx=1, pady=1)
            outer.pack(fill='both', expand=True)
            tk.Frame(outer, bg='#3b82f6').pack(fill='both', expand=True)

        w = max(rx2 - rx1, 1)
        h = max(ry2 - ry1, 1)
        ox = self._tree.winfo_rootx()
        oy = self._tree.winfo_rooty()
        self._rb_win.geometry(f'{w}x{h}+{ox + rx1}+{oy + ry1}')
        self._rb_win.deiconify()
        self._rb_win.lift()

        # Select every row whose bounding box overlaps the rubber band
        selected = []
        for iid in self._tree.get_children():
            bb = self._tree.bbox(iid)
            if bb:
                row_top, row_bot = bb[1], bb[1] + bb[3]
                if row_bot > ry1 and row_top < ry2:
                    selected.append(iid)
        self._tree.selection_set(selected)

    def _rb_end(self):
        self._rb_mode = False
        if self._rb_win is not None:
            self._rb_win.destroy()
            self._rb_win = None

    def _on_double_click(self, event):
        row = self._tree.identify_row(event.y)
        if row:
            self._play_file(row)

    def _on_right_click(self, event):
        row = self._tree.identify_row(event.y)
        if not row:
            return
        if row not in self._tree.selection():
            self._tree.selection_set(row)
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=FG,
                       activebackground=ACCENT, activeforeground='#ffffff',
                       bd=0, font=('Segoe UI', 9))
        menu.add_command(label='▶  Play', command=self._play_selected)
        if not self._converting:
            menu.add_separator()
            menu.add_command(label='Rename', command=lambda: self._start_rename(row))
            menu.add_command(label='Remove from list', command=self._remove_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _start_rename(self, iid):
        """Show an inline entry widget over the filename cell."""
        bb = self._tree.bbox(iid, 'file')
        if not bb:
            return
        x, y, w, h   = bb
        current_name = os.path.basename(iid)
        stem         = os.path.splitext(current_name)[0]

        var   = tk.StringVar(value=current_name)
        entry = tk.Entry(self._tree, textvariable=var,
                         font=('Segoe UI', 9),
                         bg='#2d2d55', fg=FG,
                         insertbackground=FG,
                         selectbackground=ACCENT,
                         selectforeground='#ffffff',
                         relief='flat',
                         highlightthickness=1,
                         highlightbackground=ACCENT2,
                         highlightcolor=ACCENT2)
        entry.place(x=x, y=y, width=w, height=h)
        entry.select_range(0, len(stem))   # pre-select name, leave extension alone
        entry.focus_set()

        done = [False]

        def _apply(event=None):
            if done[0]:
                return
            done[0] = True
            new_name = var.get().strip()
            entry.destroy()
            if new_name and new_name != current_name:
                self._do_rename(iid, new_name)

        def _cancel(event=None):
            done[0] = True
            entry.destroy()

        entry.bind('<Return>',   _apply)
        entry.bind('<Escape>',   _cancel)
        entry.bind('<FocusOut>', _apply)

    def _do_rename(self, old_path, new_name):
        dir_part = os.path.dirname(old_path)
        new_path = os.path.join(dir_part, new_name)
        # Allow case-only renames on Windows
        if os.path.normcase(new_path) != os.path.normcase(old_path) and os.path.exists(new_path):
            self._status(f'⚠ "{new_name}" already exists.')
            return
        try:
            os.rename(old_path, new_path)
        except Exception as exc:
            self._status(f'⚠ Rename failed: {exc}')
            return
        all_rows = list(self._tree.get_children())
        idx      = all_rows.index(old_path)
        if old_path in self._files:
            self._files[self._files.index(old_path)] = new_path
        self._tree.delete(old_path)
        self._tree.insert('', idx, iid=new_path,
                          values=(new_name,
                                  self._format_label(new_path),
                                  self._file_hint(new_path)))
        self._status(f'Renamed to "{new_name}"')

    def _remove_selected(self):
        for iid in self._tree.selection():
            self._tree.delete(iid)
            if iid in self._files:
                self._files.remove(iid)
        self._refresh_count()

    # ── MCI (Windows Media Control Interface) — ALL calls on main thread ──────

    @staticmethod
    def _mci_send(cmd):
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.winmm.mciSendStringW(cmd, buf, 512, 0)
        return buf.value.strip()

    def _mci_int(self, cmd):
        try:
            return int(self._mci_send(cmd))
        except (ValueError, AttributeError):
            return 0

    @staticmethod
    def _fmt_time(seconds):
        s = max(0, int(seconds))
        return f'{s // 60}:{s % 60:02d}'

    def _mci_close(self):
        """Close MCI player if open. Must be called on main thread."""
        if self._mci_open:
            self._mci_send('stop player')
            self._mci_send('close player')
            self._mci_open = False

    # ── audio player ─────────────────────────────────────────────────────────

    def _play_selected(self):
        sel = self._tree.selection()
        if not sel:
            self._now_playing_var.set('⚠ Select a file first')
            return
        self._play_file(sel[0])

    def _play_file(self, path):
        # Stop and clean up any previous session (main thread — safe for MCI)
        self._stop_playback()
        self._playing = True
        name = os.path.basename(path)
        self._now_playing_var.set(f'⏳ Loading  {name}…')

        def _decode_worker():
            """Background thread: only decodes to WAV, touches no MCI or UI."""
            tmp = None
            try:
                ext = os.path.splitext(path)[1].lower()
                if ext == '.wav':
                    wav_path = path
                elif ext == BFWAV_EXT:
                    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                    tmp.close()
                    bfwav_to_wav(path, tmp.name)
                    wav_path = tmp.name
                elif ext == BFSTM_EXT:
                    vgm = find_vgmstream()
                    if not vgm:
                        raise RuntimeError('vgmstream-cli.exe not found')
                    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                    tmp.close()
                    subprocess.run([vgm, '-o', tmp.name, path],
                                   capture_output=True, timeout=60, check=True)
                    wav_path = tmp.name
                else:
                    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                    tmp.close()
                    to_wav(path, tmp.name)
                    wav_path = tmp.name

                if not self._playing:
                    if tmp:
                        try: os.remove(tmp.name)
                        except Exception: pass
                    return

                tmp_name = tmp.name if tmp else None
                # Hand off to main thread for all MCI operations
                self.after(0, lambda: self._mci_start(path, name, wav_path, tmp_name))

            except Exception as exc:
                msg = str(exc)[:60] if str(exc) else 'Unknown error'
                if tmp:
                    try: os.remove(tmp.name)
                    except Exception: pass
                self.after(0, lambda: (
                    self._now_playing_var.set(f'⚠ {msg}'),
                    setattr(self, '_playing', False)
                ))

        threading.Thread(target=_decode_worker, daemon=True).start()

    def _mci_start(self, path, name, wav_path, tmp_name):
        """Open and play via MCI — called on main thread only."""
        if not self._playing:
            if tmp_name:
                try: os.remove(tmp_name)
                except Exception: pass
            return

        self._temp_wav = tmp_name  # may be None for plain .wav files

        self._mci_send(f'open "{wav_path}" type waveaudio alias player')
        self._mci_send('set player time format milliseconds')
        dur_ms = self._mci_int('status player length')
        self._play_dur_ms = max(dur_ms, 1)
        self._mci_open = True
        self._mci_send('play player')

        # Update UI
        self._now_playing_var.set(f'▶  {name}')
        self._end_time_var.set(self._fmt_time(dur_ms / 1000))
        self._cur_time_var.set('0:00')
        self._timescale.config(to=self._play_dur_ms)
        self._timescale.state(['!disabled'])
        self._time_var.set(0)

        # Mark row as playing
        try:
            vals = self._tree.item(path)['values']
            self._tree.item(path, values=vals, tags=('playing',))
        except Exception:
            pass

        self._update_timebar()

    def _update_timebar(self):
        if not self._playing or not self._mci_open:
            return
        mode   = self._mci_send('status player mode')
        pos_ms = self._mci_int('status player position')
        if not self._user_seeking:
            self._time_var.set(pos_ms)
            self._cur_time_var.set(self._fmt_time(pos_ms / 1000))
        if mode == 'stopped':
            self._playing = False
            self._now_playing_var.set(
                self._now_playing_var.get().replace('▶', '⏹', 1))
            return
        self.after(200, self._update_timebar)

    def _on_seek_press(self, event):
        self._user_seeking = True

    def _on_seek_release(self, event):
        self._user_seeking = False
        if not self._mci_open:
            return
        ms = int(self._time_var.get())
        self._mci_send(f'seek player to {ms}')
        self._mci_send('play player')
        self._playing = True
        self._cur_time_var.set(self._fmt_time(ms / 1000))
        self.after(200, self._update_timebar)

    def _stop_playback(self):
        """Stop playback and clean up. Safe to call at any time from main thread."""
        self._playing = False
        self._mci_close()
        # Temp file is released by MCI close above, now safe to delete
        if self._temp_wav:
            try: os.remove(self._temp_wav)
            except Exception: pass
            self._temp_wav = None
        self._now_playing_var.set('Select a file and press Play, or double-click')
        self._cur_time_var.set('--:--')
        self._end_time_var.set('--:--')
        self._time_var.set(0)
        self._timescale.state(['disabled'])
        # Clear playing highlight
        for iid in self._tree.get_children():
            if 'playing' in self._tree.item(iid, 'tags'):
                self._tree.item(iid, tags=())

    # ── drag & drop ───────────────────────────────────────────────────────────

    def _on_drop(self, files):
        found = []
        for f in files:
            p = f.decode('utf-8') if isinstance(f, bytes) else f
            if os.path.isdir(p):
                for root, _, names in os.walk(p):
                    for n in names:
                        if os.path.splitext(n)[1].lower() in AUDIO_EXTS:
                            found.append(os.path.join(root, n))
            elif os.path.splitext(p)[1].lower() in AUDIO_EXTS:
                found.append(p)
        self._add_paths(found)

    # ── file management ───────────────────────────────────────────────────────

    def _add_paths(self, paths):
        existing = set(self._files)
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            if p not in existing and ext in AUDIO_EXTS:
                self._files.append(p)
                existing.add(p)
                self._tree.insert('', 'end', iid=p,
                                  values=(os.path.basename(p),
                                          self._format_label(p),
                                          self._file_hint(p)))
        self._refresh_count()

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title='Select audio files',
            filetypes=[('Audio files', ' '.join(f'*{e}' for e in AUDIO_EXTS)),
                       ('All files', '*.*')]
        )
        self._add_paths(list(paths))

    def _add_folder(self):
        folder = filedialog.askdirectory(title='Select folder containing audio files')
        if not folder:
            return
        found = [os.path.join(r, f)
                 for r, _, files in os.walk(folder)
                 for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXTS]
        self._add_paths(found)
        self._status(f'Added {len(found)} audio file(s).')

    def _clear_list(self):
        if self._converting:
            return
        self._stop_playback()
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
            self._status('⚠ Add some audio files first.')
            return

        fmt        = self._fmt_var.get()
        exts       = {os.path.splitext(p)[1].lower() for p in self._files}
        audio_exts = exts - {BFWAV_EXT, BFSTM_EXT}

        nw4f = vgaudio = vgmstream = None
        if fmt == 'BFWAV' and audio_exts:
            nw4f = find_nw4f()
            if not nw4f:
                self._status('⚠ NW4F_WaveConverter.exe not found — place it next to this exe.')
                return
        if fmt == 'BFSTM' and audio_exts:
            vgaudio = find_vgaudio()
            if not vgaudio:
                self._status('⚠ VGAudioCli.exe not found — place it next to this exe.')
                return
        if BFSTM_EXT in exts:
            vgmstream = find_vgmstream()
            if not vgmstream:
                self._status('⚠ vgmstream-cli.exe not found — place it next to this exe.')
                return

        self._converting = True
        self._convert_btn.set_state(False)
        self._convert_btn.config(fg=FG_DIM)
        self._progress['maximum'] = len(self._files)
        self._progress['value']   = 0

        threading.Thread(target=self._run,
                         args=(fmt, nw4f, vgaudio, vgmstream), daemon=True).start()

    def _run(self, fmt, nw4f, vgaudio, vgmstream):
        errors = 0
        for i, input_path in enumerate(self._files):
            name   = os.path.basename(input_path)
            ext    = os.path.splitext(input_path)[1].lower()
            in_dir = os.path.dirname(input_path)
            stem   = os.path.splitext(input_path)[0]

            self._set_row(input_path, '⏳ Working…', 'working')
            self._status(f'Converting: {name}')

            try:
                if ext == BFSTM_EXT:
                    out_wav = stem + '.wav'
                    if os.path.isfile(out_wav):
                        raise FileExistsError('Output .wav already exists — delete it first')
                    self._set_row(input_path, '⏳ Decoding BFSTM…', 'working')
                    subprocess.run([vgmstream, '-o', out_wav, input_path],
                                   capture_output=True, timeout=60, check=True)
                    self._set_row(input_path, '✔ → .wav', 'done')

                elif ext == BFWAV_EXT:
                    with open(input_path, 'rb') as fh:
                        bom = get_bom(fh.read(6))
                    if bom == '>':
                        self._set_row(input_path, '⏳ Converting BE→LE…', 'working')
                        process_file(input_path)
                        self._set_row(input_path, '✔ → LE', 'done')
                    else:
                        out_wav = stem + '.wav'
                        if os.path.isfile(out_wav):
                            raise FileExistsError('Output .wav already exists — delete it first')
                        self._set_row(input_path, '⏳ Decoding BFWAV…', 'working')
                        bfwav_to_wav(input_path, out_wav)
                        self._set_row(input_path, '✔ → .wav', 'done')

                elif fmt == 'BFWAV':
                    tmp_wav = None
                    if ext != '.wav':
                        self._set_row(input_path, '⏳ Decoding audio…', 'working')
                        tmp_wav    = os.path.join(in_dir, '_tmp_convert_.wav')
                        to_wav(input_path, tmp_wav)
                        nw4f_input = tmp_wav
                        nw4f_stem  = os.path.splitext(tmp_wav)[0]
                    else:
                        nw4f_input = input_path
                        nw4f_stem  = stem
                    self._set_row(input_path, '⏳ Running NW4F…', 'working')
                    subprocess.run([nw4f, nw4f_input], cwd=in_dir,
                                   capture_output=True, timeout=30)
                    dspadpcm_bfwav = nw4f_stem + '.dspadpcm.bfwav'
                    if not os.path.isfile(dspadpcm_bfwav):
                        raise FileNotFoundError('NW4F output not found')
                    dspadpcm = nw4f_stem + '.dspadpcm'
                    bfwav    = stem + '.bfwav'
                    if os.path.isfile(bfwav):
                        for f in (tmp_wav, dspadpcm_bfwav):
                            if f and os.path.isfile(f): os.remove(f)
                        raise FileExistsError('Output .bfwav already exists — delete it first')
                    os.rename(dspadpcm_bfwav, dspadpcm)
                    os.rename(dspadpcm, bfwav)
                    if tmp_wav and os.path.isfile(tmp_wav):
                        os.remove(tmp_wav)
                    self._set_row(input_path, '⏳ Converting BE→LE…', 'working')
                    process_file(bfwav)
                    self._set_row(input_path, '✔ → .bfwav', 'done')

                else:
                    tmp_wav = None
                    if ext != '.wav':
                        self._set_row(input_path, '⏳ Decoding audio…', 'working')
                        tmp_wav   = os.path.join(in_dir, '_tmp_convert_.wav')
                        to_wav(input_path, tmp_wav)
                        vga_input = tmp_wav
                    else:
                        vga_input = input_path
                    out_bfstm = stem + '.bfstm'
                    if os.path.isfile(out_bfstm):
                        if tmp_wav and os.path.isfile(tmp_wav): os.remove(tmp_wav)
                        raise FileExistsError('Output .bfstm already exists — delete it first')
                    self._set_row(input_path, '⏳ Encoding BFSTM…', 'working')
                    subprocess.run([vgaudio, '--little-endian', vga_input, out_bfstm],
                                   capture_output=True, timeout=60, check=True)
                    if tmp_wav and os.path.isfile(tmp_wav):
                        os.remove(tmp_wav)
                    self._set_row(input_path, '✔ → .bfstm', 'done')

            except FileExistsError as exc:
                self._set_row(input_path, '✘ Output exists', 'error')
                print(f'[ERROR] {input_path}: {exc}')
                errors += 1
            except Exception as exc:
                short = str(exc)[:40] if str(exc) else 'Unknown error'
                self._set_row(input_path, f'✘ {short}', 'error')
                print(f'[ERROR] {input_path}: {exc}')
                errors += 1

            self._progress['value'] = i + 1
            self.update_idletasks()

        total = len(self._files)
        ok    = total - errors
        self._status(f'Done! {ok}/{total} converted.' +
                     (f'  ({errors} error(s))' if errors else ''))
        self._converting = False
        self._convert_btn.set_state(True)
        self._convert_btn.config(fg='#ffffff')

    def _set_icon(self, filename):
        try:
            from PIL import Image, ImageTk
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
            path = os.path.join(base, filename)
            img  = Image.open(path)
            sizes = [16, 32, 48, 64, 128, 256]
            icons = [ImageTk.PhotoImage(img.resize((s, s), Image.LANCZOS)) for s in sizes]
            self.iconphoto(True, *icons)
            self._icons = icons
        except Exception:
            pass

    def _center(self):
        self.update_idletasks()
        w, h = 700, 570
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')


if __name__ == '__main__':
    app = App()
    app.mainloop()
