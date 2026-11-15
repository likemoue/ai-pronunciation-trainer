"""gunicorn settings for the container (CMD: gunicorn -c gunicorn.conf.py webApp:app)."""
import ctypes
import os

from gunicorn.glogging import Logger as _GunicornLogger

import access_log as _access_log
import logging_setup as _logging_setup
import readiness as _readiness

bind = os.environ.get('BIND', '0.0.0.0:3000')
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
# Threads let a worker serve the page, samples and TTS while one thread scores.
# Scoring is serialised per worker by a lock in lambdaSpeechToScore, and Piper
# synthesis by one in piperTTS, and every recording or text waiting for its
# lock keeps its thread. So each worker takes at most SCORING_QUEUE_LIMIT
# recordings (threads - 4: 20) and PIPER_QUEUE_LIMIT texts to synthesise (2)
# at a time and answers the next ones at once with 503 and Retry-After; the
# browser sends the recording again by itself, or reads the text with its own
# voice. At least 2 threads per worker stay free for the page, samples and
# /healthz. Two workers take a class of 40 recordings sent at once.
# With threads, `timeout` only restarts a worker whose main loop hangs; a slow
# request is not interrupted. Every request is bounded on its own: decoding by
# AUDIO_DECODE_TIMEOUT, recordings by MAX_AUDIO_SECONDS, Whisper by
# WHISPER_MAX_NEW_TOKENS and speech synthesis by PIPER_MAX_PHONEMES. gunicorn
# does not bound a slow upload: a thread reading a stalled body waits. In
# production, Caddy (deploy/deploy.sh) buffers every body before the app gets
# it and drops clients that take over 60 s to send one; the colours listen on
# 127.0.0.1 only, so every request goes through it.
worker_class = 'gthread'
threads = int(os.environ.get('GUNICORN_THREADS', '24'))
# A worker accepts no more connections than it has threads. Both workers accept
# from the same socket, and in a burst one of them used to take most of the
# recordings and turn half of them away while the other sat idle; a full
# worker now leaves new connections to the other one. That leaves no
# connection for keep-alive, so each response closes its connection (Caddy
# opens a new one on 127.0.0.1, which costs nothing, and never reuses one that
# gunicorn is about to close; its `keepalive 4s` in deploy/deploy.sh only
# matters if gunicorn keeps connections open again).
worker_connections = threads
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
# Time a stopping worker has to finish the requests it has accepted, including
# recordings queued behind the one being scored. Cloudflare gives up on a
# request after 125 s, so nothing that could still be answered is cut.
# deploy/deploy.sh gives a colour 130 s (docker stop -t) before it is killed.
graceful_timeout = int(os.environ.get('GUNICORN_GRACEFUL_TIMEOUT', '120'))
keepalive = 0
# Worker heartbeat files on tmpfs rather than the container's overlay filesystem.
if os.path.isdir('/dev/shm'):
    worker_tmp_dir = '/dev/shm'
# Each worker loads its own models after the fork (OpenMP thread pools are not fork-safe).
preload_app = False

accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('LOG_LEVEL', 'info')


class JsonLogger(_GunicornLogger):
    """gunicorn's own messages and the access log as JSON lines.

    The access log has one object per request (access_log.py): no client IP,
    no query string, no body. gunicorn's access_log_format cannot produce valid
    JSON: it does not escape backslashes or newlines."""

    def setup(self, cfg):
        super().setup(cfg)
        for handler in self.error_log.handlers:
            handler.setFormatter(_logging_setup.JsonFormatter())

    def access(self, resp, req, environ, request_time):
        if not self.cfg.accesslog:
            return
        try:
            self.access_log.info(_access_log.from_gunicorn(resp, environ, request_time))
        except Exception:
            self.exception('Could not write the access log entry')


logger_class = JsonLogger


# Each worker writes a readiness marker after a successful warm-up (webApp.py);
# healthcheck.py and /readyz count the markers of live workers.
def on_starting(server):
    _readiness.reset()


def child_exit(server, worker):
    _readiness.forget(worker.pid)


def post_worker_init(worker):
    """Load the models in the background as soon as the worker is up."""
    import webApp
    webApp.start_warm_up()


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
