#!/usr/bin/env python3
"""Smoke test for a running instance (standard library only).

    python3 deploy/smoke_test.py http://127.0.0.1:3001
    python3 deploy/smoke_test.py https://aitrainer.ism.io.vn --user-agent 'aitrainer-canary/1.0'

Checks the page, health, sampling, input validation, TTS and one full scoring
pass on a sentence synthesised by the server itself. Exits non-zero on any
failure. deploy/deploy.sh runs it against each new release, and the canary
(.github/workflows/canary.yml) against the public site. Cloudflare refuses
Python's default user agent, so give the canary its own.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# The warm-up sentence (lambdaSpeechToScore.WARMUP_SENTENCES['en']), which the
# reference voice reads reliably.
SENTENCE = 'I have a cat and a dog at home.'

parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
parser.add_argument('base', nargs='?', default='http://127.0.0.1:3000', help='base URL of the instance')
parser.add_argument('--user-agent', help='User-Agent header for every request')
args = parser.parse_args()
BASE = args.base.rstrip('/')
failures = []


def call(path, body=None, content_type='application/json', timeout=120):
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method='GET' if body is None else 'POST')
    if body is not None:
        request.add_header('Content-Type', content_type)
    if args.user_agent:
        request.add_header('User-Agent', args.user_agent)
    start = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, response.read(), time.time() - start
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read(), time.time() - start
    except (urllib.error.URLError, OSError) as error:
        return 0, {}, str(error).encode(), time.time() - start


def check(name, ok, detail=''):
    print(f'{"ok  " if ok else "FAIL"} {name} {detail}', flush=True)
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

# Releases from before phase 1 have no /healthz or /readyz (the canary may run
# against one); for them both checks are skipped.
status, headers, body, seconds = call('/healthz', timeout=10)
if status == 404:
    print('skip healthz (this release has no /healthz)')
else:
    check('healthz', status == 200 and as_json(body).get('status') == 'ok', f'{status} {seconds:.2f}s')
    status, headers, body, seconds = call('/readyz', timeout=10)
    check('readyz', status == 200, f'{status} {seconds:.2f}s {body[:120]!r}')

status, headers, body, seconds = call('/getSample', {'category': 1, 'language': 'en'})
sentence = (as_json(body).get('real_transcript') or [''])[0]
check('sample', status == 200 and bool(sentence), f'{status} {seconds:.2f}s')

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

status, headers, body, seconds = call('/version', timeout=10)
print(f'     version {as_json(body)}')

if failures:
    print(f'\nSmoke test FAILED: {", ".join(failures)}')
    sys.exit(1)
print('\nSmoke test passed.')
