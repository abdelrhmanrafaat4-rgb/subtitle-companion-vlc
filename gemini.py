"""Gemini API client -- stdlib only (urllib), no extra pip install needed.
Mirrors the Chrome extension's background.js (geminiRequest /
generateWithFallback / parseJson) closely, so this app gives the same
quality of card and the same friendly Arabic error messages for the same
failure modes (bad key, rate limit, region, network).

The HTTP call itself (_request_once) can't be exercised in a sandbox with no
real API key and no outbound network to this host, so it is kept as a thin,
carefully-reviewed wrapper; everything around it (the request body, the
model fallback order, and parsing/normalizing the response) is pure and is
unit-tested in test_gemini.py.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

import core

GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta/models/'
# Same fallback order as the Chrome extension's background.js, so quality
# and availability match what already works for the YouTube extension.
DEFAULT_MODELS = ['gemini-3.5-flash-lite', 'gemini-3.6-flash', 'gemini-3.5-flash']
TIMEOUT_SECONDS = 25


class GeminiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def model_chain(preferred_model=''):
    preferred_model = (preferred_model or '').strip()
    if not preferred_model:
        return list(DEFAULT_MODELS)
    return [preferred_model] + [m for m in DEFAULT_MODELS if m != preferred_model]


def build_request_body(prompt):
    """The exact JSON body sent to generateContent. Pure/testable."""
    return {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'responseMimeType': 'application/json',
            'responseSchema': core.EXPLAIN_SCHEMA,
            'temperature': 0.4,
        },
    }


def parse_json_text(text):
    """Forgiving JSON parse, same fallback order as background.js's
    parseJson(): plain JSON, then a stripped ```json fence, then the first
    {...} block found anywhere in the text."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    cleaned = text.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned[3:]
        if cleaned.lower().startswith('json'):
            cleaned = cleaned[4:]
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except ValueError:
            pass
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    raise GeminiError('BAD_RESPONSE', 'مقدرتش أفهم رد Gemini. جرّب تاني.')


def extract_text(response_json):
    """Pulls the plain-text reply out of a generateContent response, raising
    the same friendly errors background.js does for a blocked/empty reply."""
    if (response_json or {}).get('promptFeedback', {}).get('blockReason'):
        raise GeminiError('BLOCKED', 'Gemini رفض يشرح النص ده. جرّب كلمة تانية.')
    candidates = (response_json or {}).get('candidates') or []
    parts = (candidates[0].get('content', {}).get('parts') if candidates else None) or []
    text = ''.join(p.get('text', '') for p in parts if isinstance(p, dict) and not p.get('thought') and isinstance(p.get('text'), str))
    if not text.strip():
        raise GeminiError('BAD_RESPONSE', 'Gemini رجّع رد فاضي. جرّب تاني.')
    return text


def _error_from_http(status, body_text):
    info = {}
    try:
        info = json.loads(body_text).get('error', {})
    except (ValueError, AttributeError):
        pass
    msg = f"{info.get('message', '')} {info.get('status', '')}"
    if 'location is not supported' in msg.lower():
        return GeminiError('REGION', 'Gemini مش متاح من المنطقة اللي إنت فيها دلوقتي.')
    if status in (400, 401, 403) and any(k in msg for k in ('api key', 'API_KEY', 'PERMISSION_DENIED', 'UNAUTHENTICATED', 'not valid')):
        return GeminiError('BAD_GEMINI_KEY', 'مفتاح Gemini مش شغّال. راجعه في الإعدادات.')
    if status == 429:
        return GeminiError('RATE_LIMIT', 'وصلت للحد المجاني اللحظي من Gemini. استنى دقيقة وجرّب تاني.')
    detail = (info.get('message') or '')[:160]
    return GeminiError(f'HTTP_{status}', f'Gemini رجّع خطأ {status}. {detail}'.strip())


def _request_once(api_key, model, body):
    url = f'{GEMINI_BASE}{urllib.parse.quote(model, safe="")}:generateContent'
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode('utf-8', errors='replace')
        raise _error_from_http(e.code, body_text)
    except (urllib.error.URLError, TimeoutError) as e:
        raise GeminiError('NETWORK', 'مفيش اتصال بالإنترنت أو Gemini مش بيرد. جرّب تاني.')


def generate_card(api_key, selection, sentence, preferred_model=''):
    """Calls Gemini with a fallback model chain and returns a sanitized
    explain-card dict (see core.sanitize_explain_response). Raises
    GeminiError on failure (same codes/messages as background.js uses, so
    they read naturally in the overlay UI)."""
    if not (api_key or '').strip():
        raise GeminiError('NO_KEY', 'محتاج تحط مفتاح Gemini الأول في config.json.')
    prompt = core.build_explain_prompt(selection, sentence)
    body = build_request_body(prompt)
    last_err = None
    for model in model_chain(preferred_model):
        try:
            resp = _request_once(api_key, model, body)
            text = extract_text(resp)
            data = parse_json_text(text)
            return core.sanitize_explain_response(data, selection, sentence)
        except GeminiError as e:
            last_err = e
            if e.code in ('BAD_GEMINI_KEY', 'BLOCKED', 'REGION', 'NETWORK', 'NO_KEY'):
                raise
            # otherwise (rate limit / bad response / unknown http error on this one model): try the next model
    raise last_err or GeminiError('UNKNOWN', 'حصلت مشكلة غير متوقعة مع Gemini.')
