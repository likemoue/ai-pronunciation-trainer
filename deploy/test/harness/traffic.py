#!/usr/bin/env python3
"""traffic.py BASE STOPFILE OUT.json: keep requesting BASE until STOPFILE exists.

Fast requests (GET /) from 4 threads every 20 ms, and slow ones (GET /slow,
1.5 s in the app) from 2 threads, so some requests are always in flight while
deploy.sh switches. Every request that does not answer 200 is a failure.
"""
import collections
import json
import os
import sys
import threading
import time
import urllib.request

base, stop_file, out = sys.argv[1:4]
lock = threading.Lock()
stats = collections.Counter()
served = collections.Counter()
failures = []


def worker(path, pause):
    while not os.path.exists(stop_file):
        start = time.time()
        try:
            with urllib.request.urlopen(base + path, timeout=15) as response:
                body = response.read().decode(errors='replace').strip()
                ok = response.status == 200
        except Exception as error:  # noqa: BLE001
            ok, body = False, f'{type(error).__name__}: {error}'
        with lock:
            stats['total'] += 1
            if ok:
                served[body] += 1
            else:
                stats['failed'] += 1
                failures.append({'t': time.strftime('%T', time.localtime(start)), 'ts': round(start, 3), 'path': path,
                                 'after_s': round(time.time() - start, 2), 'error': body[:160]})
        time.sleep(pause)


threads = [threading.Thread(target=worker, args=('/', 0.02)) for _ in range(4)]
threads += [threading.Thread(target=worker, args=('/slow?ms=1500', 0.05)) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()
summary = {'total': stats['total'], 'failed': stats['failed'], 'served': dict(served), 'failures': failures}
json.dump(summary, open(out, 'w'), indent=1)
print(f"{summary['total']} requests, {summary['failed']} failed; served {dict(served)}"
      + (f"; first failures {failures[:3]}" if failures else ''))
