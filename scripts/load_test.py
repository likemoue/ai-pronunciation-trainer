"""A class sends its recordings at once: how long does each learner wait?

    python scripts/load_test.py --base http://127.0.0.1:3000 --students 40
    python scripts/load_test.py --base https://aitrainer.ism.io.vn --user-agent aipt-load-test --students 40

Standard library only. Each student sends one recording as app.js does (JSON
with a base64 data URL) and, like app.js, sends it again after Retry-After
plus up to 2 s when the server answers 503, at most --retries times. The
recordings are the server's own reference voice reading bank sentences
(fetched once, before the burst). Meanwhile a probe asks for the page and a
sample every second, to see whether light requests wait behind the scoring.

Run it outside school hours: it keeps both workers busy while it lasts.
Cloudflare refuses Python's default user agent; pass --user-agent for the
public site.
"""
import argparse
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
parser.add_argument('--base', default='http://127.0.0.1:3000')
parser.add_argument('--students', type=int, default=40)
parser.add_argument('--spread', type=float, default=0.0, help='seconds over which the recordings are sent (0: at once)')
parser.add_argument('--retries', type=int, default=3, help='resends after a 503, as app.js does')
parser.add_argument('--sentences', type=int, default=8, help='different sentences (levels 1-3)')
parser.add_argument('--timeout', type=float, default=100.0,
                    help="a client's limit for one request; the page gives each attempt 100 s (Cloudflare: 125 s)")
parser.add_argument('--user-agent', default='')
parser.add_argument('--out', default='', help='write every result to this JSON file')
args = parser.parse_args()


def request(method, path, body=None, timeout=None):
    """(status, headers, parsed JSON or bytes, seconds)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(args.base.rstrip('/') + path, data=data, method=method)
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    if args.user_agent:
        req.add_header('User-Agent', args.user_agent)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout or args.timeout) as response:
            raw, status, headers = response.read(), response.status, response.headers
    except urllib.error.HTTPError as e:
        raw, status, headers = e.read(), e.code, e.headers
    except Exception as e:  # noqa: BLE001 - timeouts and resets are results too
        return type(e).__name__, {}, None, time.perf_counter() - start
    elapsed = time.perf_counter() - start
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = raw
    return status, headers, payload, elapsed


def recordings():
    """(sentence, data URL) pairs read by the server's voice."""
    pairs = []
    for n in range(args.sentences):
        status, _, sample, _ = request('POST', '/getSample', {'category': 1 + n % 3, 'language': 'en'})
        if status != 200:
            raise SystemExit(f'/getSample answered {status}')
        sentence = sample['real_transcript'][0]
        status, _, speech, _ = request('POST', '/getAudioFromText', {'value': sentence, 'language': 'en'})
        if status != 200:
            raise SystemExit(f'/getAudioFromText answered {status}')
        pairs.append((sentence, 'data:audio/wav;base64,' + speech['wavBase64']))
    return pairs


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, round(p / 100 * (len(values) - 1)))] if values else None


def main():
    pairs = recordings()
    print(f'{len(pairs)} recordings ready; {args.students} students, spread {args.spread} s', flush=True)
    results, probes = [], []
    lock = threading.Lock()
    stop = threading.Event()
    t0 = time.perf_counter()

    def student(i):
        time.sleep(args.spread * i / max(1, args.students - 1) if args.spread else 0)
        sentence, audio = pairs[i % len(pairs)]
        started = time.perf_counter()
        waited = 0.0
        for attempt in range(args.retries + 1):
            status, headers, body, _ = request('POST', '/GetAccuracyFromRecordedAudio',
                                               {'title': sentence, 'base64Audio': audio, 'language': 'en'})
            if status not in (429, 503) or attempt == args.retries:
                break
            retry_after = float(headers.get('Retry-After') or 3)
            pause = retry_after + random.uniform(0, 2)
            waited += pause
            time.sleep(pause)
        entry = {'student': i, 'status': status, 'attempts': attempt + 1, 'seconds': round(time.perf_counter() - started, 2),
                 'waited_for_retry_s': round(waited, 1),
                 'accuracy': body.get('pronunciation_accuracy') if isinstance(body, dict) else None}
        with lock:
            results.append(entry)

    def probe():
        while not stop.is_set():
            for name, method, path, body in (('page', 'GET', '/', None),
                                             ('sample', 'POST', '/getSample', {'category': 1, 'language': 'en'})):
                status, _, _, elapsed = request(method, path, body, timeout=60)
                probes.append({'what': name, 'status': status, 'seconds': round(elapsed, 2),
                               'at': round(time.perf_counter() - t0, 1)})
            stop.wait(1)

    prober = threading.Thread(target=probe, daemon=True)
    prober.start()
    threads = [threading.Thread(target=student, args=(i,)) for i in range(args.students)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stop.set()
    prober.join(timeout=65)

    seconds = [r['seconds'] for r in results]
    scored = [r for r in results if r['status'] == 200]
    summary = {
        'students': args.students, 'spread_s': args.spread, 'wall_s': round(time.perf_counter() - t0, 1),
        'scored': len(scored),
        'statuses': {str(s): sum(1 for r in results if r['status'] == s) for s in {r['status'] for r in results}},
        'resent': sum(1 for r in results if r['attempts'] > 1),
        'max_attempts': max(r['attempts'] for r in results),
        'seconds_p50': percentile(seconds, 50), 'seconds_p90': percentile(seconds, 90), 'seconds_max': max(seconds),
        'page_max_s': max((p['seconds'] for p in probes if p['what'] == 'page'), default=None),
        'sample_max_s': max((p['seconds'] for p in probes if p['what'] == 'sample'), default=None),
        'probe_failures': sum(1 for p in probes if p['status'] != 200),
        'mean_accuracy': round(statistics.mean(int(r['accuracy']) for r in scored), 1) if scored else None,
    }
    print(json.dumps(summary, indent=1))
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump({'summary': summary, 'results': sorted(results, key=lambda r: r['student']), 'probes': probes},
                      f, indent=1)


if __name__ == '__main__':
    main()
