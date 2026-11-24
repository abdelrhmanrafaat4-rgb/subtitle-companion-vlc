"""Free, keyless image search via Openverse -- stdlib only (urllib).

Mirrors background.js's openverseSearch()/tokens()-based ranking closely, and
deliberately sticks to Openverse only (no Pexels/Pixabay) for two reasons:
  - Pexels is not issuing new API keys right now (the user hit this already
    with the Chrome extension), and Pixabay needs a key plus has a 24h URL
    expiry that would make a saved card's image break later.
  - Openverse's *thumbnail* URL (api.openverse.org) is the one host, besides
    Pexels, that the extension's sanitizeWord() treats as "stable enough to
    keep" (see core.STABLE_IMAGE_PREFIXES). Using the thumbnail (not the
    original-source `url`, which can point at any third-party host) is what
    keeps an imported word's picture intact in the Chrome extension.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

OPENVERSE_SEARCH = 'https://api.openverse.org/v1/images/'
TIMEOUT_SECONDS = 20
_TOKEN_RE = re.compile(r'[^a-z]+')


class ImageError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _tokens_re(s):
    return [w for w in _TOKEN_RE.split((s or '').lower()) if len(w) > 2]


def rank_results(results, queries):
    """Pure/testable: scores each candidate by how many query words appear in
    its alt text, same idea as background.js's findImages() ranking, and
    returns the best match (or None)."""
    if not results:
        return None
    wanted = set()
    for q in queries:
        wanted.update(_tokens_re(q))
    scored = []
    for idx, r in enumerate(results):
        score = len(set(_tokens_re(r.get('alt', ''))) & wanted)
        scored.append((score, -idx, r))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


def parse_openverse_response(data):
    """Pure/testable: maps Openverse's raw JSON into the small shape this
    app needs, keeping only results that have a usable thumbnail URL."""
    out = []
    for r in (data or {}).get('results', []) or []:
        thumb = r.get('thumbnail') or ''
        if not isinstance(thumb, str) or not thumb.startswith('https://api.openverse.org/'):
            continue
        out.append({'url': thumb, 'alt': r.get('title') or '', 'creator': r.get('creator') or 'Unknown'})
    return out


def _search_once(query):
    # No "category" filter: restricting to "photograph" earlier turned out
    # to zero out results for plenty of perfectly good illustration/vector
    # matches, which looked indistinguishable from the whole feature being
    # broken. A descriptive User-Agent is what Openverse's own docs ask
    # unauthenticated API consumers to send.
    url = f'{OPENVERSE_SEARCH}?{urllib.parse.urlencode({"q": query, "page_size": 8, "mature": "false"})}'
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'SubtitleCompanion/1.0 (personal vocabulary app; no commercial use)',
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise ImageError('RATE', 'وصلت للحد المجاني من Openverse دلوقتي.')
        raise ImageError('HTTP', f'Openverse رجّع خطأ {e.code}.')
    except urllib.error.URLError:
        raise ImageError('NETWORK', 'مفيش اتصال بالإنترنت.')


def find_image(queries):
    """Tries each query (Gemini's suggested image_queries, falling back to
    the lemma) until one returns results, then picks the best-ranked one.
    Returns a thumbnail URL (safe to store/import) or '' if nothing was
    found -- a missing image is never treated as a fatal error, the word is
    still saved without a picture."""
    queries = [q for q in (queries or []) if q]
    for q in queries:
        try:
            data = _search_once(q)
        except ImageError:
            continue
        results = parse_openverse_response(data)
        best = rank_results(results, queries)
        if best:
            return best['url']
    return ''
