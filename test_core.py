"""Unit tests for core.py -- the only part of this app that can be verified
in this sandbox (no screen, no Tesseract, no Windows here). Run with:
    python3 test_core.py
"""
import json
import os
import tempfile
import core


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_clean_ocr_text():
    check(core.clean_ocr_text("Don't\nwaste | your_time") == "Don't waste your time",
          'strips newlines and OCR-noise characters')
    check(core.clean_ocr_text('   ') == '', 'whitespace-only collapses to empty')
    check(core.clean_ocr_text(None) == '', 'None is handled safely')


def test_is_new_line():
    check(core.is_new_line('', 'Hello there') is True, 'first non-empty capture is new')
    check(core.is_new_line('Hello there', 'Hello there') is False, 'identical capture is not new')
    check(core.is_new_line('Hello there', 'Hcllo there') is False, 'one-character OCR jitter is not treated as a new line')
    check(core.is_new_line('Hello there', 'Completely different sentence now') is True, 'a real new line is detected')
    check(core.is_new_line('Hello there', '') is False, 'an empty capture (subtitle gap) is never "new"')


def test_tokenize():
    check(core.tokenize("Don't WASTE this. Distance!") == ["don't", 'waste', 'this', 'distance'],
          'tokenizer lowercases, keeps apostrophes, drops punctuation')


def test_word_id():
    check(core.word_id('Distance', 'the distance') == 'distance', 'id is the lemma, trimmed/lowercased')
    check(core.word_id('', 'Orbit') == 'orbit', 'falls back to selection when lemma is missing')
    check(core.word_id('', '') == '', 'empty input gives an empty id (caller must reject it)')


def test_new_srs_shape():
    srs = core.new_srs(1000)
    for key in ('due', 'stability', 'difficulty', 'reps', 'lapses', 'last', 'lastBoost', 'known'):
        check(key in srs, f'new_srs missing field "{key}" the extension expects')
    check(srs['due'] == 1000 and srs['stability'] == 0 and srs['known'] is False, 'new_srs values match shared.js newSrs()')


def test_sanitize_explain_response():
    out = core.sanitize_explain_response({'lemma': '  distance  ', 'meaning_ar': 'مسافة'}, 'the distance', 'Keep your distance.')
    check(out['lemma'] == 'distance', 'trims whitespace from Gemini fields')
    check(out['meaning_ar'] == 'مسافة', 'keeps provided field')
    check(out['example_en'] == 'Keep your distance.', 'falls back to the captured sentence when example_en is missing')
    check(out['selection'] == 'the distance', 'selection always comes from what was actually clicked, not from Gemini')

    out2 = core.sanitize_explain_response(None, 'wander', '')
    check(out2['lemma'] == 'wander', 'a non-dict Gemini reply still produces something usable (falls back to selection)')
    check(out2['example_en'] == '', 'no sentence and no example_en from Gemini -> empty, not a crash')


def test_word_record_and_image_filtering():
    explain = core.sanitize_explain_response({'lemma': 'distance', 'meaning_ar': 'مسافة'}, 'distance', 's')
    rec = core.word_record(explain, 'https://api.openverse.org/v1/images/abc.jpg', 'My Movie (2024)', 5000)
    check(rec['id'] == 'distance' and rec['imageUrl'].startswith('https://api.openverse.org/'), 'openverse image kept')
    check(rec['videoTitle'] == 'My Movie (2024)' and rec['videoUrl'] == '' and rec['ts'] == 5000, 'video/time fields set correctly')
    check(rec['srs']['due'] == 5000, 'a brand-new card is due immediately')

    # A non-whitelisted image host (e.g. a Pixabay CDN link, which carries a
    # time-limited token in the real extension) must be dropped, exactly
    # like shared.js's sanitizeWord would drop it on import.
    rec2 = core.word_record(explain, 'https://cdn.pixabay.com/photo/abc.jpg', 'x', 5000)
    check(rec2['imageUrl'] == '', 'a non-whitelisted image host is stripped so import into the extension stays consistent')


def test_merge_on_save_preserves_progress():
    now0 = 1000
    explain = core.sanitize_explain_response({'lemma': 'orbit'}, 'orbit', 's1')
    first = core.word_record(explain, '', 'Movie A', now0)
    lst = core.merge_on_save([], first)
    check(len(lst) == 1 and lst[0]['id'] == 'orbit', 'first save adds the word')

    # simulate some review progress having happened
    lst[0]['srs']['reps'] = 3
    lst[0]['srs']['stability'] = 4.2

    explain2 = core.sanitize_explain_response({'lemma': 'orbit', 'meaning_ar': 'مدار'}, 'orbit', 's2')
    again = core.word_record(explain2, '', 'Movie B', now0 + 10_000)
    lst2 = core.merge_on_save(lst, again)
    check(len(lst2) == 1, 'saving the same lemma again updates it, never duplicates it')
    check(lst2[0]['srs']['reps'] == 3 and lst2[0]['srs']['stability'] == 4.2, 'review progress survives a re-save')
    check(lst2[0]['ts'] == now0, 'the original creation time (ts) is kept, not overwritten')
    check(lst2[0]['meaning_ar'] == 'مدار', 'the freshly generated card content still gets updated')


def test_backup_payload_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'words.json')
        explain = core.sanitize_explain_response({'lemma': 'wander'}, 'wander', 's')
        words = [core.word_record(explain, '', 'Movie', 42)]
        core.save_words(path, words)
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
        check(raw['app'] == 'word-cards' and raw['version'] == 1, 'envelope matches the extension backup format exactly')
        check(isinstance(raw['words'], list) and raw['words'][0]['id'] == 'wander', 'words round-trip correctly')
        loaded = core.load_words(path)
        check(loaded == words, 'load_words reads back exactly what was written')
        check(core.load_words(os.path.join(d, 'missing.json')) == [], 'a missing file loads as an empty list, not an error')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok: {t.__name__}')
    print(f'\ncore.py: all {len(tests)} checks passed')
