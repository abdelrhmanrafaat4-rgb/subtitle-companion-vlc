"""Pure logic for the subtitle companion app: no GUI, no OCR engine, no
network calls. Kept in its own module, deliberately dependency-free (stdlib
only), so it can be unit-tested anywhere -- including a Linux sandbox that
has no screen, no Tesseract binary and no Windows -- which is exactly how
this file was developed and verified (see test_core.py).

Field names and defaults are chosen to exactly match the Chrome extension's
shared.js (newSrs/sanitizeSrs/sanitizeWord and its backup/restore envelope),
so a words.json this app writes can be dropped straight into the extension's
"My Words" -> restore (استرجاع) button and reviewed there with the same
FSRS scheduler, review modes, etc.
"""
import difflib
import json
import re
import time

DAY = 86400_000
HOUR = 3_600_000
MIN = 60_000

# Same stable-CDN allow-list as shared.js's STABLE_IMAGE_PREFIXES: only image
# URLs from these hosts survive a round-trip through the extension's
# sanitizeWord(). Keep this in sync if the extension's list ever changes.
STABLE_IMAGE_PREFIXES = ('https://images.pexels.com/', 'https://api.openverse.org/')


def clean(value, max_len):
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', value).strip()[:max_len]


def clamp(v, lo, hi):
    return min(hi, max(lo, v))


# ----------------------------- OCR text handling ----------------------------

def clean_ocr_text(raw):
    """Normalize a raw OCR capture: collapse newlines/whitespace and drop a
    short list of characters Tesseract commonly hallucinates on subtitle
    text sitting over a busy video frame."""
    if not raw:
        return ''
    text = raw.replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r"[|_~`—–]", ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def similarity(a, b):
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def is_new_line(prev_clean, raw_capture, threshold=0.72):
    """True only when a freshly OCR'd capture looks like a genuinely new
    subtitle line, not the same line re-read with minor OCR jitter (a
    flicker, a slightly different crop, an extra stray character). This is
    what keeps the overlay from re-rendering (and re-flashing) the same line
    many times a second while it sits on screen."""
    curr = clean_ocr_text(raw_capture)
    if not curr:
        return False
    if curr == (prev_clean or ''):
        return False
    return similarity(prev_clean or '', curr) < threshold


_WORD_RE = re.compile(r"[A-Za-z']+")


def tokenize(text):
    return _WORD_RE.findall((text or '').lower())


# ----------------------------- FSRS-new-card record --------------------------

def new_srs(now_ms):
    """Mirrors shared.js's newSrs(): a brand-new, never-reviewed card."""
    return {'due': now_ms, 'stability': 0, 'difficulty': 0, 'reps': 0, 'lapses': 0, 'last': 0, 'lastBoost': 0, 'known': False}


def word_id(lemma, selection):
    """Mirrors shared.js's wordId(): the lemma (falling back to the
    selection), trimmed and lowercased -- not a hash. Saving the same lemma
    again is meant to update the existing card, not create a duplicate."""
    return (lemma or selection or '').strip().lower()


# ----------------------------- Gemini prompt/response -------------------------

EXPLAIN_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'lemma': {'type': 'STRING'},
        'pos': {'type': 'STRING'},
        'meaning_ar': {'type': 'STRING'},
        'explanation_ar': {'type': 'STRING'},
        'example_en': {'type': 'STRING'},
        'example_ar': {'type': 'STRING'},
        'context_ar': {'type': 'STRING'},
        'image_queries': {'type': 'ARRAY', 'items': {'type': 'STRING'}},
    },
    'required': ['lemma', 'meaning_ar', 'explanation_ar', 'example_en', 'example_ar', 'image_queries'],
}


def build_explain_prompt(selection, sentence):
    selection = (selection or '').strip()
    sentence = (sentence or '').strip()
    context = f'\nالجملة اللي ظهرت فيها الكلمة (من سبتايتل الفيديو): "{sentence}"' if sentence else ''
    context_rule = (
        '\n\nمهم جدًا: السياق (الجملة اللي فوق) هو المرجع الأساسي للمعنى، مش القاموس. '
        'لو الكلمة ليها أكتر من معنى (مثلا "like" ممكن تبقى "زي" أو "بيحب")، اختار المعنى اللي يتفق مع '
        'الجملة دي بالظبط وماتديش المعنى الأشهر أو الأول في القاموس لو السياق بيقول غيره. '
        'نفس الكلام على image_queries: خليها تعبّر عن المعنى في السياق ده تحديدًا، مش أي معنى تاني للكلمة.'
    ) if sentence else ''
    return (
        'إنت مدرّس إنجليزي بتساعد متكلم عامية مصرية يتعلم إنجليزي من أفلام/مسلسلات بسبتايتل إنجليزي.\n'
        f'الكلمة أو العبارة المحددة: "{selection}"{context}{context_rule}\n\n'
        'رجّع JSON فيه:\n'
        '- lemma: الصورة الأساسية للكلمة (مفرد، مصدر الفعل، إلخ)\n'
        '- pos: نوعها (noun/verb/adjective/phrase/...)\n'
        '- meaning_ar: معناها بالظبط في السياق ده، بالعامية المصرية، جملة قصيرة\n'
        '- explanation_ar: شرح أوسع شوية بالعامية المصرية: إمتى تستخدمها، وهل في فرق بينها وبين كلمات شبهها\n'
        '- example_en: جملة إنجليزي جديدة (غير اللي في السبتايتل) تستخدم الكلمة بوضوح\n'
        '- example_ar: ترجمة الجملة دي بالعامية المصرية\n'
        '- context_ar: لو في سياق خاص من الجملة الأصلية يستاهل يتقال، وإلا سيبها فاضية\n'
        '- image_queries: 1-2 كلمات بحث إنجليزي بسيطة (مش جملة) تجيب صورة توضح معنى الكلمة في السياق ده بالظبط، '
        'مش بس معنى الكلمة في المطلق\n'
        'الرد JSON بس، من غير أي كلام زيادة.'
    )


def sanitize_explain_response(data, selection, sentence):
    """Fills sane fallbacks for any missing/odd field, mirroring how
    defensively shared.js's sanitizeWord treats a Gemini reply, so a partial
    or slightly-off JSON response never crashes the app."""
    data = data if isinstance(data, dict) else {}

    def s(key, fallback=''):
        v = data.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else fallback

    selection = (selection or '').strip()
    sentence = (sentence or '').strip()
    lemma = s('lemma', selection)
    queries = data.get('image_queries')
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()] if isinstance(queries, list) else []
    if not queries:
        queries = [lemma] if lemma else []
    return {
        'lemma': lemma,
        'selection': selection,
        'pos': s('pos'),
        'meaning_ar': s('meaning_ar'),
        'explanation_ar': s('explanation_ar'),
        'example_en': s('example_en', sentence),
        'example_ar': s('example_ar'),
        'sentence': sentence,
        'context_ar': s('context_ar'),
        'image_queries': queries[:2],
    }


def word_record(explain, image_url, video_title, now_ms):
    """Builds one saved-word record in the exact shape the Chrome extension
    expects (same field names as shared.js's sanitizeWord output)."""
    rec = dict(explain)
    rec['id'] = word_id(rec.get('lemma'), rec.get('selection'))
    rec['imageUrl'] = image_url if (image_url or '').startswith(STABLE_IMAGE_PREFIXES) else ''
    rec['videoTitle'] = clean(video_title, 160)
    rec['videoUrl'] = ''  # no YouTube link for a local file; the extension would strip anything else anyway
    rec['ts'] = now_ms
    rec['srs'] = new_srs(now_ms)
    return rec


def merge_on_save(existing_list, new_record):
    """Same rule as background.js's saveWord(): saving a word that is
    already on the list keeps its original `ts` and review progress
    (`srs`), only refreshing the rest of the card; the record moves to the
    front of the list either way."""
    prev = next((w for w in existing_list if w.get('id') == new_record['id']), None)
    if prev:
        merged = dict(new_record)
        merged['ts'] = prev.get('ts', new_record['ts'])
        merged['srs'] = prev.get('srs', new_record['srs'])
    else:
        merged = new_record
    rest = [w for w in existing_list if w.get('id') != new_record['id']]
    return [merged] + rest


def backup_payload(words, now_ms):
    """Same envelope as the extension's JSON backup/restore format, so this
    file can be dropped straight into "My Words" -> استرجاع (Restore)."""
    return {'app': 'word-cards', 'version': 1, 'exportedAt': now_ms, 'words': words}


def now_ms():
    return int(time.time() * 1000)


def load_words(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if isinstance(data, dict) and isinstance(data.get('words'), list):
        return data['words']
    if isinstance(data, list):
        return data
    return []


def save_words(path, words):
    payload = backup_payload(words, now_ms())
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
