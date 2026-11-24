"""Subtitle (.srt) parsing and "what line is on screen right now" lookup.

This replaces screen-reading OCR as the source of the current subtitle
line: instead of guessing from a screenshot, we read the real .srt file the
video uses and ask "which cue covers this playback time?" -- which can
never misread a single letter, because there is no image involved at all.

Pure text logic only (no file I/O beyond the one small wrapper at the
bottom), so all of the real decisions here are unit-tested directly.
"""
import os
import re

_TIME_RE = r'(\d+):(\d{2}):(\d{2})[,.](\d{3})'
_TIMECODE_LINE_RE = re.compile(r'\s*' + _TIME_RE + r'\s*-->\s*' + _TIME_RE)
_TAG_RE = re.compile(r'\{\\[^}]*\}|<[^>]+>')


def _time_to_ms(h, m, s, ms):
    return (((int(h) * 60 + int(m)) * 60 + int(s)) * 1000) + int(ms)


def clean_subtitle_text(raw):
    """Strips basic inline markup some .srt files carry: HTML-ish tags like
    <i>/<b>, and ASS-style override blocks like {\\an8} some hardsub-derived
    .srt exports leave behind. Collapses the (possibly multi-line) cue into
    one plain line, since that is what the overlay bar shows."""
    text = _TAG_RE.sub('', raw)
    text = text.replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_srt(text):
    """Returns a list of {'start_ms', 'end_ms', 'text'} cues sorted by
    start time. Tolerant of a leading BOM, Windows line endings, a missing
    numeric index line, and stray blank lines -- real .srt files in the
    wild are inconsistent about all of these."""
    text = text.lstrip('﻿').replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\s*\n', text.strip())
    cues = []
    for block in blocks:
        lines = [l for l in block.split('\n') if l.strip() != '']
        if not lines:
            continue
        time_idx = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if time_idx is None:
            continue
        m = _TIMECODE_LINE_RE.match(lines[time_idx])
        if not m:
            continue
        g = m.groups()
        start_ms = _time_to_ms(*g[0:4])
        end_ms = _time_to_ms(*g[4:8])
        clean = clean_subtitle_text('\n'.join(lines[time_idx + 1:]))
        if clean:
            cues.append({'start_ms': start_ms, 'end_ms': end_ms, 'text': clean})
    cues.sort(key=lambda c: c['start_ms'])
    return cues


def find_current_cue(cues, time_ms, tolerance_ms=150):
    """cues must be sorted by start_ms (parse_srt already returns them that
    way). Returns the active cue's text at time_ms, or '' if none is
    showing. The small tolerance smooths over VLC's own ~1-second polling
    granularity without bleeding into a neighboring line."""
    for cue in cues:
        if cue['start_ms'] - tolerance_ms <= time_ms <= cue['end_ms'] + tolerance_ms:
            return cue['text']
    return ''


def derive_subtitle_path(video_path):
    """The overwhelmingly common convention: movie.mkv next to movie.srt.
    Pure string logic; the caller decides whether the result actually
    exists on disk."""
    if not video_path:
        return ''
    base, _ext = os.path.splitext(video_path)
    return base + '.srt'


_ENCODINGS_TO_TRY = ('utf-8-sig', 'utf-16', 'cp1256', 'cp1252', 'latin-1')


def load_srt_file(path):
    """Reads and parses a .srt file, trying a few common encodings (plain
    UTF-8 with/without BOM, UTF-16, and the Windows Arabic/Western
    code pages some older subtitle tools still export) before giving up
    and replacing whatever bytes don't decode, so a slightly unusual file
    still loads with most of its text intact rather than crashing."""
    last_text = None
    for encoding in _ENCODINGS_TO_TRY:
        try:
            with open(path, 'r', encoding=encoding) as f:
                last_text = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if last_text is None:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            last_text = f.read()
    return parse_srt(last_text)
