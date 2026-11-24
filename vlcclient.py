"""Talks to VLC's own built-in web interface -- no OCR, no screen reading,
just asking VLC directly what time it's at and what file it's playing.

One-time setup inside VLC (documented in README.txt): Tools > Preferences >
bottom-left "Show settings: All" > Interface > Main interfaces > check
"Web" > under it, the "Lua" entry has a Password field -- set one, Save,
restart VLC. That starts a small local web server (default
http://127.0.0.1:8080) that this module reads from.

Split the same way gemini.py is: the one function that makes a live HTTP
call (_get_json) can't be tested without a running VLC, so everything that
actually makes a decision -- reading the current time out of the response,
finding the playing file's path in the playlist tree, turning a file://
URI into a normal path -- is a separate, pure function that IS tested,
with canned JSON standing in for VLC's real response.
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request


class VlcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _get_json(base_url, password, path):
    url = base_url.rstrip('/') + path
    req = urllib.request.Request(url)
    token = base64.b64encode((':' + (password or '')).encode('utf-8')).decode('ascii')
    req.add_header('Authorization', 'Basic ' + token)
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read().decode('utf-8', 'replace'))


def fetch_status(base_url, password):
    """GET /requests/status.json -- current playback time, state, and the
    id of the playing playlist item."""
    try:
        return _get_json(base_url, password, '/requests/status.json')
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise VlcError('BAD_PASSWORD', 'الباسورد بتاع VLC غلط. دوس ⚙ وحطه تاني.')
        raise VlcError('HTTP_' + str(e.code), f'VLC رجّع خطأ ({e.code}).')
    except urllib.error.URLError:
        raise VlcError('UNREACHABLE', 'مقدرش أوصل لـ VLC. اتأكد إنه شغّال، وإن واجهة الويب (Web) مفعّلة.')
    except Exception as e:  # noqa: BLE001 -- surfaced to the user either way
        raise VlcError('UNKNOWN', f'حصل خطأ وأنا بكلم VLC: {e}')


def fetch_playlist(base_url, password):
    """GET /requests/playlist.json -- used only to recover the playing
    item's real file path (status.json alone doesn't carry it). Best
    effort: returns None on any failure rather than raising, since the
    caller can still show *something* (and a retry) from status.json
    alone."""
    try:
        return _get_json(base_url, password, '/requests/playlist.json')
    except Exception:  # noqa: BLE001
        return None


def current_time_ms(status):
    """status.json reports 'time' in whole seconds."""
    try:
        return int(status.get('time', 0)) * 1000
    except (TypeError, ValueError, AttributeError):
        return 0


def current_item_id(status):
    if not isinstance(status, dict):
        return None
    return status.get('currentplid')


def _walk_playlist_nodes(node):
    if isinstance(node, dict):
        yield node
        for child in node.get('children', []) or []:
            yield from _walk_playlist_nodes(child)


def current_media_path(playlist, item_id):
    """Finds the playing item's local file path in VLC's playlist tree.
    Returns '' if not found, or if the playing item isn't a local file
    (e.g. a network stream)."""
    if playlist is None or item_id is None:
        return ''
    for node in _walk_playlist_nodes(playlist):
        if str(node.get('id')) == str(item_id):
            return uri_to_local_path(node.get('uri', '') or '')
    return ''


def uri_to_local_path(uri):
    """'file:///C:/Users/me/movie.mkv' -> 'C:\\Users\\me\\movie.mkv'
    (and the equivalent plain-path form on other OSes)."""
    if not uri.startswith('file://'):
        return ''
    path = urllib.parse.unquote(uri[len('file://'):])
    if len(path) >= 3 and path[0] == '/' and path[2] == ':':
        # Windows drive-letter path: strip the extra leading slash and
        # switch to backslashes, matching what the OS itself expects.
        return path[1:].replace('/', '\\')
    return path
