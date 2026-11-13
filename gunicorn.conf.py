"""gunicorn settings for the container (CMD: gunicorn -c gunicorn.conf.py webApp:app)."""
import os
import shutil

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
# One JSON object per request: no client IP, no query string, no body.
access_log_format = (
    '{"t":"%(t)s","rid":"%({x-request-id}o)s","m":"%(m)s","path":"%(U)s",'
    '"status":%(s)s,"bytes":%(B)s,"ms":%(M)s,"pid":%(p)s}'
)

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
