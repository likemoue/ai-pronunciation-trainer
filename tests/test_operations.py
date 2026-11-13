"""Health, readiness, version, logging, the JSON access log and the deploy script."""
import ast
import datetime
import glob
import io
import json
import logging
import os
import runpy
import shutil
import subprocess
import sys

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


# ------------------------------------------------------------------ deploy script

def test_smoke_test_scores_the_warm_up_sentence():
    # The reference voice reads this sentence reliably (see WARMUP_SENTENCES);
    # a sentence it misreads would make deploys fail at random.
    import lambdaSpeechToScore
    with open(os.path.join(ROOT, 'deploy', 'smoke_test.py'), encoding='utf-8') as f:
        source = f.read()
    assert f"SENTENCE = {lambdaSpeechToScore.WARMUP_SENTENCES['en']!r}" in source


@pytest.mark.skipif(os.name == 'nt', reason='needs a POSIX bash')
def test_deploy_script_parses():
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('bash is not installed')
    with open(os.path.join(ROOT, 'deploy', 'deploy.sh'), encoding='utf-8') as f:
        subprocess.run([bash, '-n'], input=f.read(), text=True, check=True)
