#!/usr/bin/env python3
# Stub smoke test (harness): GET / must answer "ok <sha>".
# SMOKE_FAIL_PORTS=<port>[,<port>] fails it for those ports; SMOKE_SLEEP delays it; HARNESS_FIRE is the signal hook.
import os, subprocess, sys, time, urllib.parse, urllib.request

url = sys.argv[1].rstrip('/')
port = str(urllib.parse.urlparse(url).port)
where = 'prod' if port == os.environ.get('PROD_PORT') else 'staging'
if os.environ.get('HARNESS_FIRE'):
    subprocess.call([os.environ['HARNESS_FIRE'], 'smoke-' + where])
time.sleep(float(os.environ.get('SMOKE_SLEEP', '0')))
try:
    body = urllib.request.urlopen(url + '/', timeout=5).read().decode().strip()
except Exception as error:
    print('smoke FAIL', error)
    sys.exit(1)
print('smoke', where, body)
if port in os.environ.get('SMOKE_FAIL_PORTS', '').split(','):
    print('smoke FAIL (injected)')
    sys.exit(1)
sys.exit(0 if body.startswith('ok ') else 1)
