"""Unit tests for gemini.py. No real network call is made: _request_once is
monkeypatched so the request/response plumbing and the model-fallback logic
are verified without needing a live API key or outbound network, neither of
which this sandbox has.
"""
import gemini


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_model_chain():
    check(gemini.model_chain('') == gemini.DEFAULT_MODELS, 'no preference -> the default order')
    check(gemini.model_chain('gemini-3.6-flash')[0] == 'gemini-3.6-flash', 'a preferred model goes first')
    check(gemini.model_chain('gemini-3.6-flash').count('gemini-3.6-flash') == 1, 'no duplicate when the preference is already a default')


def test_build_request_body():
    body = gemini.build_request_body('hello')
    check(body['contents'][0]['parts'][0]['text'] == 'hello', 'prompt text is carried through')
    check(body['generationConfig']['responseSchema'] is gemini.core.EXPLAIN_SCHEMA, 'uses the shared schema')
    check(body['generationConfig']['responseMimeType'] == 'application/json', 'forces JSON output')


def test_parse_json_text():
    check(gemini.parse_json_text('{"a": 1}') == {'a': 1}, 'plain JSON parses directly')
    check(gemini.parse_json_text('```json\n{"a": 1}\n```') == {'a': 1}, 'strips a ```json fence')
    check(gemini.parse_json_text('```\n{"a": 1}\n```') == {'a': 1}, 'strips a bare ``` fence')
    check(gemini.parse_json_text('here you go: {"a": 1} thanks') == {'a': 1}, 'finds the first {...} block in surrounding prose')
    try:
        gemini.parse_json_text('no json here at all')
        raise AssertionError('should have raised')
    except gemini.GeminiError as e:
        check(e.code == 'BAD_RESPONSE', 'unparseable text raises BAD_RESPONSE')


def test_extract_text():
    ok = {'candidates': [{'content': {'parts': [{'text': '{"x":1}'}]}}]}
    check(gemini.extract_text(ok) == '{"x":1}', 'extracts plain text parts')

    with_thought = {'candidates': [{'content': {'parts': [{'thought': True, 'text': 'reasoning...'}, {'text': 'real answer'}]}}]}
    check(gemini.extract_text(with_thought) == 'real answer', 'thinking/thought parts are excluded')

    try:
        gemini.extract_text({'promptFeedback': {'blockReason': 'SAFETY'}})
        raise AssertionError('should have raised')
    except gemini.GeminiError as e:
        check(e.code == 'BLOCKED', 'a blocked prompt raises BLOCKED')

    try:
        gemini.extract_text({'candidates': []})
        raise AssertionError('should have raised')
    except gemini.GeminiError as e:
        check(e.code == 'BAD_RESPONSE', 'no candidates raises BAD_RESPONSE')


def test_error_from_http():
    bad_key = gemini._error_from_http(401, '{"error":{"message":"API key not valid","status":"UNAUTHENTICATED"}}')
    check(bad_key.code == 'BAD_GEMINI_KEY', '401 + api key message -> BAD_GEMINI_KEY')
    rate = gemini._error_from_http(429, '{"error":{"message":"quota"}}')
    check(rate.code == 'RATE_LIMIT', '429 -> RATE_LIMIT')
    region = gemini._error_from_http(400, '{"error":{"message":"User location is not supported"}}')
    check(region.code == 'REGION', 'unsupported-region message -> REGION')
    other = gemini._error_from_http(500, '{"error":{"message":"server exploded"}}')
    check(other.code == 'HTTP_500', 'unrecognized server error keeps the status code')


def test_generate_card_no_key():
    try:
        gemini.generate_card('', 'wander', 's')
        raise AssertionError('should have raised')
    except gemini.GeminiError as e:
        check(e.code == 'NO_KEY', 'an empty key fails fast with a clear message, no request attempted')


def test_generate_card_falls_back_to_next_model_on_bad_response(monkeypatch_calls=None):
    calls = []

    def fake_request(api_key, model, body):
        calls.append(model)
        if model == gemini.DEFAULT_MODELS[0]:
            return {'candidates': [{'content': {'parts': [{'text': 'not json'}]}}]}
        return {'candidates': [{'content': {'parts': [{'text': '{"lemma":"wander","meaning_ar":"m","explanation_ar":"e","example_en":"x","example_ar":"a","image_queries":["wander"]}'}]}}]}

    gemini._request_once = fake_request
    card = gemini.generate_card('key123', 'wander', 'They wander.')
    check(card['lemma'] == 'wander', 'eventually succeeds via the second model')
    check(calls == gemini.DEFAULT_MODELS[:2], 'tried the first model, got a bad response, moved to the second -- did not retry forever')


def test_generate_card_stops_immediately_on_bad_key(monkeypatch_calls=None):
    calls = []

    def fake_request(api_key, model, body):
        calls.append(model)
        raise gemini.GeminiError('BAD_GEMINI_KEY', 'bad key')

    gemini._request_once = fake_request
    try:
        gemini.generate_card('key123', 'wander', 's')
        raise AssertionError('should have raised')
    except gemini.GeminiError as e:
        check(e.code == 'BAD_GEMINI_KEY', 'propagates the bad-key error')
    check(calls == [gemini.DEFAULT_MODELS[0]], 'a bad key fails the same on every model, so it must not retry the other two')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok: {t.__name__}')
    print(f'\ngemini.py: all {len(tests)} checks passed')
