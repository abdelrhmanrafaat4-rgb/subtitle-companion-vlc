import urllib.error

import vlcclient


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_current_time_ms_converts_seconds():
    check(vlcclient.current_time_ms({'time': 42}) == 42000, 'seconds -> ms')
    check(vlcclient.current_time_ms({}) == 0, 'missing time field should not crash')
    check(vlcclient.current_time_ms(None) == 0, 'non-dict status should not crash')


def test_current_item_id_reads_currentplid():
    check(vlcclient.current_item_id({'currentplid': 7}) == 7, 'should read currentplid')
    check(vlcclient.current_item_id({}) is None, 'missing field -> None')


def test_current_media_path_finds_playing_node_in_nested_tree():
    playlist = {
        'children': [
            {
                'id': '1', 'name': 'Playlist',
                'children': [
                    {'id': '3', 'uri': 'file:///C:/Movies/other.mkv'},
                    {'id': '4', 'uri': 'file:///C:/Movies/My%20Show.mkv'},
                ],
            }
        ]
    }
    path = vlcclient.current_media_path(playlist, 4)
    check(path == 'C:\\Movies\\My Show.mkv', path)


def test_current_media_path_missing_item_returns_empty():
    check(vlcclient.current_media_path({'children': []}, 9) == '', 'no matching id -> empty')
    check(vlcclient.current_media_path(None, 9) == '', 'no playlist at all -> empty')
    check(vlcclient.current_media_path({'children': []}, None) == '', 'no item id -> empty')


def test_uri_to_local_path_handles_windows_and_plain_paths():
    check(vlcclient.uri_to_local_path('file:///C:/a/b.mkv') == 'C:\\a\\b.mkv', vlcclient.uri_to_local_path('file:///C:/a/b.mkv'))
    check(vlcclient.uri_to_local_path('file:///home/me/a.mkv') == '/home/me/a.mkv', vlcclient.uri_to_local_path('file:///home/me/a.mkv'))
    check(vlcclient.uri_to_local_path('http://example.com/a.mkv') == '', 'a non-file uri (network stream) should not be treated as local')


def test_fetch_status_wraps_http_401_as_bad_password(monkeypatch=None):
    def fake_get_json(base_url, password, path):
        raise urllib.error.HTTPError(base_url + path, 401, 'Unauthorized', None, None)
    orig = vlcclient._get_json
    vlcclient._get_json = fake_get_json
    try:
        try:
            vlcclient.fetch_status('http://127.0.0.1:8080', 'wrong')
            check(False, 'should have raised')
        except vlcclient.VlcError as e:
            check(e.code == 'BAD_PASSWORD', e.code)
    finally:
        vlcclient._get_json = orig


def test_fetch_status_wraps_url_error_as_unreachable():
    def fake_get_json(base_url, password, path):
        raise urllib.error.URLError('connection refused')
    orig = vlcclient._get_json
    vlcclient._get_json = fake_get_json
    try:
        try:
            vlcclient.fetch_status('http://127.0.0.1:8080', 'x')
            check(False, 'should have raised')
        except vlcclient.VlcError as e:
            check(e.code == 'UNREACHABLE', e.code)
    finally:
        vlcclient._get_json = orig


def test_fetch_status_passes_through_real_data_on_success():
    def fake_get_json(base_url, password, path):
        return {'time': 5, 'currentplid': 2}
    orig = vlcclient._get_json
    vlcclient._get_json = fake_get_json
    try:
        status = vlcclient.fetch_status('http://127.0.0.1:8080', 'secret')
        check(status == {'time': 5, 'currentplid': 2}, status)
    finally:
        vlcclient._get_json = orig


def test_fetch_playlist_never_raises():
    def fake_get_json(base_url, password, path):
        raise RuntimeError('anything')
    orig = vlcclient._get_json
    vlcclient._get_json = fake_get_json
    try:
        check(vlcclient.fetch_playlist('http://127.0.0.1:8080', 'x') is None, 'should swallow the error and return None')
    finally:
        vlcclient._get_json = orig


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok: {t.__name__}')
    print(f'\nvlcclient.py: all {len(tests)} checks passed')
