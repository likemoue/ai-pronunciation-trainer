"""Logging, readiness markers, the JSON access log and the deploy script."""
import datetime
import json
import logging
import os
import runpy
import shutil
import subprocess
import sys

import pytest

import access_log

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_app_warnings_are_logged_and_library_warnings_are_not():
    # epitran calls logging.basicConfig(level=CRITICAL) when it is imported;
    # webApp has to configure logging first, or every warning it logs is lost.
    # Library warnings stay off: Piper warns once for every phoneme its voice
    # lacks, so one crafted text wrote hundreds of lines.
    code = '\n'.join([
        'import logging, webApp',
        'webApp.app.logger.warning("probe-warning")',
        'logging.getLogger("piper.phoneme_ids").warning("library-warning")',
        'logging.getLogger("piper.phoneme_ids").error("library-error")',
        'print("LEVEL", webApp.app.logger.getEffectiveLevel())',
    ])
    env = {**os.environ, 'PRELOAD_LANGUAGES': '', 'PYTHONUTF8': '1'}
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-3000:]
    assert 'probe-warning' in result.stderr
    assert 'library-warning' not in result.stderr
    assert 'library-error' in result.stderr
    level = int(result.stdout.split('LEVEL')[-1].split()[0])
    assert level <= logging.INFO


def test_worker_is_ready_at_once_when_nothing_is_preloaded(monkeypatch, tmp_path):
    import webApp
    monkeypatch.setattr(webApp, 'READY_DIR', str(tmp_path))
    monkeypatch.setenv('PRELOAD_LANGUAGES', '')
    webApp._warm_up_models()
    assert (tmp_path / str(os.getpid())).exists()


def test_preloading_a_disabled_language_is_reported(monkeypatch, tmp_path, caplog):
    import webApp
    monkeypatch.setattr(webApp, 'READY_DIR', str(tmp_path))
    monkeypatch.setenv('PRELOAD_LANGUAGES', 'de')
    with caplog.at_level(logging.WARNING):
        webApp._warm_up_models()
    assert 'not in ENABLED_LANGUAGES' in caplog.text


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


def test_gunicorn_writes_the_access_log_as_json(tmp_path):
    pytest.importorskip('fcntl')  # gunicorn only runs on POSIX
    gunicorn_config = pytest.importorskip('gunicorn.config')
    settings = runpy.run_path(os.path.join(ROOT, 'gunicorn.conf.py'))
    cfg = gunicorn_config.Config()
    for name in ('logger_class', 'post_request', 'on_starting', 'child_exit', 'timeout', 'workers'):
        cfg.set(name, settings[name])
    log_file = tmp_path / 'access.log'
    cfg.set('accesslog', str(log_file))
    logger = cfg.logger_class(cfg)

    class Response:
        status = '200 OK'
        sent = 5
        headers = [('X-Request-ID', 'abc')]

    logger.access(Response(), None, {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/a"b\\c\nd'},
                  datetime.timedelta(milliseconds=7))
    for handler in logger.access_log.handlers:
        handler.flush()
    lines = log_file.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record['path'] == '/a"b\\c\nd' and record['rid'] == 'abc' and record['ms'] == 7


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


@pytest.mark.skipif(os.name == 'nt', reason='needs a POSIX bash')
def test_deploy_script_parses():
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('bash is not installed')
    with open(os.path.join(ROOT, 'deploy', 'deploy.sh'), encoding='utf-8') as f:
        subprocess.run([bash, '-n'], input=f.read(), text=True, check=True)
