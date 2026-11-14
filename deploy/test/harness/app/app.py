# Stand-in for the real app (harness): GET / -> "ok <GIT_SHA>", /version -> JSON,
# /slow?ms=N answers after N ms. On SIGTERM it stops accepting connections and
# lets requests in flight finish (at most STOP_DELAY s), like gunicorn.
import http.server
import json
import os
import signal
import sys
import threading
import time
import urllib.parse

MODE = open('/srv/HEALTH').read().strip()
if MODE == 'crash' or os.environ.get('FORCE_CRASH') == '1':
    sys.exit(3)
with open('/tmp/started', 'w') as f:
    f.write(str(time.time()))

active = 0
lock = threading.Lock()


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        global active
        with lock:
            active += 1
        try:
            url = urllib.parse.urlparse(self.path)
            if url.path == '/slow':
                time.sleep(int(urllib.parse.parse_qs(url.query).get('ms', ['1000'])[0]) / 1000)
            if url.path == '/version':
                body = json.dumps({'git_sha': os.environ.get('GIT_SHA', '?')}).encode()
            else:
                body = ('ok ' + os.environ.get('GIT_SHA', '?') + '\n').encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            with lock:
                active -= 1

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(('0.0.0.0', 3000), H)
server.daemon_threads = True


def drain_and_exit():
    server.shutdown()          # stop accepting
    server.socket.close()
    deadline = time.time() + float(os.environ.get('STOP_DELAY', '3'))
    while time.time() < deadline:
        with lock:
            if active == 0:
                break
        time.sleep(0.05)
    time.sleep(float(os.environ.get('STOP_EXTRA', '0.5')))
    os._exit(0)


def on_term(*_):
    threading.Thread(target=drain_and_exit, daemon=True).start()


signal.signal(signal.SIGTERM, on_term)
server.serve_forever(poll_interval=0.05)
time.sleep(3600)  # drain_and_exit ends the process
