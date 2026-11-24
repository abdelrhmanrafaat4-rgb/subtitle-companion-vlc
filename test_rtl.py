import rtl


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_non_arabic_text_passes_through_unchanged():
    check(rtl.to_display('Hello world') == 'Hello world', 'plain English text is never touched')
    check(rtl.to_display('') == '', 'empty string stays empty')
    check(rtl.to_display(None) == '', 'None is handled safely')


def test_arabic_text_does_not_crash_either_way():
    # arabic_reshaper/python-bidi are not installed in this sandbox, so this
    # exercises the graceful-fallback path; on a machine that has them
    # installed, to_display() would additionally reorder/reshape the text,
    # but "runs without crashing and returns a non-empty string" is what's
    # checked here either way.
    out = rtl.to_display('مسافة')
    check(isinstance(out, str) and len(out) > 0, 'Arabic input always returns a usable string, with or without the optional libraries')
    check(rtl.available() in (True, False), 'availability flag is a plain boolean the UI can branch on')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok: {t.__name__}')
    print(f'\nrtl.py: all {len(tests)} checks passed (arabic_reshaper/python-bidi available here: {rtl.available()})')
