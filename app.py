"""Subtitle Companion -- desktop word-lookup helper for movies/shows you
watch in VLC with a .srt subtitle file.

An earlier version of this read subtitles off the screen with OCR so it
could work with any video player. In practice that was unreliable --
busy video backgrounds behind the text made the OCR engine misread
words -- so this version instead asks VLC directly (via VLC's own built-in
web interface) what time it's at, and reads the real subtitle text for
that moment straight out of the .srt file. That can never misread a
letter, because no image is involved at all; the trade-off is that it only
works with VLC (not "any" player), and VLC's web interface has to be
turned on once (see README.txt).

Run:  python app.py
First run asks for your Gemini key and the password you set for VLC's web
interface. After that it sits as a thin bar at the bottom (or top) of your
screen showing the current subtitle line (read from VLC + the .srt file
next to the video); click any word on it.

    اختصارات لوحة المفاتيح (تشتغل حتى لو التركيز على VLC): حط الماوس على
    كلمة في الشريط (من غير ما تدوس عليها) وبعدين دوس Alt+X عشان تشوف
    شرحها، أو Alt+S عشان تتحفظ على طول من غير ما يفتح لك حاجة.

    عناصر التحكم على الشريط: ⚙ تختار ملف السبتايتل يدويًا لو مكتشفش لوحده،
    🎚 تتحكم في حجم خط السبتايتل وعتامة خلفية الشريط، ✕ تقفل البرنامج.
    تقدر كمان تسحب الشريط نفسه لأي مكان.

IMPORTANT, please read: every OTHER file in this project (core.py,
gemini.py, images.py, subtitles.py, vlcclient.py, config.py, rtl.py) has an
automated test that actually ran and passed. This file is different: it
drives real Windows GUI windows and talks to a real running VLC, which
could not be run or verified in the Linux sandbox that wrote it (no
display, no Windows, no VLC to point it at). It was written carefully and
every decision here was kept as simple and defensive as possible, but
please treat it as a first version to try, not as something pre-verified --
and tell me what misbehaves so it can be fixed.
"""
import io
import os
import queue
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import filedialog, messagebox, simpledialog

import config
import core
import gemini
import images
import rtl
import subtitles
import vlcclient

try:
    import keyboard  # system-wide hotkeys (Alt+X / Alt+S) even while VLC has focus
except ImportError:
    keyboard = None

CONFIG_PATH = 'config.json'


class WordCard(tk.Toplevel):
    """The popup shown when a word is clicked: loading -> full card (image +
    Arabic meaning/explanation + English example + Save button). Same
    fields as the Chrome extension's on-page card; no CSP workarounds are
    needed here since a desktop window has none of a web page's
    restrictions."""

    def __init__(self, root, app, selection, sentence):
        super().__init__(root)
        self.app = app
        self.selection = selection
        self.sentence = sentence
        self.card = None
        self.image_url = ''
        self.image_ref = None
        self.title('')
        self.attributes('-topmost', True)
        self.configure(bg='#1b1d23')
        x = max(0, root.winfo_pointerx() - 150)
        y = max(0, root.winfo_pointery() - 260)
        self.geometry(f'+{x}+{y}')
        self.status = tk.Label(self, text=rtl.to_display(f'بيشرح "{selection}"...'), fg='#f2f3f5', bg='#1b1d23',
                                font=('Segoe UI', 13), wraplength=360, justify='right')
        self.status.pack(padx=16, pady=16)
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            cfg = self.app.cfg
            card = gemini.generate_card(cfg.get('geminiKey', ''), self.selection, self.sentence, cfg.get('model', ''))
            # Try Gemini's own in-context search terms first, then fall back
            # to the plain lemma and the exact selected text -- several
            # tries noticeably reduces how often a word ends up with no
            # picture at all.
            queries = list(dict.fromkeys((card.get('image_queries') or []) + [card.get('lemma', ''), self.selection]))
            img_url = images.find_image(queries)
            self.app.ui_queue.put(('card_ready', self, card, img_url))
        except gemini.GeminiError as e:
            self.app.ui_queue.put(('card_error', self, e.message))
        except Exception as e:  # noqa: BLE001 -- always surfaced to the user, never swallowed silently
            self.app.ui_queue.put(('card_error', self, f'حصل خطأ غير متوقع: {e}'))

    def show_error(self, message):
        if self.winfo_exists():
            self.status.config(text=rtl.to_display(message))

    def show_card(self, card, image_url):
        if not self.winfo_exists():
            return
        self.card = card
        self.image_url = image_url
        for w in self.winfo_children():
            w.destroy()
        body = tk.Frame(self, bg='#1b1d23')
        body.pack(padx=16, pady=14)
        if image_url:
            self.app.fetch_thumbnail(image_url, self._set_image)
        else:
            tk.Label(self, text=rtl.to_display('(مفيش صورة مناسبة اتلاقت للكلمة دي)'), fg='#6b7280', bg='#1b1d23',
                     font=('Segoe UI', 10)).pack(before=body, padx=16, pady=(14, 0))
        tk.Label(body, text=card['lemma'], fg='#f2f3f5', bg='#1b1d23', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        if card.get('pos'):
            tk.Label(body, text=card['pos'], fg='#9aa0ab', bg='#1b1d23', font=('Segoe UI', 11)).pack(anchor='w')
        tk.Label(body, text=rtl.to_display(card['meaning_ar']), fg='#ffd479', bg='#1b1d23',
                 font=('Segoe UI', 15, 'bold'), wraplength=360, justify='right').pack(anchor='e', pady=(6, 2))
        if card.get('explanation_ar'):
            tk.Label(body, text=rtl.to_display(card['explanation_ar']), fg='#dfe1e6', bg='#1b1d23',
                     font=('Segoe UI', 12), wraplength=360, justify='right').pack(anchor='e', pady=2)
        if card.get('example_en'):
            tk.Label(body, text=card['example_en'], fg='#dfe1e6', bg='#1b1d23', font=('Segoe UI', 12, 'italic'),
                     wraplength=360, justify='left').pack(anchor='w', pady=(8, 0))
        if card.get('example_ar'):
            tk.Label(body, text=rtl.to_display(card['example_ar']), fg='#9aa0ab', bg='#1b1d23',
                     font=('Segoe UI', 11), wraplength=360, justify='right').pack(anchor='e')
        btns = tk.Frame(body, bg='#1b1d23')
        btns.pack(anchor='e', pady=(12, 0))
        save_btn = tk.Button(btns, text=rtl.to_display('⭐ حفظ'))
        save_btn.config(command=lambda: self._save(save_btn))
        save_btn.pack(side='right', padx=4)
        tk.Button(btns, text='✕', command=self.destroy).pack(side='right', padx=4)

    def _set_image(self, photo):
        if not self.winfo_exists():
            return
        self.image_ref = photo  # keep a reference: Tkinter does not and the image would vanish
        children = self.winfo_children()
        lbl = tk.Label(self, image=photo, bg='#1b1d23')
        if children:
            lbl.pack(before=children[0], padx=16, pady=(14, 0))
        else:
            lbl.pack(padx=16, pady=(14, 0))

    def _save(self, btn):
        btn.config(text=rtl.to_display('بيتحفظ...'), state='disabled')
        threading.Thread(target=self._save_thread, args=(btn,), daemon=True).start()

    def _save_thread(self, btn):
        try:
            rec = core.word_record(self.card, self.image_url, self.app.video_title_hint, core.now_ms())
            self.app.save_word(rec)
            self.app.ui_queue.put(('saved_ok', btn, rec['lemma']))
        except Exception as e:  # noqa: BLE001
            self.app.ui_queue.put(('saved_err', btn, str(e)))


class OverlayBar(tk.Toplevel):
    """The thin always-on-top strip showing the current subtitle line as
    clickable words, plus a choose-subtitle-file (⚙) and quit (✕) control.
    Since it has no window-manager titlebar (overrideredirect), it can be
    dragged by its own background to wherever the user wants it, and that
    position is remembered."""

    def __init__(self, root, app):
        super().__init__(root)
        self.app = app
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg='#14151a')
        try:
            self.attributes('-alpha', self.app.cfg.get('barOpacity', 0.92))
        except tk.TclError:
            pass
        self._drag_origin = None
        self._last_rendered = ''

        outer = tk.Frame(self, bg='#14151a', padx=8, pady=6)
        outer.pack(fill='both', expand=True)
        controls = tk.Frame(outer, bg='#14151a')
        controls.pack(side='right', padx=(8, 0))
        tk.Label(controls, text='⚙', fg='#9aa0ab', bg='#14151a', font=('Segoe UI', 13), cursor='hand2').pack(side='left', padx=2)
        tk.Label(controls, text='🎚', fg='#9aa0ab', bg='#14151a', font=('Segoe UI', 13), cursor='hand2').pack(side='left', padx=2)
        tk.Label(controls, text='✕', fg='#9aa0ab', bg='#14151a', font=('Segoe UI', 13), cursor='hand2').pack(side='left', padx=2)
        gear, sliders, close = controls.winfo_children()
        gear.bind('<Button-1>', lambda e: self.app.choose_subtitle_file())
        sliders.bind('<Button-1>', lambda e: self.app.open_settings())
        close.bind('<Button-1>', lambda e: self.app.quit())

        self.wrap = tk.Frame(outer, bg='#14151a')
        self.wrap.pack(side='left', fill='both', expand=True)
        self._show_placeholder()

        for widget in (self, outer, self.wrap):
            widget.bind('<ButtonPress-1>', self._drag_start)
            widget.bind('<B1-Motion>', self._drag_move)
            widget.bind('<ButtonRelease-1>', self._drag_end)

        self._position()

    def _show_placeholder(self):
        """When there's genuinely no subtitle on screen right now (a gap
        between lines, which happens constantly during normal playback),
        the bar just stays blank -- no "waiting for a subtitle..." text.
        That message used to reappear on every single gap, which in
        practice meant it was flashing up almost as often as real subtitle
        lines, which is exactly what it should not do."""
        for w in self.wrap.winfo_children():
            w.destroy()

    def _bar_height(self):
        # Scales with the chosen font size so bigger subtitle text always
        # has room to breathe rather than getting clipped.
        return max(40, int(self.app.cfg.get('fontSize', 14) * 1.9) + 18)

    def _position(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = max(400, min(sw - 40, 1100)), self._bar_height()
        xy = self.app.cfg.get('overlayXY')
        if isinstance(xy, (list, tuple)) and len(xy) == 2:
            x, y = xy
        else:
            x = (sw - w) // 2
            y = (sh - h - 30) if self.app.cfg.get('overlayPosition', 'bottom') == 'bottom' else 30
        self.geometry(f'{w}x{h}+{int(x)}+{int(y)}')

    def refresh_style(self):
        """Called after the font size or opacity is changed in the settings
        window, so the change is visible immediately rather than needing a
        restart."""
        try:
            self.attributes('-alpha', self.app.cfg.get('barOpacity', 0.92))
        except tk.TclError:
            pass
        self._position()
        self.set_line(self._last_rendered)

    def _drag_start(self, e):
        self._drag_origin = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _drag_move(self, e):
        if self._drag_origin is None:
            return
        x = e.x_root - self._drag_origin[0]
        y = e.y_root - self._drag_origin[1]
        self.geometry(f'+{x}+{y}')

    def _drag_end(self, e):
        if self._drag_origin is None:
            return
        self._drag_origin = None
        self.app.cfg['overlayXY'] = [self.winfo_x(), self.winfo_y()]
        config.save(CONFIG_PATH, self.app.cfg)

    def set_line(self, text):
        self._last_rendered = text
        for w in self.wrap.winfo_children():
            w.destroy()
        words = [w for w in text.split(' ') if w]
        self._word_boxes = []
        if not words:
            self._show_placeholder()
            return
        font_size = self.app.cfg.get('fontSize', 14)
        line = tk.Frame(self.wrap, bg='#14151a')
        line.pack()
        clickable = []
        for raw_word in words:
            clean_w = ''.join(ch for ch in raw_word if ch.isalpha() or ch == "'")
            lbl = tk.Label(line, text=raw_word, fg='#f2f3f5', bg='#14151a', font=('Segoe UI', font_size), padx=3)
            lbl.pack(side='left')
            if clean_w:
                lbl.config(cursor='hand2')
                lbl.bind('<Enter>', lambda e, b=lbl: b.config(fg='#4da3ff'))
                lbl.bind('<Leave>', lambda e, b=lbl: b.config(fg='#f2f3f5'))
                lbl.bind('<Button-1>', lambda e, word=clean_w, sentence=text: self.app.on_word_clicked(word, sentence))
                clickable.append((lbl, clean_w))
        # Recorded fresh on every re-render (every new subtitle line) so
        # Alt+X / Alt+S can look up "which word is the mouse over right
        # now" at the exact moment the key is pressed, instead of relying
        # on the last <Enter> event -- that went stale the instant the line
        # changed underneath a mouse that hadn't moved, which looked like
        # the shortcut had simply stopped working.
        self.update_idletasks()
        for lbl, clean_w in clickable:
            x1, y1 = lbl.winfo_rootx(), lbl.winfo_rooty()
            self._word_boxes.append((x1, y1, x1 + lbl.winfo_width(), y1 + lbl.winfo_height(), clean_w, text))

    def word_at_mouse(self):
        """Where the mouse is RIGHT NOW vs. the bar's current word layout --
        always fresh, never stale. Returns (word, sentence) or None."""
        try:
            mx, my = self.winfo_pointerx(), self.winfo_pointery()
        except tk.TclError:
            return None
        for x1, y1, x2, y2, word, sentence in getattr(self, '_word_boxes', []):
            if x1 <= mx <= x2 and y1 <= my <= y2:
                return word, sentence
        return None


class SettingsWindow(tk.Toplevel):
    """Opened from the 🎚 button: two live sliders for the subtitle text
    size and the bar's background opacity (how much of the real,
    burned-in subtitle behind it stays hidden vs. visible)."""

    def __init__(self, root, app):
        super().__init__(root)
        self.app = app
        self.title('')
        self.attributes('-topmost', True)
        self.configure(bg='#1b1d23')
        pad = {'padx': 16, 'pady': (10, 0)}

        tk.Label(self, text=rtl.to_display('حجم خط السبتايتل'), fg='#f2f3f5', bg='#1b1d23',
                 font=('Segoe UI', 11)).pack(anchor='e', **pad)
        font_scale = tk.Scale(self, from_=10, to=32, orient='horizontal', bg='#1b1d23', fg='#f2f3f5',
                               troughcolor='#2a2d36', highlightthickness=0, command=self._on_font_change)
        font_scale.set(self.app.cfg.get('fontSize', 14))
        font_scale.pack(fill='x', padx=16)

        tk.Label(self, text=rtl.to_display('عتامة خلفية الشريط (لإخفاء السبتايتل الأصلي اللي وراه)'),
                 fg='#f2f3f5', bg='#1b1d23', font=('Segoe UI', 11), wraplength=320, justify='right').pack(anchor='e', **pad)
        opacity_scale = tk.Scale(self, from_=20, to=100, orient='horizontal', bg='#1b1d23', fg='#f2f3f5',
                                  troughcolor='#2a2d36', highlightthickness=0, command=self._on_opacity_change)
        opacity_scale.set(int(self.app.cfg.get('barOpacity', 0.92) * 100))
        opacity_scale.pack(fill='x', padx=16, pady=(0, 6))

        tk.Button(self, text=rtl.to_display('قفل'), command=self.destroy).pack(pady=(10, 14))
        x = max(0, root.winfo_pointerx() - 170)
        y = max(0, root.winfo_pointery() - 220)
        self.geometry(f'+{x}+{y}')

    def _on_font_change(self, value):
        self.app.cfg['fontSize'] = int(value)
        config.save(CONFIG_PATH, self.app.cfg)
        self.app.overlay.refresh_style()

    def _on_opacity_change(self, value):
        self.app.cfg['barOpacity'] = int(value) / 100.0
        config.save(CONFIG_PATH, self.app.cfg)
        self.app.overlay.refresh_style()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.cfg = config.load(CONFIG_PATH)
        self.ui_queue = queue.Queue()
        self.last_clean_line = ''
        self.video_title_hint = ''  # VLC's web API doesn't expose a clean "show title" separate from the filename; left blank
        self.running = True
        self._subs_path = None
        self._subs_cues = []
        self.settings_win = None

        self._ensure_setup()
        self.overlay = OverlayBar(self.root, self)
        self._register_hotkeys()
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()
        self.root.after(120, self._drain_queue)

    def _register_hotkeys(self):
        """Alt+X (show the hovered word's card) / Alt+S (save it silently)
        -- registered as real OS-level hotkeys via the `keyboard` library so
        they fire even while VLC's own window has the keyboard focus (which
        it normally will, since the person is watching the video there, not
        looking at this app). `keyboard`'s callbacks run on its own listener
        thread, so they only ever push an event onto ui_queue -- the actual
        work happens on the main thread via _drain_queue, same as every
        other background thread in this app."""
        if keyboard is None:
            messagebox.showwarning('', rtl.to_display(
                'اختصارات Alt+X / Alt+S محتاجة مكتبة اسمها keyboard مش موجودة دلوقتي. '
                'شغّل: pip install -r requirements.txt تاني وبعدين افتح البرنامج من جديد. '
                'لحد ما تعمل كده، تقدر تدوس على الكلمة بالماوس في الشريط بدل الاختصار.'))
            return
        try:
            keyboard.add_hotkey('alt+x', lambda: self.ui_queue.put(('hotkey_show',)))
            keyboard.add_hotkey('alt+s', lambda: self.ui_queue.put(('hotkey_save',)))
        except Exception as e:  # noqa: BLE001 -- never let a hotkey registration problem crash the whole app
            messagebox.showwarning('', rtl.to_display(f'مقدرتش أفعّل اختصارات لوحة المفاتيح: {e}'))

    def open_settings(self):
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        self.settings_win = SettingsWindow(self.root, self)

    def _ensure_setup(self):
        if not (self.cfg.get('geminiKey') or '').strip():
            key = simpledialog.askstring('Gemini API key', 'الصق مفتاح Gemini (من aistudio.google.com/apikey):', parent=self.root)
            self.cfg['geminiKey'] = (key or '').strip()
        if not (self.cfg.get('vlcPassword') or '').strip():
            messagebox.showinfo('', rtl.to_display(
                'قبل ما نكمل: لازم تفعّل "واجهة الويب" (Web interface) في VLC مرة واحدة، '
                'وتحط لها باسورد (الخطوات بالتفصيل في README.txt). دوس OK وبعدين الصق نفس الباسورد في المربع اللي هيفتح.'))
            pw = simpledialog.askstring('VLC web interface password', 'الباسورد اللي حطيته في إعدادات VLC:', parent=self.root)
            self.cfg['vlcPassword'] = (pw or '').strip()
        config.save(CONFIG_PATH, self.cfg)
        if not config.is_ready(self.cfg):
            messagebox.showwarning('', rtl.to_display(
                'لسه الإعداد مش كامل (محتاج مفتاح Gemini وباسورد VLC). '
                'البرنامج هيفضل شغّال بس من غير ما يعمل حاجة لحد ما تظبط ده (امسح config.json وشغّله تاني).'))

    def base_url(self):
        return f"http://{self.cfg.get('vlcHost', '127.0.0.1')}:{self.cfg.get('vlcPort', 8080)}"

    def choose_subtitle_file(self):
        """Bound to the ⚙ button: manually pick (or override) the .srt
        file, for when the automatic same-folder-as-the-video guess picks
        the wrong file or finds none."""
        path = filedialog.askopenfilename(
            title=rtl.to_display('اختار ملف السبتايتل (.srt)'),
            filetypes=[('Subtitle files', '*.srt'), ('All files', '*.*')])
        if path:
            self.cfg['subtitlePath'] = path
            config.save(CONFIG_PATH, self.cfg)
            self._subs_path = None  # force a reload on the next poll tick

    def _resolve_subtitle_path(self, status):
        manual = (self.cfg.get('subtitlePath') or '').strip()
        if manual:
            return manual
        playlist = vlcclient.fetch_playlist(self.base_url(), self.cfg.get('vlcPassword', ''))
        media_path = vlcclient.current_media_path(playlist, vlcclient.current_item_id(status))
        if not media_path:
            return ''
        candidate = subtitles.derive_subtitle_path(media_path)
        return candidate if os.path.isfile(candidate) else ''

    def _poll_loop(self):
        last_status_msg = None
        while self.running:
            message = None
            try:
                status = vlcclient.fetch_status(self.base_url(), self.cfg.get('vlcPassword', ''))
                sub_path = self._resolve_subtitle_path(status)
                if not sub_path:
                    message = 'مش لاقي ملف السبتايتل بجانب الفيديو - دوس ⚙ واختاره يدويًا.'
                else:
                    if sub_path != self._subs_path:
                        self._subs_cues = subtitles.load_srt_file(sub_path)
                        self._subs_path = sub_path
                    line = subtitles.find_current_cue(self._subs_cues, vlcclient.current_time_ms(status))
                    if line != self.last_clean_line:
                        self.last_clean_line = line
                        self.ui_queue.put(('line', line))
            except vlcclient.VlcError as e:
                message = e.message
            except Exception as e:  # noqa: BLE001 -- one bad poll tick is never worth crashing the loop for
                message = f'حصل خطأ غير متوقع: {e}'
            if message is not None and message != last_status_msg:
                last_status_msg = message
                self.ui_queue.put(('line', message))
            elif message is None:
                last_status_msg = None
            time.sleep(float(self.cfg.get('pollSeconds', 0.6)))

    def on_word_clicked(self, word, sentence):
        WordCard(self.root, self, word, sentence)

    def handle_hotkey_show(self):
        hit = self.overlay.word_at_mouse()
        if hit:
            self.on_word_clicked(*hit)
        else:
            self.show_toast('حط الماوس فوق كلمة في الشريط وبعدين دوس Alt+X')

    def handle_hotkey_save(self):
        hit = self.overlay.word_at_mouse()
        if hit:
            self.silent_save(*hit)
        else:
            self.show_toast('حط الماوس على كلمة في الشريط الأول وبعدين دوس Alt+S')

    def silent_save(self, word, sentence):
        """Alt+S: explain + save a word in the background, with no card
        window opened at all -- just a brief toast, mirroring the Chrome
        extension's silent Alt+S behavior."""
        self.show_toast(f'بيحفظ "{word}"...')
        threading.Thread(target=self._silent_save_thread, args=(word, sentence), daemon=True).start()

    def _silent_save_thread(self, word, sentence):
        try:
            card = gemini.generate_card(self.cfg.get('geminiKey', ''), word, sentence, self.cfg.get('model', ''))
            queries = list(dict.fromkeys((card.get('image_queries') or []) + [card.get('lemma', ''), word]))
            img_url = images.find_image(queries)
            rec = core.word_record(card, img_url, self.video_title_hint, core.now_ms())
            self.save_word(rec)
            self.ui_queue.put(('toast', f"اتحفظت ✓ {rec['lemma']}"))
        except gemini.GeminiError as e:
            self.ui_queue.put(('toast', e.message))
        except Exception as e:  # noqa: BLE001
            self.ui_queue.put(('toast', f'حصل خطأ: {e}'))

    def show_toast(self, message):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        try:
            win.attributes('-alpha', 0.95)
        except tk.TclError:
            pass
        win.configure(bg='#1b1d23')
        tk.Label(win, text=rtl.to_display(message), fg='#f2f3f5', bg='#1b1d23',
                 font=('Segoe UI', 12), padx=14, pady=8, wraplength=420, justify='right').pack()
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        x = (sw - win.winfo_width()) // 2
        win.geometry(f'+{x}+70')
        win.after(2200, win.destroy)

    def fetch_thumbnail(self, url, callback):
        def work():
            try:
                from PIL import Image, ImageTk
                with urllib.request.urlopen(url, timeout=15) as resp:
                    raw = resp.read()
                img = Image.open(io.BytesIO(raw))
                img.thumbnail((340, 220))
                photo = ImageTk.PhotoImage(img)
                self.ui_queue.put(('thumbnail', callback, photo))
            except Exception:
                pass  # a missing/broken thumbnail should never block the rest of the card
        threading.Thread(target=work, daemon=True).start()

    def save_word(self, record):
        words_path = self.cfg.get('wordsPath', 'words.json')
        words = core.load_words(words_path)
        words = core.merge_on_save(words, record)
        core.save_words(words_path, words)

    def _drain_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == 'line':
                    self.overlay.set_line(item[1])
                elif kind == 'card_ready':
                    _, card_win, card, img_url = item
                    card_win.show_card(card, img_url)
                elif kind == 'card_error':
                    _, card_win, message = item
                    card_win.show_error(message)
                elif kind == 'thumbnail':
                    _, callback, photo = item
                    callback(photo)
                elif kind == 'saved_ok':
                    _, btn, lemma = item
                    if btn.winfo_exists():
                        btn.config(text=rtl.to_display(f'اتحفظت ✓ {lemma}'))
                elif kind == 'saved_err':
                    _, btn, message = item
                    if btn.winfo_exists():
                        btn.config(text=rtl.to_display('فشل الحفظ، جرّب تاني'), state='normal')
                elif kind == 'hotkey_show':
                    self.handle_hotkey_show()
                elif kind == 'hotkey_save':
                    self.handle_hotkey_save()
                elif kind == 'toast':
                    self.show_toast(item[1])
        except queue.Empty:
            pass
        if self.running:
            self.root.after(120, self._drain_queue)

    def quit(self):
        self.running = False
        if keyboard is not None:
            try:
                keyboard.unhook_all()
            except Exception:  # noqa: BLE001 -- quitting should never get stuck on hotkey cleanup
                pass
        self.root.quit()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
