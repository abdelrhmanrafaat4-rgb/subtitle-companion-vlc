"""Tkinter does not reshape or reorder Arabic script on its own: letters can
come out in the wrong joined form and right-to-left lines can render in the
wrong visual order, especially a line mixing Arabic and an English word.
`arabic_reshaper` + `python-bidi` fix that; both are optional (pure-Python,
small, pip-installable) so the app still runs without them -- Arabic text
just won't look as clean -- rather than failing to start.
"""
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_ARABIC_RE = None


def available():
    return _AVAILABLE


def _has_arabic(text):
    global _ARABIC_RE
    if _ARABIC_RE is None:
        import re
        _ARABIC_RE = re.compile('[؀-ۿ]')
    return bool(_ARABIC_RE.search(text or ''))


def to_display(text):
    """Returns text ready to hand to a Tkinter label/text widget. Safe to
    call on any string, Arabic or not, present or not."""
    if not text or not _AVAILABLE or not _has_arabic(text):
        return text or ''
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text
