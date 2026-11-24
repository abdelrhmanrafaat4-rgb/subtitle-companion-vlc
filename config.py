"""Loads/saves the app's small local config.json: the Gemini key, how to
reach VLC's web interface, and a couple of preferences. Pure file I/O +
defaults, so it's fully testable without a display.
"""
import json
import os

DEFAULTS = {
    'geminiKey': '',
    'model': '',               # '' = use the default fallback chain
    'vlcHost': '127.0.0.1',
    'vlcPort': 8080,
    'vlcPassword': '',         # set once inside VLC's own preferences (see README.txt)
    'subtitlePath': None,      # manual override; '' / None means auto-detect from the playing file's own folder
    'wordsPath': 'words.json', # where saved cards are written (same schema the Chrome extension restores from)
    'pollSeconds': 0.6,        # how often VLC is asked for its current playback time
    'overlayPosition': 'bottom',  # 'bottom' or 'top' of the screen, used only until the bar is dragged
    'overlayXY': None,         # [x, y] once the user drags the overlay bar somewhere specific
    'fontSize': 14,            # size of the subtitle text shown on the bar
    'barOpacity': 0.92,        # 0.0 (fully see-through) to 1.0 (fully opaque) -- covers a burned-in subtitle when high
}


def load(path):
    if not os.path.exists(path):
        return dict(DEFAULTS)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def save(path, cfg):
    clean = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    return clean


def is_ready(cfg):
    """The two things that must be set before the app can actually do
    anything useful: a Gemini key, and VLC's web-interface password (the
    subtitle file itself is auto-detected at runtime, so it is not
    required here)."""
    return bool((cfg.get('geminiKey') or '').strip()) and bool((cfg.get('vlcPassword') or '').strip())
