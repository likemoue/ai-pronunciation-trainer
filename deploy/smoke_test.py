#!/usr/bin/env python3
"""Smoke test for a running instance (standard library only).

    python3 deploy/smoke_test.py http://127.0.0.1:3001

Checks the page, sampling, input validation, TTS and one full scoring pass on
a sentence synthesised by the server itself. Exits non-zero on any failure.
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3000').rstrip('/')
SENTENCE = 'Hello, I have a cat and a dog at home.'
failures = []


def call(path, body=None, content_type='application/json', timeout=120):
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method='GET' if body is None else 'POST')
    if body is not None:
        request.add_header('Content-Type', content_type)
    start = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, response.read(), time.time() - start
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read(), time.time() - start


def check(name, ok, detail=''):
    print(f'{"ok  " if ok else "FAIL"} {name} {detail}')
    if not ok:
        failures.append(name)


def as_json(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {}


status, headers, body, seconds = call('/')
check('page', status == 200 and b'Pronunciation' in body
      and bool(headers.get('Content-Security-Policy')), f'{status} {seconds:.2f}s')

status, headers, body, seconds = call('/getSample', {'category': 1, 'language': 'en'})
sentence = (as_json(body).get('real_transcript') or [''])[0]
check('sample', status == 200 and bool(sentence), f'{status} {seconds:.2f}s {sentence!r}')

status, headers, body, seconds = call('/getSample', {'category': 7, 'language': 'en'}, timeout=10)
check('bad category is rejected', status == 400, f'{status} {seconds:.2f}s')

status, headers, body, seconds = call('/getSample', b'{"category": 1}', content_type='text/plain', timeout=10)
check('non-JSON body is rejected', status == 415, f'{status} {seconds:.2f}s')

status, headers, body, seconds = call('/getAudioFromText', {'value': SENTENCE, 'language': 'en'})
wav = as_json(body).get('wavBase64')
check('tts', status == 200 and bool(wav), f'{status} {seconds:.2f}s')

if wav:
    status, headers, body, seconds = call('/GetAccuracyFromRecordedAudio', {
        'title': SENTENCE, 'base64Audio': 'data:audio/wav;base64,' + wav, 'language': 'en'})
    result = as_json(body)
    accuracy = int(result.get('pronunciation_accuracy', -1)) if status == 200 else -1
    check('score', status == 200 and accuracy >= 60
          and headers.get('Content-Type', '').startswith('application/json'),
          f'{status} {seconds:.2f}s accuracy={accuracy} heard={result.get("real_transcript")!r}')

if failures:
    print(f'\nSmoke test FAILED: {", ".join(failures)}')
    sys.exit(1)
print('\nSmoke test passed.')
