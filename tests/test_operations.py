"""Health, readiness, version, logging, the JSON access log and the deploy script."""
import ast
import datetime
import glob
import http.server
import io
import json
import logging
import os
import re
import runpy
import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest

import access_log
import logging_setup
import readiness

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def ready_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(readiness, 'READY_DIR', str(tmp_path))
    return tmp_path


# ------------------------------------------------------------------ health and readiness

def test_healthz(client):
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'ok'
    assert response.headers['Content-Type'].startswith('application/json')


def test_readyz_counts_the_markers_of_live_workers(client, monkeypatch, ready_dir):
    monkeypatch.setenv('WEB_CONCURRENCY', '2')
    assert client.get('/readyz').status_code == 503
    (ready_dir / str(os.getpid())).write_text('ready\n')
    response = client.get('/readyz')
    assert response.status_code == 503
    assert response.get_json()['ready_workers'] == 1
    monkeypatch.setenv('WEB_CONCURRENCY', '1')
    response = client.get('/readyz')
    assert response.status_code == 200
    body = response.get_json()
    assert body['ready_workers'] == 1 and body['expected_workers'] == 1


@pytest.mark.skipif(os.name == 'nt', reason='markers of dead processes are only detected on POSIX')
def test_markers_of_dead_workers_do_not_count(ready_dir):
    dead = subprocess.Popen([sys.executable, '-c', 'pass'])
    dead.wait()
    (ready_dir / str(dead.pid)).write_text('ready\n')
    (ready_dir / 'not-a-pid').write_text('ready\n')
    assert readiness.ready_workers() == 0


def test_healthcheck_script_uses_the_markers(monkeypatch, ready_dir):
    env = {**os.environ, 'READY_DIR': str(ready_dir), 'WEB_CONCURRENCY': '1'}
    script = os.path.join(ROOT, 'healthcheck.py')
    assert subprocess.run([sys.executable, script], env=env).returncode == 1
    (ready_dir / str(os.getpid())).write_text('ready\n')
    assert subprocess.run([sys.executable, script], env=env).returncode == 0


def test_version(client, monkeypatch):
    monkeypatch.setenv('GIT_SHA', 'abc1234')
    assert client.get('/version').get_json()['git_sha'] == 'abc1234'


def test_importing_the_app_does_not_start_the_warm_up():
    import webApp
    assert webApp._warm_up_started is False


def test_worker_is_ready_at_once_when_nothing_is_preloaded(monkeypatch, ready_dir):
    import webApp
    monkeypatch.setenv('PRELOAD_LANGUAGES', '')
    webApp._warm_up_models()
    assert (ready_dir / str(os.getpid())).exists()


def test_preloading_a_disabled_language_is_reported(monkeypatch, ready_dir, caplog):
    import webApp
    monkeypatch.setenv('PRELOAD_LANGUAGES', 'de')
    with caplog.at_level(logging.WARNING):
        webApp._warm_up_models()
    assert 'not in ENABLED_LANGUAGES' in caplog.text


def test_a_failed_warm_up_leaves_the_worker_not_ready(monkeypatch, ready_dir, caplog):
    import lambdaSpeechToScore
    import webApp
    monkeypatch.setenv('PRELOAD_LANGUAGES', 'en')
    monkeypatch.setattr(webApp.piperTTS, 'is_available', lambda: False)
    monkeypatch.setattr(lambdaSpeechToScore, 'warm_up', lambda language: False)
    with caplog.at_level(logging.INFO):
        webApp._warm_up_models()
    assert not (ready_dir / str(os.getpid())).exists()
    assert 'Warm-up FAILED for en' in caplog.text


# ------------------------------------------------------------------ application logs

def test_app_logs_from_info_and_libraries_only_log_errors():
    # epitran calls logging.basicConfig(level=CRITICAL) when it is imported;
    # webApp has to configure logging first, or every warning it logs is lost.
    # Library warnings stay off: Piper warns once for every phoneme its voice
    # lacks, so one crafted text wrote hundreds of lines.
    code = '\n'.join([
        'import logging, webApp',
        'logging.basicConfig(level=logging.CRITICAL)',  # what epitran does on import
        'webApp.logger.info("probe-info")',
        'webApp.lambdaSpeechToScore.logger.warning("probe-warning")',
        'logging.getLogger("piper.phoneme_ids").warning("library-warning")',
        'logging.getLogger("piper.phoneme_ids").error("library-error")',
    ])
    env = {**os.environ, 'PRELOAD_LANGUAGES': '', 'PYTHONUTF8': '1'}
    env.pop('LOG_LEVEL', None)
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-3000:]
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith('{')]
    messages = {record['msg']: record for record in records}
    assert messages['probe-info']['logger'] == 'aipt.webApp'
    assert messages['probe-info']['level'] == 'info'
    assert 'probe-warning' in messages
    assert 'library-error' in messages
    assert 'library-warning' not in result.stderr


def test_log_lines_are_json_with_the_request_id():
    import webApp
    stream = io.StringIO()
    logger = logging_setup.get_logger('test-json')
    handler = logging_setup.json_handler(stream)
    logger.addHandler(handler)
    try:
        ray = '8f3b2a1c9d4e5f60-SIN'
        with webApp.app.test_request_context('/', headers={'CF-Ray': ray}):
            webApp.app.preprocess_request()
            logger.info('hello\n{"forged": 1}', extra={'fields': {'total_ms': 5, 'msg': 'overwritten?'}})
    finally:
        logger.removeHandler(handler)
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record['msg'] == 'hello\n{"forged": 1}'
    assert record['rid'] == ray
    assert record['total_ms'] == 5
    assert record['t'].endswith('Z')


def test_exceptions_are_logged_with_their_traceback():
    stream = io.StringIO()
    logger = logging_setup.get_logger('test-exc')
    handler = logging_setup.json_handler(stream)
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError('boom')
        except RuntimeError:
            logger.exception('failed')
    finally:
        logger.removeHandler(handler)
    record = json.loads(stream.getvalue())
    assert record['level'] == 'error' and 'RuntimeError: boom' in record['exc']


def _app_modules():
    return sorted(glob.glob(os.path.join(ROOT, '*.py')))


@pytest.mark.parametrize('path', _app_modules(), ids=os.path.basename)
def test_app_modules_log_instead_of_printing(path):
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not [node.lineno for node in calls if getattr(node.func, 'id', None) == 'print']
    # Loggers come from logging_setup.get_logger, so they are in the app namespace.
    assert not [node.lineno for node in calls
                if getattr(node.func, 'attr', None) == 'getLogger'
                and os.path.basename(path) not in ('logging_setup.py',)]


# ------------------------------------------------------------------ access log

def test_access_log_line_is_valid_json_even_for_hostile_input():
    path = '/x"y\\z\n{"t":"forged","status":200}'
    line = access_log.entry('GET', path, '404 NOT FOUND', 207, 3, 'abc"\\')
    assert '\n' not in line
    record = json.loads(line)
    assert record['path'] == path
    assert record['status'] == 404 and record['bytes'] == 207 and record['ms'] == 3
    assert record['rid'] == 'abc"\\' and record['pid'] == os.getpid()


def test_access_log_path_is_truncated():
    record = json.loads(access_log.entry('GET', '/' + 'a' * 5000, '404', 0, 1, ''))
    assert len(record['path']) == access_log.MAX_PATH_CHARS


def test_access_log_from_gunicorn_objects():
    class Response:
        status = '200 OK'
        sent = 12
        headers = [('Content-Type', 'application/json'), ('X-Request-ID', 'ray-1')]

    line = access_log.from_gunicorn(Response(), {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/getSample'},
                                    datetime.timedelta(seconds=1, microseconds=2500))
    record = json.loads(line)
    assert {k: record[k] for k in ('m', 'path', 'status', 'bytes', 'ms', 'rid')} == {
        'm': 'POST', 'path': '/getSample', 'status': 200, 'bytes': 12, 'ms': 1002, 'rid': 'ray-1'}


def _gunicorn_logger(tmp_path):
    gunicorn_config = pytest.importorskip('gunicorn.config')
    settings = runpy.run_path(os.path.join(ROOT, 'gunicorn.conf.py'))
    cfg = gunicorn_config.Config()
    for name in ('logger_class', 'post_request', 'post_worker_init', 'on_starting', 'child_exit',
                 'timeout', 'workers', 'worker_class', 'threads'):
        cfg.set(name, settings[name])
    cfg.set('accesslog', str(tmp_path / 'access.log'))
    cfg.set('errorlog', str(tmp_path / 'error.log'))
    return cfg.logger_class(cfg)


def test_gunicorn_writes_the_access_log_as_json(tmp_path):
    pytest.importorskip('fcntl')  # gunicorn only runs on POSIX
    logger = _gunicorn_logger(tmp_path)

    class Response:
        status = '200 OK'
        sent = 5
        headers = [('X-Request-ID', 'abc')]

    logger.access(Response(), None, {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/a"b\\c\nd'},
                  datetime.timedelta(milliseconds=7))
    for handler in logger.access_log.handlers:
        handler.flush()
    lines = (tmp_path / 'access.log').read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record['path'] == '/a"b\\c\nd' and record['rid'] == 'abc' and record['ms'] == 7


def test_gunicorn_writes_its_own_messages_as_json(tmp_path):
    pytest.importorskip('fcntl')  # gunicorn only runs on POSIX
    logger = _gunicorn_logger(tmp_path)
    logger.info('Booting worker with pid: %s', 42)
    for handler in logger.error_log.handlers:
        handler.flush()
    record = json.loads((tmp_path / 'error.log').read_text().splitlines()[-1])
    assert record['msg'] == 'Booting worker with pid: 42' and record['logger'] == 'gunicorn.error'


def test_gunicorn_uses_threads_and_starts_the_warm_up_in_each_worker():
    pytest.importorskip('fcntl')  # gunicorn only runs on POSIX
    pytest.importorskip('gunicorn.glogging')
    settings = runpy.run_path(os.path.join(ROOT, 'gunicorn.conf.py'))
    assert settings['worker_class'] == 'gthread' and settings['threads'] >= 2
    assert settings['preload_app'] is False
    assert 'start_warm_up' in ast.dump(ast.parse(open(os.path.join(ROOT, 'gunicorn.conf.py')).read()))


def test_memory_is_returned_to_the_system_after_post_requests():
    pytest.importorskip('fcntl')  # gunicorn only runs on POSIX
    pytest.importorskip('gunicorn.glogging')
    settings = runpy.run_path(os.path.join(ROOT, 'gunicorn.conf.py'))
    post_request = settings['post_request']
    calls = []
    post_request.__globals__['_malloc_trim'] = calls.append

    class Request:
        method = 'POST'

    post_request(None, Request(), {}, None)
    Request.method = 'GET'
    post_request(None, Request(), {}, None)
    assert calls == [0]


def test_numpy_starts_no_helper_thread_for_its_blas():
    # The image runs OpenBLAS on one thread (OPENBLAS_NUM_THREADS=1 beside
    # OMP_NUM_THREADS=5 in the Dockerfile): its helper threads spun for about
    # 0.1 s after each matrix product, taking CPU from the other colour during
    # a deploy.
    if not os.path.isdir('/proc/self/task'):
        pytest.skip('counts the threads in /proc')
    code = ('import os, numpy; numpy.ones((200, 200)) @ numpy.ones((200, 200)); '
            'print(len(os.listdir("/proc/self/task")))')
    env = dict(os.environ, OMP_NUM_THREADS='5', OPENBLAS_NUM_THREADS='1')
    threads = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, check=True)
    assert threads.stdout.strip() == '1'


def test_closing_a_connection_holds_the_worker_only_briefly():
    # gthread closes each connection on the worker's main thread and lingers
    # there until the peer closes: a client that read a large answer slowly
    # through Caddy stalled the whole worker 2 s per connection.
    pytest.importorskip('fcntl')  # gunicorn only runs on POSIX
    pytest.importorskip('gunicorn.glogging')
    import inspect
    import socket
    import time
    import gunicorn.util
    from gunicorn.workers import gthread
    original = gunicorn.util.close_graceful
    try:
        settings = runpy.run_path(os.path.join(ROOT, 'gunicorn.conf.py'))
        assert 0 < settings['CLOSE_LINGER_SECONDS'] <= 0.5
        assert gunicorn.util.close_graceful.func is getattr(original, 'func', original)
        assert gunicorn.util.close_graceful.keywords == {
            'timeout': settings['CLOSE_LINGER_SECONDS'], 'max_drain': settings['CLOSE_DRAIN_BYTES']}
        # gthread looks the function up at each close, so the shorter linger reaches it.
        assert 'util.close_graceful(' in inspect.getsource(gthread)
        ours, peer = socket.socketpair()
        start = time.monotonic()
        gunicorn.util.close_graceful(ours)  # the peer never closes its side
        assert time.monotonic() - start < 1.0
        peer.close()
    finally:
        gunicorn.util.close_graceful = original


class _CountedSocket:
    """A socket that counts the bytes read from it."""

    def __init__(self, sock):
        self.sock, self.received = sock, 0

    def recv(self, size):
        data = self.sock.recv(size)
        self.received += len(data)
        return data

    def __getattr__(self, name):
        return getattr(self.sock, name)


def test_closing_a_connection_drops_a_body_the_app_did_not_read():
    # The app refuses some requests without reading their body (413, 415, 404).
    # gunicorn reset a connection that still held more than 64 KB of it, and
    # Caddy then answered 502 instead of the app's answer, about once in 600.
    pytest.importorskip('fcntl')  # gunicorn only runs on POSIX
    pytest.importorskip('gunicorn.glogging')
    import gunicorn.util
    original = gunicorn.util.close_graceful
    body = b'x' * (512 * 1024)
    try:
        runpy.run_path(os.path.join(ROOT, 'gunicorn.conf.py'))
        with socket.create_server(('127.0.0.1', 0)) as listener:
            client = socket.create_connection(listener.getsockname())
            ours, _ = listener.accept()
            errors = []

            def send():  # the body, at loopback speed as Caddy sends it
                try:
                    client.sendall(body)
                    client.shutdown(socket.SHUT_WR)
                except OSError as error:  # the connection was reset
                    errors.append(error)

            sender = threading.Thread(target=send, daemon=True)
            sender.start()
            ours.recv(1, socket.MSG_PEEK)  # the body is on its way
            counted = _CountedSocket(ours)
            gunicorn.util.close_graceful(counted)
            sender.join(5)
            try:
                # Everything was read and dropped before the close. (The client
                # alone does not show a reset reliably: when gunicorn's FIN
                # arrives first, it reads a clean end of the stream.)
                assert counted.received == len(body)
                assert not errors
                assert client.recv(1) == b''
            finally:
                client.close()
    finally:
        gunicorn.util.close_graceful = original


# ------------------------------------------------------------------ deploy script

def test_smoke_test_scores_the_warm_up_sentence():
    # The reference voice reads this sentence reliably (see WARMUP_SENTENCES);
    # a sentence it misreads would make deploys fail at random.
    import lambdaSpeechToScore
    with open(os.path.join(ROOT, 'deploy', 'smoke_test.py'), encoding='utf-8') as f:
        source = f.read()
    assert f"SENTENCE = {lambdaSpeechToScore.WARMUP_SENTENCES['en']!r}" in source


class _FakeInstance(http.server.BaseHTTPRequestHandler):
    """Answers the smoke test's requests like the app. `delays` holds seconds per path; `status`, when
    set, is the answer to every request (a proxy that cannot reach the app)."""
    delays = {}
    status = None
    requests = []

    def _answer(self, code, payload, content_type='application/json'):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Security-Policy', "default-src 'self'")
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        type(self).requests.append(self.path)
        length = int(self.headers.get('Content-Length') or 0)
        data = self.rfile.read(length) if length else b''
        time.sleep(self.delays.get(self.path, 0))
        if self.status:
            return self._answer(self.status, {'error': 'The server is restarting.', 'code': 'server_unavailable'})
        if self.command == 'GET':
            pages = {'/': (b'<title>AI Pronunciation Trainer</title>', 'text/html'),
                     '/healthz': ({'status': 'ok'}, 'application/json'),
                     '/readyz': ({'ready_workers': 2}, 'application/json'),
                     '/version': ({'git_sha': 'abc1234'}, 'application/json')}
            payload, content_type = pages.get(self.path, ({'error': 'not found'}, 'application/json'))
            return self._answer(200 if self.path in pages else 404, payload, content_type)
        if self.headers.get('Content-Type') != 'application/json':
            return self._answer(415, {'error': 'JSON only', 'code': 'unsupported_media_type'})
        request = json.loads(data)
        if self.path == '/getSample':
            if request.get('category') not in (0, 1, 2, 3):
                return self._answer(400, {'error': 'bad category', 'code': 'bad_request'})
            return self._answer(200, {'real_transcript': ['I have a cat.']})
        if self.path == '/getAudioFromText':
            return self._answer(200, {'wavBase64': 'UklGRg=='})
        return self._answer(200, {'pronunciation_accuracy': '100', 'real_transcript': request.get('title')})

    do_GET = do_POST = _handle

    def log_message(self, *args):
        pass


class _QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass   # a client that gave up waiting


@pytest.fixture
def fake_instance(monkeypatch):
    monkeypatch.setattr(_FakeInstance, 'delays', {})
    monkeypatch.setattr(_FakeInstance, 'status', None)
    monkeypatch.setattr(_FakeInstance, 'requests', [])
    server = _QuietServer(('127.0.0.1', 0), _FakeInstance)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}', _FakeInstance
    server.shutdown()
    server.server_close()


def _smoke(base, *options):
    start = time.time()
    result = subprocess.run([sys.executable, os.path.join(ROOT, 'deploy', 'smoke_test.py'), base, *options],
                            capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout, time.time() - start


def test_smoke_test_passes_against_an_instance_that_answers(fake_instance):
    base, _ = fake_instance
    code, out, _ = _smoke(base)
    assert code == 0, out
    assert 'Smoke test passed.' in out


def test_smoke_test_waits_as_long_as_its_timeout_for_a_busy_instance(fake_instance):
    # deploy.sh gives the checks after a switch 60 s: the colour that has just
    # taken the traffic may make /healthz wait behind recordings.
    base, instance = fake_instance
    instance.delays = {'/healthz': 1.5}
    code, out, _ = _smoke(base, '--timeout', '0.5')
    assert code == 1 and 'FAIL /healthz no answer' in out, out
    code, out, _ = _smoke(base, '--timeout', '5')
    assert code == 0, out


def test_smoke_test_stops_at_once_when_nothing_answers():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    code, out, seconds = _smoke(f'http://127.0.0.1:{port}', '--timeout', '60')
    assert code == 1 and 'the instance does not answer' in out, out
    assert seconds < 30


def test_smoke_test_stops_at_once_on_a_gateway_error(fake_instance):
    base, instance = fake_instance
    instance.status = 502
    code, out, seconds = _smoke(base, '--timeout', '60')
    assert code == 1 and 'FAIL / 502' in out and 'the instance does not answer' in out, out
    assert instance.requests == ['/']


def _bash():
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('bash is not installed')
    return bash


@pytest.mark.skipif(os.name == 'nt', reason='needs a POSIX bash')
def test_deploy_script_parses():
    with open(os.path.join(ROOT, 'deploy', 'deploy.sh'), encoding='utf-8') as f:
        subprocess.run([_bash(), '-n'], input=f.read(), text=True, check=True)


def _shell_default(script, name):
    """The default in a line NAME=${NAME:-default} of a shell script."""
    match = re.search(r'^%s=\$\{%s:-([^}]*)\}$' % (name, name), script, re.M)
    assert match, f'{name} has no default'
    return match.group(1)


def test_deploy_script_timings_fit_together():
    # The harness (deploy/test/) runs with short timings, so only this test sees
    # the production ones that deploy/RUNBOOK.md and CLAUDE.md describe.
    with open(os.path.join(ROOT, 'deploy', 'deploy.sh'), encoding='utf-8') as f:
        script = f.read()
    read_body = int(_shell_default(script, 'READ_BODY_SECONDS'))
    margin = int(_shell_default(script, 'DRAIN_MARGIN'))
    stop = int(_shell_default(script, 'STOP_TIMEOUT'))
    smoke = int(_shell_default(script, 'PROD_SMOKE_TIMEOUT'))
    assert (read_body, margin, stop, smoke) == (60, 5, 130, 60)
    # The drain covers exactly the time Caddy gives a client to send its body.
    assert 'read_body @READ_BODY_SECONDS@s' in script
    # A stopping worker finishes its requests before docker kills it, and
    # Cloudflare (125 s) gives up on a request between the two.
    with open(os.path.join(ROOT, 'gunicorn.conf.py'), encoding='utf-8') as f:
        graceful = re.search(r"GUNICORN_GRACEFUL_TIMEOUT', '(\d+)'", f.read())
    assert graceful and int(graceful.group(1)) < 125 < stop


@pytest.mark.skipif(os.name == 'nt', reason='needs a POSIX bash')
def test_deploy_script_help_names_the_rollbacks():
    out = subprocess.run([_bash(), os.path.join(ROOT, 'deploy', 'deploy.sh'), '--help'],
                         capture_output=True, text=True, check=True).stdout
    assert 'deploy/deploy.sh --rollback ' in out
    assert '--rollback-legacy can bring it' in out


@pytest.mark.skipif(os.name == 'nt', reason='needs a POSIX bash, git and flock')
def test_deploy_script_refuses_commits_older_than_the_oldest_release(tmp_path):
    # Commits from before 4290c3e have the unscreened sentences or the voice
    # licensed for research only; deploy.sh must never deploy them.
    if not (shutil.which('git') and shutil.which('flock')):
        pytest.skip('needs git and flock')
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}

    def git(*args, cwd=tmp_path):
        return subprocess.run(['git', *args], cwd=cwd, env=env, capture_output=True, text=True,
                              check=True).stdout.strip()

    git('init', '-q', '--bare', '-b', 'main', 'origin.git')
    git('clone', '-q', 'origin.git', 'work')
    work = tmp_path / 'work'
    (work / 'deploy').mkdir()
    (work / 'deploy' / 'smoke_test.py').write_text('print("smoke")\n')
    shas = []
    for name in ('old', 'oldest-release', 'new'):
        (work / 'release').write_text(name)
        git('add', '-A', cwd=work)
        git('commit', '-qm', name, cwd=work)
        shas.append(git('rev-parse', 'HEAD', cwd=work))
    git('push', '-q', 'origin', 'HEAD:main', cwd=work)
    git('clone', '-q', 'origin.git', 'repo')
    stubs = tmp_path / 'bin'
    stubs.mkdir()
    (stubs / 'docker').write_text('#!/bin/sh\n# No containers; every docker command fails.\nexit 1\n')
    (stubs / 'docker').chmod(0o755)
    env.update(PATH=f'{stubs}{os.pathsep}{os.environ["PATH"]}', APP='aipt-test', REPO_DIR=str(tmp_path / 'repo'),
               DEPLOY_LOG=str(tmp_path / 'state' / 'deploys.log'), OLDEST_RELEASE=shas[1],
               SKIP_CI_CHECK='1', SYSTEM_REFRESH='test')

    def deploy(ref):
        return subprocess.run([_bash(), os.path.join(ROOT, 'deploy', 'deploy.sh'), ref], cwd=tmp_path / 'repo',
                              env=env, capture_output=True, text=True, timeout=120)

    old = deploy(shas[0][:7])
    assert old.returncode == 1
    assert 'does not contain' in old.stderr and 'Building' not in old.stdout, old.stdout + old.stderr
    for ref in (shas[1][:7], 'origin/main'):
        accepted = deploy(ref)   # refused only by the stub docker, at the build
        assert 'does not contain' not in accepted.stderr, accepted.stderr
        assert 'SYSTEM_REFRESH=test (SYSTEM_REFRESH)' in accepted.stdout, accepted.stdout + accepted.stderr
    # GitHub being down does not stop a deploy: the refs fetched earlier are used.
    git('remote', 'set-url', 'origin', str(tmp_path / 'gone.git'), cwd=tmp_path / 'repo')
    offline = deploy(shas[0][:7])
    assert 'Warning: could not fetch origin' in offline.stderr and 'does not contain' in offline.stderr
