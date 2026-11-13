"""Readiness markers, shared by the workers, /readyz and the Docker HEALTHCHECK.

Each gunicorn worker writes READY_DIR/<pid> once its warm-up has scored a
spoken sentence (webApp._warm_up_models), and gunicorn.conf.py removes the
marker when the worker exits. The container is ready when every worker has a
marker; markers of processes that are gone do not count.

This module imports nothing from the app, so healthcheck.py stays cheap.
"""
import os
import shutil

READY_DIR = os.environ.get('READY_DIR', '/tmp/aipt-ready')


def expected_workers() -> int:
    """gunicorn starts WEB_CONCURRENCY workers (gunicorn.conf.py, default 2)."""
    return int(os.environ.get('WEB_CONCURRENCY', '2'))


def _alive(pid: int) -> bool:
    if os.name == 'nt':  # os.kill(pid, 0) would terminate the process on Windows
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:  # it exists but belongs to another user
        return True


def ready_workers() -> int:
    """Live workers that have finished their warm-up."""
    try:
        names = os.listdir(READY_DIR)
    except FileNotFoundError:
        return 0
    return sum(1 for name in names if name.isdigit() and _alive(int(name)))


def mark_ready(pid=None):
    os.makedirs(READY_DIR, exist_ok=True)
    with open(os.path.join(READY_DIR, str(pid or os.getpid())), 'w') as marker:
        marker.write('ready\n')


def forget(pid):
    try:
        os.remove(os.path.join(READY_DIR, str(pid)))
    except FileNotFoundError:
        pass


def reset():
    """Remove every marker (gunicorn calls this before it starts the workers)."""
    shutil.rmtree(READY_DIR, ignore_errors=True)
    os.makedirs(READY_DIR, exist_ok=True)
