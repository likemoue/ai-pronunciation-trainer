"""Docker HEALTHCHECK: healthy once every gunicorn worker has finished its warm-up.

It reads the marker files the workers write (readiness.py) instead of calling
the HTTP API, so a health probe never waits in the queue behind scoring requests.
"""
import sys

import readiness

sys.exit(0 if readiness.ready_workers() >= readiness.expected_workers() else 1)
