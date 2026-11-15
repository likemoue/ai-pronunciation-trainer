#!/usr/bin/env python3
"""traffic.py BASE STOPFILE OUT.json [full|basic] [TRACE]: keep requesting BASE until STOPFILE exists.

Every request opens a new connection. Fast requests (GET /) from 4 threads every 20 ms, and
slow ones (GET /slow, 1.5 s in the app) from 2 threads, so some are always in flight while
deploy.sh switches. "full" (the default) adds:
- long requests (GET /slow, 8 s) from 3 threads started 2.7 s apart;
- slow uploads (POST, 32 KB sent over 1.4 s, within Caddy's read_body of 3 s) from 2 threads;
- at every `caddy reload` in TRACE (bin/docker's trace of the deploy.sh that runs), as soon as
  it is traced (bin/docker then waits 0.3 s before it reloads): an upload whose body is complete
  2.2 s later, which Caddy sends to the colour that loses the traffic once it has all of it,
  and a 6.5 s request to that colour, still in flight when it is stopped (4-5 s after the
  reload: READ_BODY_SECONDS + DRAIN_MARGIN + 1, lib.sh). Both must succeed, after a switch and
  after a switch back.
A request fails unless it gets 200 with "ok <sha>", and an upload unless the app read all of it.
OUT.json has the counts, every failure, and the times of the long requests and uploads
that succeeded (traffic_check.py).
"""
import collections
import http.client
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request

base, stop_file, out = sys.argv[1:4]
full = sys.argv[4:5] != ['basic']
trace = sys.argv[5] if len(sys.argv) > 5 else None
address = urllib.parse.urlparse(base)
lock = threading.Lock()
stats = collections.Counter()
served = collections.Counter()
failures = []
spans = {'long': [], 'uploads': []}
probes = []


def record(path, start, ok, body, kind=None, span=None):
    with lock:
        stats['total'] += 1
        if ok:
            served[body] += 1
            if kind:
                spans[kind].append(span)
        else:
            stats['failed'] += 1
            failures.append({'t': time.strftime('%T', time.localtime(start)), 'ts': round(start, 3), 'path': path,
                             'after_s': round(time.time() - start, 2), 'error': body[:160]})


def get_once(path, kind=None):
    start = time.time()
    try:
        with urllib.request.urlopen(base + path, timeout=15) as response:
            body = response.read().decode(errors='replace').strip()
            ok = response.status == 200 and body.startswith('ok ')
    except Exception as error:  # noqa: BLE001
        ok, body = False, f'{type(error).__name__}: {error}'
    record(path, start, ok, body, kind, [round(start, 3), round(time.time(), 3)])


def upload_once(label, pieces, gap, size=4096):
    start = time.time()
    sent = 0.0
    try:
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=30)
        connection.putrequest('POST', '/upload')
        connection.putheader('Content-Type', 'application/octet-stream')
        connection.putheader('Content-Length', str(size * pieces))
        connection.putheader('Connection', 'close')
        connection.endheaders()
        for n in range(pieces):
            if n:
                time.sleep(gap)
            connection.send(b'x' * size)
        sent = time.time()
        response = connection.getresponse()
        body = response.read().decode(errors='replace').strip()
        received = response.getheader('X-Received')
        ok = response.status == 200 and body.startswith('ok ') and received == str(size * pieces)
        if not ok:
            body = f'HTTPError: HTTP {response.status}, the app read {received} bytes: {body[:80]}'
        connection.close()
    except Exception as error:  # noqa: BLE001
        ok, body = False, f'{type(error).__name__}: {error}'
    record(label, start, ok, body, 'uploads', [round(start, 3), round(sent, 3), round(time.time(), 3)])


def get(path, pause, kind=None, delay=0.0):
    time.sleep(delay)
    while not os.path.exists(stop_file):
        get_once(path, kind)
        time.sleep(pause)


def upload(delay):
    time.sleep(delay)
    while not os.path.exists(stop_file):
        upload_once('POST /upload', 8, 0.2)
        time.sleep(0.05)


def watch_reloads():
    """Start the two probes of each reload as soon as bin/docker traces it."""
    try:
        offset = os.path.getsize(trace)  # the reloads of runs before this traffic are not probed
    except OSError:
        offset = 0
    while not os.path.exists(stop_file):
        try:
            if os.path.getsize(trace) < offset:
                offset = 0  # run_deploy started a new trace
            with open(trace) as f:
                f.seek(offset)
                lines = f.readlines()
                offset = f.tell()
        except OSError:
            lines = []
        for line in lines:
            if ' docker exec ' in line and ' caddy reload ' in line:
                for target, args in ((upload_once, ('POST /upload (at a reload)', 12, 0.2)),
                                     (get_once, ('/slow?ms=6500', 'long'))):
                    probe = threading.Thread(target=target, args=args)
                    probe.start()
                    probes.append(probe)
        time.sleep(0.02)


threads = [threading.Thread(target=get, args=('/', 0.02)) for _ in range(4)]
threads += [threading.Thread(target=get, args=('/slow?ms=1500', 0.05)) for _ in range(2)]
if full:
    threads += [threading.Thread(target=get, args=('/slow?ms=8000', 0.05, 'long', 2.7 * n)) for n in range(3)]
    threads += [threading.Thread(target=upload, args=(0.8 * n,)) for n in range(2)]
    if trace:
        threads.append(threading.Thread(target=watch_reloads))
began = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join()
for t in probes:  # none is added once watch_reloads has returned
    t.join()
summary = {'total': stats['total'], 'failed': stats['failed'], 'served': dict(served), 'failures': failures,
           'began': round(began, 3), 'ended': round(time.time(), 3), 'reload_probes': len(probes) // 2,
           'full': full, 'long': spans['long'], 'uploads': spans['uploads']}
with open(out, 'w') as f:
    json.dump(summary, f, indent=1)
print(f"{summary['total']} requests, {summary['failed']} failed; served {dict(served)}"
      + (f"; {len(spans['long'])} long requests and {len(spans['uploads'])} uploads succeeded, "
         f"{summary['reload_probes']} reloads probed" if full else '')
      + (f"; first failures {failures[:3]}" if failures else ''))
