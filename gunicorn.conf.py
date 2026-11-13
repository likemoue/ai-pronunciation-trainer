"""gunicorn settings for the container (CMD: gunicorn -c gunicorn.conf.py webApp:app)."""
import ctypes
import os
import shutil

from gunicorn.glogging import Logger as _GunicornLogger

import access_log as _access_log

bind = os.environ.get('BIND', '0.0.0.0:3000')
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
worker_class = 'sync'
# Cloudflare gives up after 125 s (error 524), so a request that runs longer
# only wastes a worker.
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
graceful_timeout = int(os.environ.get('GUNICORN_GRACEFUL_TIMEOUT', '30'))
keepalive = 5
# Worker heartbeat files on tmpfs rather than the container's overlay filesystem.
if os.path.isdir('/dev/shm'):
    worker_tmp_dir = '/dev/shm'
# Each worker loads its own models after the fork (torch/OpenMP is not fork-safe).
preload_app = False

accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('LOG_LEVEL', 'info')


class JsonAccessLogger(_GunicornLogger):
    """Writes one JSON object per request (access_log.py): no client IP, no
    query string, no body. gunicorn's access_log_format cannot produce valid
    JSON: it does not escape backslashes or newlines."""

    def access(self, resp, req, environ, request_time):
        if not self.cfg.accesslog:
            return
        try:
            self.access_log.info(_access_log.from_gunicorn(resp, environ, request_time))
        except Exception:
            self.exception('Could not write the access log entry')


logger_class = JsonAccessLogger

# Each worker writes READY_DIR/<pid> after a successful warm-up (webApp.py);
# healthcheck.py counts the markers of live workers.
READY_DIR = os.environ.get('READY_DIR', '/tmp/aipt-ready')


def on_starting(server):
    shutil.rmtree(READY_DIR, ignore_errors=True)
    os.makedirs(READY_DIR, exist_ok=True)


def child_exit(server, worker):
    try:
        os.remove(os.path.join(READY_DIR, str(worker.pid)))
    except FileNotFoundError:
        pass


try:
    _malloc_trim = ctypes.CDLL('libc.so.6').malloc_trim
except (OSError, AttributeError):  # not glibc
    _malloc_trim = None


def post_request(worker, req, environ, resp):
    # glibc keeps memory freed after a large request (decoded audio, Whisper
    # buffers) in the heap, so a few unusual recordings could leave each worker
    # about 1 GB larger. Returning it takes a few ms after the response is sent.
    if _malloc_trim is not None and req.method == 'POST':
        _malloc_trim(0)
