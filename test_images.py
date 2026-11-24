"""Unit tests for images.py. _search_once is monkeypatched so no real
network call to Openverse is made -- this sandbox has no network access to
that host anyway."""
import images


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_parse_openverse_response_keeps_only_whitelisted_thumbnails():
    data = {'results': [
        {'thumbnail': 'https://api.openverse.org/v1/thumbs/a.jpg', 'title': 'a dog running', 'creator': 'Jane'},
        {'thumbnail': 'https://sketchy-cdn.example/b.jpg', 'title': 'should be dropped', 'creator': 'X'},
        {'title': 'no thumbnail field at all'},
    ]}
    out = images.parse_openverse_response(data)
    check(len(out) == 1, 'only the api.openverse.org thumbnail survives; third-party hosts and missing thumbnails are dropped')
    check(out[0]['url'] == 'https://api.openverse.org/v1/thumbs/a.jpg', 'keeps the thumbnail URL, not some other field')


def test_parse_openverse_response_empty():
    check(images.parse_openverse_response({}) == [], 'empty response -> empty list, not a crash')
    check(images.parse_openverse_response(None) == [], 'None response handled safely')


def test_rank_results_prefers_alt_text_overlap():
    results = [
        {'url': 'https://api.openverse.org/x1', 'alt': 'a red bicycle in a park'},
        {'url': 'https://api.openverse.org/x2', 'alt': 'astronaut floating in orbit around a planet'},
    ]
    best = images.rank_results(results, ['orbit', 'planet'])
    check(best['url'] == 'https://api.openverse.org/x2', 'picks the result whose alt text actually matches the search intent')


def test_rank_results_falls_back_to_first_when_no_overlap():
    results = [
        {'url': 'https://api.openverse.org/x1', 'alt': 'unrelated text'},
        {'url': 'https://api.openverse.org/x2', 'alt': 'also unrelated'},
    ]
    best = images.rank_results(results, ['distance'])
    check(best['url'] == 'https://api.openverse.org/x1', 'with no overlap at all, keeps the provider\'s own top result rather than discarding it')


def test_rank_results_empty():
    check(images.rank_results([], ['x']) is None, 'no results -> None, not an error')


def test_find_image_tries_next_query_when_first_is_empty():
    calls = []

    def fake_search(query):
        calls.append(query)
        if query == 'first try':
            return {'results': []}
        return {'results': [{'thumbnail': 'https://api.openverse.org/v1/thumbs/ok.jpg', 'title': query, 'creator': 'Jane'}]}

    images._search_once = fake_search
    url = images.find_image(['first try', 'second try'])
    check(url == 'https://api.openverse.org/v1/thumbs/ok.jpg', 'falls through to the second query when the first returns nothing')
    check(calls == ['first try', 'second try'], 'tried both queries in order')


def test_find_image_no_results_is_not_fatal():
    images._search_once = lambda q: {'results': []}
    check(images.find_image(['nothing', 'still nothing']) == '', 'no image found anywhere -> empty string, never an exception')


def test_find_image_network_error_on_one_query_tries_the_next():
    def fake_search(query):
        if query == 'bad':
            raise images.ImageError('NETWORK', 'x')
        return {'results': [{'thumbnail': 'https://api.openverse.org/v1/thumbs/ok.jpg', 'title': 'ok', 'creator': 'Jane'}]}

    images._search_once = fake_search
    url = images.find_image(['bad', 'good'])
    check(url == 'https://api.openverse.org/v1/thumbs/ok.jpg', 'a transient error on one query does not abort the whole search')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok: {t.__name__}')
    print(f'\nimages.py: all {len(tests)} checks passed')
