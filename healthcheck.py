"""Docker HEALTHCHECK: healthy once every gunicorn worker has finished its warm-up.

It reads the marker files the workers write instead of calling the HTTP API,
so a health probe never waits in the queue behind scoring requests.
"""
import os
import sys

ready_dir = os.environ.get('READY_DIR', '/tmp/aipt-ready')
expected = int(os.environ.get('WEB_CONCURRENCY', '2'))
alive = 0
try:
    for name in os.listdir(ready_dir):
        try:
            os.kill(int(name), 0)
            alive += 1
        except (ValueError, ProcessLookupError):
            pass
except FileNotFoundError:
    pass
sys.exit(0 if alive >= expected else 1)
