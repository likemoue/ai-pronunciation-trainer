# HEALTHCHECK: healthy WARMUP seconds after start, if the commit is "good" and no fault is injected.
import os, sys, time, urllib.request

if open('/srv/HEALTH').read().strip() != 'good':
    sys.exit(1)
if os.environ.get('FORCE_UNHEALTHY') == '1':
    sys.exit(1)
try:
    started = float(open('/tmp/started').read())
except (OSError, ValueError):
    sys.exit(1)
if time.time() - started < float(os.environ.get('WARMUP', '2')):
    sys.exit(1)
urllib.request.urlopen('http://127.0.0.1:3000/', timeout=1).read()
