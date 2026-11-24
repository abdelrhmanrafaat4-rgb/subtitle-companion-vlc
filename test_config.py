import os
import tempfile
import config


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_load_missing_file_returns_defaults():
    with tempfile.TemporaryDirectory() as d:
        cfg = config.load(os.path.join(d, 'nope.json'))
        check(cfg == config.DEFAULTS, 'a missing config file loads as the defaults, not an error')


def test_load_corrupt_file_returns_defaults():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'config.json')
        with open(path, 'w') as f:
            f.write('{not valid json')
        check(config.load(path) == config.DEFAULTS, 'corrupt JSON falls back to defaults instead of crashing the app')


def test_save_then_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'config.json')
        config.save(path, {'geminiKey': 'abc123', 'vlcPassword': 'secret'})
        loaded = config.load(path)
        check(loaded['geminiKey'] == 'abc123' and loaded['vlcPassword'] == 'secret', 'saved fields round-trip correctly')
        check(loaded['pollSeconds'] == config.DEFAULTS['pollSeconds'], 'fields not explicitly saved still fall back to their default')


def test_load_ignores_a_field_dropped_from_an_older_version():
    # Older versions of this app stored a calibrated screen "region" --
    # loading a config.json saved by one of those must not crash or carry
    # the stale field forward now that OCR is no longer how this app works.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'config.json')
        with open(path, 'w', encoding='utf-8') as f:
            import json
            json.dump({'geminiKey': 'abc123', 'region': {'left': 0, 'top': 0, 'right': 10, 'bottom': 10}}, f)
        loaded = config.load(path)
        check(loaded['geminiKey'] == 'abc123', 'the still-relevant field survives')
        check('region' not in loaded, 'the retired field is dropped rather than carried forward')


def test_save_ignores_unknown_keys():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'config.json')
        config.save(path, {'geminiKey': 'x', 'totallyMadeUpField': 'should not appear'})
        with open(path, encoding='utf-8') as f:
            import json
            raw = json.load(f)
        check('totallyMadeUpField' not in raw, 'unknown keys are not written into the config file')


def test_is_ready():
    check(config.is_ready(dict(config.DEFAULTS)) is False, 'defaults alone are not ready (no key, no VLC password)')
    cfg = dict(config.DEFAULTS, geminiKey='abc')
    check(config.is_ready(cfg) is False, 'a Gemini key without a VLC password is still not ready')
    cfg['vlcPassword'] = 'secret'
    check(config.is_ready(cfg) is True, 'key + VLC password together are ready')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok: {t.__name__}')
    print(f'\nconfig.py: all {len(tests)} checks passed')
