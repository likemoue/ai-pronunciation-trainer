#!/usr/bin/env python3
"""Smoke test for a running instance (standard library only).

    python3 deploy/smoke_test.py http://127.0.0.1:3001
    python3 deploy/smoke_test.py http://127.0.0.1:3000 --timeout 60
    python3 deploy/smoke_test.py https://aitrainer.ism.io.vn --user-agent 'aitrainer-canary/1.0'

Checks the page, health, sampling, input validation, TTS and one full scoring
pass on a sentence synthesised by the server itself. Exits non-zero on any
failure, and at once when a request gets no answer or a gateway error (502,
504). deploy/deploy.sh runs it against each new release, and the canary
(.github/workflows/canary.yml) against the public site. Cloudflare refuses
Python's default user agent, so give the canary its own.

From phase 2 on, a worker that holds as many recordings (or texts to read
aloud) as it takes answers 503 with Retry-After; like the page, the check sends
them again after that time, 3 times at most, so a class at work does not fail
a deploy or the canary. Before phase 2 every request, /healthz too, waited
behind the recordings queued on its worker instead. --timeout (default 10 s)
is the wait for the quick checks; the page, samples, TTS and scoring wait at
least 120 s. deploy.sh gives the quick checks on port 3000 60 s, as the colour
that has just taken the traffic may be busy. The recording of a bank sentence
(/tts/<language>/<key>.mp3, phase 2 on) is checked when the sample names one.
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
parser.add_argument('--timeout', type=float, default=10,
                    help='seconds to wait for each quick check (default 10); the others wait at least 120')
args = parser.parse_args()
BASE = args.base.rstrip('/')
QUICK = args.timeout
SLOW = max(120.0, args.timeout)
# No answer at all (refused, reset, timed out), or a proxy that could not reach the app.
UNREACHABLE = {0, 502, 504}
failures = []


def call(path, body=None, content_type='application/json', timeout=SLOW, stop_if_unreachable=True):
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
            result = response.status, response.headers, response.read(), time.time() - start
    except urllib.error.HTTPError as error:
        result = error.code, error.headers, error.read(), time.time() - start
    except (urllib.error.URLError, OSError) as error:
        result = 0, {}, str(error).encode(), time.time() - start
    if stop_if_unreachable and result[0] in UNREACHABLE:
        # The other checks would fail the same way; a deploy switches back sooner.
        print(f'FAIL {path} {result[0] or "no answer"} {result[3]:.2f}s {result[2][:160]!r}')
        print('\nSmoke test FAILED: the instance does not answer.')
        sys.exit(1)
    return result


def call_resending(path, body=None, attempts=4):
    """call(), sent again after a 503 busy answer with its Retry-After (30 s at
    most), as the page does."""
    for attempt in range(attempts):
        result = call(path, body)
        if result[0] != 503 or as_json(result[2]).get('code') not in ('busy', 'tts_busy') \
                or attempt == attempts - 1:
            return result
        wait = min(30.0, float(result[1].get('Retry-After') or 5))
        print(f'     {path}: busy (503), sending it again in {wait:g} s', flush=True)
        time.sleep(wait)
    return result


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
status, headers, body, seconds = call('/healthz', timeout=QUICK)
if status == 404:
    print('skip healthz (this release has no /healthz)')
else:
    check('healthz', status == 200 and as_json(body).get('status') == 'ok', f'{status} {seconds:.2f}s')
    status, headers, body, seconds = call('/readyz', timeout=QUICK)
    check('readyz', status == 200, f'{status} {seconds:.2f}s {body[:120]!r}')

status, headers, body, seconds = call('/getSample', {'category': 1, 'language': 'en'})
sentence = (as_json(body).get('real_transcript') or [''])[0]
tts_url = as_json(body).get('tts_url')
check('sample', status == 200 and bool(sentence), f'{status} {seconds:.2f}s')

if tts_url:
    status, headers, body, seconds = call_resending(tts_url)
    check('sentence recording', status == 200 and headers.get('Content-Type', '').startswith('audio/mpeg')
          and len(body) > 1000, f'{status} {seconds:.2f}s {len(body)} bytes')

status, headers, body, seconds = call('/getSample', {'category': 7, 'language': 'en'}, timeout=QUICK)
check('bad category is rejected', status == 400, f'{status} {seconds:.2f}s')

status, headers, body, seconds = call('/getSample', b'{"category": 1}', content_type='text/plain', timeout=QUICK)
check('non-JSON body is rejected', status == 415, f'{status} {seconds:.2f}s')

status, headers, body, seconds = call_resending('/getAudioFromText', {'value': SENTENCE, 'language': 'en'})
wav = as_json(body).get('wavBase64')
check('tts', status == 200 and bool(wav), f'{status} {seconds:.2f}s')

if wav:
    status, headers, body, seconds = call_resending('/GetAccuracyFromRecordedAudio', {
        'title': SENTENCE, 'base64Audio': 'data:audio/wav;base64,' + wav, 'language': 'en'})
    result = as_json(body)
    accuracy = int(result.get('pronunciation_accuracy', -1)) if status == 200 else -1
    check('score', status == 200 and accuracy >= 60
          and headers.get('Content-Type', '').startswith('application/json'),
          f'{status} {seconds:.2f}s accuracy={accuracy} heard={result.get("real_transcript")!r}')

status, headers, body, seconds = call('/version', timeout=QUICK, stop_if_unreachable=False)
print(f'     version {as_json(body)}')

if failures:
    print(f'\nSmoke test FAILED: {", ".join(failures)}')
    sys.exit(1)
print('\nSmoke test passed.')
