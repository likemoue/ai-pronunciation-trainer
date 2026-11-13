"""One JSON object per request for gunicorn's access log (see gunicorn.conf.py).

The line is built with json.dumps, so a quote, backslash or newline in the
path or in a header cannot break it or forge another entry. It records no
client IP, query string or body.
"""
import json
import os
import time

MAX_PATH_CHARS = 200


def entry(method, path, status, sent, duration_ms, request_id) -> str:
    try:
        status = int(str(status).split()[0])
    except (ValueError, IndexError):
        status = str(status)
    return json.dumps({
        't': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'rid': request_id or '',
        'm': method or '',
        'path': (path or '')[:MAX_PATH_CHARS],
        'status': status,
        'bytes': sent,
        'ms': duration_ms,
        'pid': os.getpid(),
    }, separators=(',', ':'))


def from_gunicorn(resp, environ, request_time) -> str:
    """Build the entry from the objects gunicorn passes to Logger.access()."""
    headers = getattr(resp, 'headers', None) or []
    request_id = next((value for name, value in headers if name.lower() == 'x-request-id'), '')
    duration_ms = request_time.seconds * 1000 + request_time.microseconds // 1000
    return entry(environ.get('REQUEST_METHOD'), environ.get('PATH_INFO'), getattr(resp, 'status', ''),
                 getattr(resp, 'sent', None), duration_ms, request_id)
