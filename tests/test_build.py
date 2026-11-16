"""The build stays reproducible: dependencies declared and locked, models,
images and actions pinned, and the Docker context holding what the app reads.
The build's shell scripts run here too, with stand-ins for pip and curl."""
import ast
import datetime
import glob
import hashlib
import http.server
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time

import pytest

import model_pins

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Top-level modules the app imports -> the requirement in requirements.in that provides them.
THIRD_PARTY = {
    'flask': 'flask', 'werkzeug': 'flask', 'gunicorn': 'gunicorn', 'numpy': 'numpy', 'pandas': 'pandas',
    'faster_whisper': 'faster-whisper',
    'piper': 'piper-tts', 'onnxruntime': 'onnxruntime', 'eng_to_ipa': 'eng-to-ipa',
}
# Imported only when German is enabled, which the English image does not install.
OPTIONAL = {'epitran'}
# In requirements.in without being imported: the build backend for eng-to-ipa's sdist,
# which scripts/pip_install_locked.sh installs from the lock first.
BUILD_ONLY = {'setuptools'}


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as f:
        return f.read()


def requirement_names(text):
    names = set()
    for line in text.splitlines():
        line = line.split('#')[0].strip()
        if line and not line.startswith('-'):
            names.add(re.split(r'[<>=!~;\[ ]', line)[0].lower())
    return names


def app_imports():
    local = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, '*.py'))}
    found = set()
    for path in glob.glob(os.path.join(ROOT, '*.py')) + glob.glob(os.path.join(ROOT, 'scripts', '*.py')):
        for node in ast.walk(ast.parse(read(path))):
            if isinstance(node, ast.Import):
                found.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split('.')[0])
    return {name for name in found if name not in sys.stdlib_module_names and name not in local}


def test_every_third_party_import_is_declared_in_requirements_in():
    declared = requirement_names(read('requirements.in'))
    imports = app_imports() - OPTIONAL
    unknown = imports - set(THIRD_PARTY)
    assert not unknown, f'add these to THIRD_PARTY and requirements.in: {sorted(unknown)}'
    assert {THIRD_PARTY[name] for name in imports} <= declared


def test_requirements_in_lists_nothing_the_app_does_not_import():
    used = {THIRD_PARTY[name] for name in app_imports() - OPTIONAL}
    assert requirement_names(read('requirements.in')) <= used | BUILD_ONLY


@pytest.mark.parametrize('lock', ['requirements.lock', 'requirements-dev.lock'])
def test_lock_pins_every_package_with_hashes(lock):
    text = read(lock)
    entries = re.findall(r'^([A-Za-z0-9_.-]+)==(\S+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)', text, re.M)
    pinned = {name.lower().replace('_', '-') for name, _, _ in entries}
    assert pinned and len(pinned) == len(re.findall(r'^[A-Za-z0-9_.-]+==', text, re.M))
    if lock == 'requirements.lock':
        assert requirement_names(read('requirements.in')) <= pinned
        # faster-whisper replaced transformers in phase 2; torch (most of the image) went with it.
        assert not re.search(r'^(torch|transformers|nvidia-[a-z0-9-]+)==', text, re.M)
    assert '--exclude-newer 20' in text.splitlines()[1], 'the lock records its cut-off date'


def test_whisper_and_the_voice_are_pinned():
    assert re.fullmatch(r'[0-9a-f]{40}', model_pins.WHISPER_REVISION)
    spec = model_pins.PIPER_VOICES[model_pins.DEFAULT_ENGLISH_VOICE]
    assert set(spec['sha256']) == set(model_pins.PIPER_VOICE_FILES)


def test_images_are_pinned_by_digest():
    assert re.search(r'^ARG PYTHON_IMAGE=python:3\.12\.\d+-slim-\w+@sha256:[0-9a-f]{64}$', read('Dockerfile'), re.M)
    assert re.search(r'CADDY_IMAGE:-caddy:[0-9.]+-alpine@sha256:[0-9a-f]{64}\}', read('deploy/deploy.sh'))
    for name in ('SHELLCHECK_IMAGE', 'ACTIONLINT_IMAGE', 'TRIVY_IMAGE'):
        assert re.search(rf'^  {name}: \S+@sha256:[0-9a-f]{{64}}$', read('.github/workflows/ci.yml'), re.M), name


@pytest.mark.parametrize('workflow', sorted(glob.glob(os.path.join(ROOT, '.github', 'workflows', '*.yml'))),
                         ids=os.path.basename)
def test_actions_are_pinned_by_commit_sha(workflow):
    uses = re.findall(r'uses:\s*(\S+)', read(workflow))
    assert uses
    assert all(re.fullmatch(r'[\w.-]+/[\w.-]+@[0-9a-f]{40}', action) for action in uses), uses


def copy_sources(dockerfile):
    """What the COPY instructions take from the build context (COPY --from aside)."""
    sources = []
    for line in dockerfile.replace('\\\n', ' ').splitlines():
        words = line.split()
        if words[:1] == ['COPY'] and not any(word.startswith('--from=') for word in words):
            sources += [word.rstrip('/') for word in words[1:-1] if not word.startswith('--')]
    return sources


def docker_pattern(pattern):
    """A path pattern as Docker reads it (* and ? stop at /); a directory takes what is in it."""
    parts = ('[^/]*' if char == '*' else '[^/]' if char == '?' else re.escape(char) for char in pattern)
    return re.compile(''.join(parts) + '(?:/.*)?')


def test_the_dockerfile_and_dockerignore_let_in_the_same_files():
    # deploy.sh builds from a `git archive` tar, to which .dockerignore does not
    # apply, so the COPY lines decide what the production image holds. CI builds
    # from the directory, through .dockerignore. A file let in by one and not the
    # other is missing from one of the two images.
    copied = set(copy_sources(read('Dockerfile')))
    patterns = [line.strip() for line in read('.dockerignore').splitlines()
                if line.strip() and not line.strip().startswith('#')]
    assert patterns[0] == '*', '.dockerignore leaves out everything it does not let in'
    allowed = {pattern[1:].rstrip('/') for pattern in patterns if pattern.startswith('!')}
    unused = allowed - copied
    assert not unused, f'.dockerignore lets in {sorted(unused)}, but no COPY in the Dockerfile copies it'
    missing = {source for source in copied if not any(docker_pattern(entry).fullmatch(source) for entry in allowed)}
    assert not missing, f"COPY takes {sorted(missing)}, but .dockerignore leaves it out of CI's build"
    for source in copied:
        assert glob.glob(os.path.join(ROOT, source)), f'COPY {source}: no such file'
    # `COPY *.py` takes the top-level modules only, and every module the app imports is one.
    assert not glob.glob(os.path.join(ROOT, '*', '__init__.py'))


def test_dockerfile_installs_the_lock_with_hashes_from_pypi():
    dockerfile = read('Dockerfile')
    assert 'bash /tmp/pip_install_locked.sh /opt/venv/bin/python /tmp/requirements.lock' in dockerfile
    assert 'PIP_INDEX_URL=https://pypi.org/simple' in dockerfile and 'PIP_EXTRA_INDEX_URL' not in dockerfile
    assert 'WARMUP_STRICT=1' in dockerfile
    # The models come from a stage that does not depend on the packages.
    assert re.search(r'^FROM \$\{PYTHON_IMAGE\} AS models$', dockerfile, re.M)


def test_the_build_backend_is_installed_from_the_lock_with_its_hashes():
    script = read('scripts/pip_install_locked.sh')
    assert '--no-build-isolation' in script and '--require-hashes' in script
    assert re.search(r'^setuptools==[0-9.]+ \\$', read('requirements.lock'), re.M)


def test_whisper_files_are_pinned_by_sha256():
    assert set(model_pins.WHISPER_FILES) == {'config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt'}
    assert all(re.fullmatch(r'[0-9a-f]{64}', digest) for digest in model_pins.WHISPER_FILES.values())


def test_idle_threads_do_not_spin_for_long():
    # Both colours score at once during a deploy; with GNU OpenMP's default
    # spin, each slowed the other down tenfold and recordings timed out.
    dockerfile = read('Dockerfile')
    spin = re.search(r'^\s+GOMP_SPINCOUNT=(\d+) \\$', dockerfile, re.M)
    assert spin and int(spin.group(1)) <= 100000
    # numpy's OpenBLAS does not read it, and its helper threads spun after each
    # matrix product: one thread does them (tests/test_operations.py checks
    # that numpy then starts no helper thread).
    assert re.search(r'^\s+OPENBLAS_NUM_THREADS=1 \\$', dockerfile, re.M)
    # GOMP_SPINCOUNT only reaches GNU OpenMP, which the Linux wheel of CTranslate2 bundles.
    ctranslate2 = pytest.importorskip('ctranslate2')
    libs = os.path.join(os.path.dirname(os.path.dirname(ctranslate2.__file__)), 'ctranslate2.libs')
    if not sys.platform.startswith('linux'):
        pytest.skip('the Linux wheel is the one the image installs')
    assert any(name.startswith('libgomp') for name in os.listdir(libs)), os.listdir(libs)


def test_gunicorn_drops_any_body_caddy_lets_through():
    # The app refuses some requests without reading their body. gunicorn must
    # be able to drop all of one when it closes the connection: a reset makes
    # Caddy answer 502 instead of the app's 413, 415 or 404.
    caddy = re.search(r'^\s+max_size (\d+)MB$', read('deploy/deploy.sh'), re.M)
    assert caddy
    drain = next(node.value for node in ast.parse(read('gunicorn.conf.py')).body
                 if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'CLOSE_DRAIN_BYTES')
    drain = eval(compile(ast.Expression(drain), 'gunicorn.conf.py', 'eval'), {'__builtins__': {}})
    assert drain >= int(caddy.group(1)) * 1024 * 1024


def test_no_telemetry_leaves_the_image():
    dockerfile = read('Dockerfile')
    for setting in ('HF_HUB_OFFLINE=1', 'HF_HUB_DISABLE_TELEMETRY=1', 'ORT_DISABLE_TELEMETRY=1'):
        assert setting in dockerfile, setting
    # On Windows, ONNX Runtime ignores ORT_DISABLE_TELEMETRY; this call turns its events off there.
    assert 'disable_telemetry_events()' in read('piperTTS.py')


def test_onnx_runtime_telemetry_is_off_outside_the_image_too():
    # On Linux, ONNX Runtime reads ORT_DISABLE_TELEMETRY once, when it is first
    # imported. piperTTS sets it, and in webApp's import order that comes first.
    code = textwrap.dedent('''
        import os, sys
        seen = []

        class Watch:
            def find_spec(self, name, path=None, target=None):
                if name == 'onnxruntime':
                    seen.append(os.environ.get('ORT_DISABLE_TELEMETRY'))

        sys.meta_path.insert(0, Watch())
        import webApp, piperTTS
        piperTTS.is_available()  # imports piper, which imports onnxruntime
        print(seen[:1])
    ''')
    env = {name: value for name, value in os.environ.items() if name != 'ORT_DISABLE_TELEMETRY'}
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=300)
    assert result.returncode == 0, result.stderr
    if result.stdout.split() == ['[]']:
        pytest.skip('piper-tts is not installed')
    assert result.stdout.split() == ["['1']"]


def test_smoke_test_takes_a_user_agent_for_the_canary():
    result = subprocess.run([sys.executable, os.path.join(ROOT, 'deploy', 'smoke_test.py'), '--help'],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and '--user-agent' in result.stdout
    assert '--user-agent' in read('.github/workflows/canary.yml')


def test_files_read_on_linux_keep_lf_line_endings():
    # Without these, a Windows checkout (core.autocrlf) gives them CRLF, and so
    # does a `git archive` made there.
    attributes = read('.gitattributes').splitlines()
    for pattern in ('*.sh', 'requirements*.lock', 'requirements*.in', 'Dockerfile', '.dockerignore'):
        assert f'{pattern} text eol=lf' in attributes, pattern


# ------------------------------------------------------------------ shell scripts

def posix_bash():
    """The bash to run the build's scripts with, or None. On Windows, that of Git
    for Windows in usr/bin: its bin/bash.exe puts Git's directories ahead of
    PATH, and the bash.exe in WindowsApps or System32 starts WSL instead."""
    if os.name != 'nt':
        return shutil.which('bash')
    candidates = []
    found = shutil.which('bash')
    if found and os.path.normcase(found).endswith(os.path.normcase(os.path.join('usr', 'bin', 'bash.exe'))):
        candidates.append(found)
    git = shutil.which('git')
    if git:
        here = os.path.dirname(git)
        candidates += [os.path.join(here, *[os.pardir] * up, 'usr', 'bin', 'bash.exe') for up in (1, 2)]
    return next((os.path.normpath(path) for path in candidates if os.path.isfile(path)), None)


def run_script(tmp_path, script, *args, stubs, env=None):
    """Run scripts/<script> with bash. Each command in `stubs` (name -> bash
    code) is replaced by a stand-in that comes first on PATH."""
    bash = posix_bash()
    if bash is None:
        pytest.skip('needs bash (on Windows, the one of Git for Windows)')
    stub_dir = tmp_path / 'stub-bin'
    stub_dir.mkdir(exist_ok=True)
    for name, code in stubs.items():
        stub = stub_dir / name
        stub.write_bytes(('#!/usr/bin/env bash\n' + textwrap.dedent(code).lstrip()).encode())
        stub.chmod(0o755)
    path = os.pathsep.join([str(stub_dir), os.path.dirname(bash), os.environ.get('PATH', '')])
    run_env = dict(os.environ, PATH=path, **(env or {}))
    # The real pip or curl must never run here.
    found = subprocess.run([bash, '-c', 'command -v "$@"', 'bash', *stubs], env=run_env,
                           capture_output=True, text=True, timeout=60).stdout.split()
    if [os.path.basename(os.path.dirname(command)) for command in found] != ['stub-bin'] * len(stubs):
        pytest.skip(f'{bash} does not look commands up in PATH order')
    return subprocess.run([bash, os.path.join(ROOT, 'scripts', script).replace(os.sep, '/'), *args],
                          env=run_env, capture_output=True, text=True, timeout=120)


def test_the_build_backend_keeps_its_hashes_in_a_crlf_lock(tmp_path):
    # A Windows checkout, or a `git archive` made there, can give the lock CRLF
    # line endings; mawk in the image keeps the CR when it reads a line.
    with open(os.path.join(ROOT, 'requirements.lock'), 'rb') as f:
        lock = f.read().decode().replace('\r\n', '\n')
    crlf_lock = tmp_path / 'requirements.lock'
    crlf_lock.write_bytes(lock.replace('\n', '\r\n').encode())
    copies = tmp_path / 'given-to-pip'
    copies.mkdir()
    # pip keeps a copy of each requirements file it is given, numbered from 0.
    pip = '''
        while (( $# )); do
            if [[ $1 == -r ]]; then cp "$2" "$PIP_COPIES/$(ls "$PIP_COPIES" | wc -l | tr -d ' ')"; shift; fi
            shift
        done
    '''
    result = run_script(tmp_path, 'pip_install_locked.sh', 'python', crlf_lock.as_posix(),
                        stubs={'pip': pip}, env={'PIP_COPIES': copies.as_posix()})
    assert result.returncode == 0, result.stderr
    # The first file is the build backend: setuptools with both of its hashes
    # (the wheel and the sdist), exactly as in the lock.
    entry = re.search(r'^setuptools==\S+ \\\n(?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+', lock, re.M).group(0)
    assert entry.count('--hash=sha256:') >= 2
    assert (copies / '0').read_bytes().decode() == entry


SUITES = ('debian/dists/trixie', 'debian/dists/trixie-updates', 'debian-security/dists/trixie-security')
PACKAGE_INDEXES = ('a' * 64, 'b' * 64, 'c' * 64)
# curl answers from FAKE_ARCHIVE instead of https://deb.debian.org; a missing file is an HTTP error.
CURL = '''
    url=${*: -1}
    file=$FAKE_ARCHIVE/${url#https://deb.debian.org/}
    [[ -f $file ]] || exit 22
    cat "$file"
'''


def fake_inrelease(suite, packages_sha256, date='Sat, 14 Nov 2026 04:03:02 UTC', other='0'):
    """An InRelease file shaped like Debian's, with this sha256 for main/binary-amd64/Packages."""
    codename = suite.rsplit('/', 1)[1]
    return textwrap.dedent(f'''\
        -----BEGIN PGP SIGNED MESSAGE-----
        Hash: SHA256

        Origin: Debian
        Codename: {codename}
        Date: {date}
        Valid-Until: {date}
        Architectures: all amd64 arm64
        Components: main contrib
        MD5Sum:
         {other * 32}  2208609 main/binary-amd64/Packages
        SHA256:
         {other * 64}   901945 main/binary-all/Packages
         {packages_sha256}  2208609 main/binary-amd64/Packages
         {other * 64}   303376 main/binary-amd64/Packages.xz
         {other * 64}  2214833 main/binary-arm64/Packages
        -----BEGIN PGP SIGNATURE-----

        iQIzBAEBCAAdFiEEgQ0Fdz1ug0Y
        -----END PGP SIGNATURE-----
        ''')


def fake_archive(root, indexes=PACKAGE_INDEXES, crlf=False, **fields):
    """The InRelease files of the three suites under root, where curl finds them."""
    for suite, packages_sha256 in zip(SUITES, indexes, strict=True):
        text = fake_inrelease(suite, packages_sha256, **fields)
        (root / suite).mkdir(parents=True)
        (root / suite / 'InRelease').write_bytes((text.replace('\n', '\r\n') if crlf else text).encode())
    return root


def system_refresh(tmp_path, archive):
    return run_script(tmp_path, 'system_refresh.sh', stubs={'curl': CURL}, env={'FAKE_ARCHIVE': archive.as_posix()})


def system_refresh_key(tmp_path, name, **kwargs):
    result = system_refresh(tmp_path, fake_archive(tmp_path / name, **kwargs))
    assert result.returncode == 0 and result.stderr == '', result.stderr
    assert re.fullmatch(r'debian-[0-9a-f]{16}\n', result.stdout)
    return result.stdout


def test_the_system_package_key_changes_only_with_a_package_index(tmp_path):
    key = system_refresh_key(tmp_path, 'archive')
    # Debian signs InRelease again with a new Date several times a day, and the
    # files apt in the image does not read change on their own: same key.
    assert system_refresh_key(tmp_path, 'signed-again', date='Sun, 15 Nov 2026 10:00:00 UTC', other='9') == key
    assert system_refresh_key(tmp_path, 'crlf', crlf=True) == key
    # A new package in any of the three suites changes it.
    changed = set()
    for i in range(len(SUITES)):
        indexes = PACKAGE_INDEXES[:i] + ('d' * 64,) + PACKAGE_INDEXES[i + 1:]
        changed.add(system_refresh_key(tmp_path, f'new-in-{i}', indexes=indexes))
    assert len(changed) == len(SUITES) and key not in changed


@pytest.mark.parametrize('answer', ['http error', 'login page', 'other suite', 'two indexes'])
def test_the_system_package_key_falls_back_to_the_iso_week(tmp_path, answer):
    def this_week():
        year, week, _ = datetime.datetime.now(datetime.timezone.utc).isocalendar()
        return f'week-{year}-W{week:02d}\n'

    archive = fake_archive(tmp_path / 'archive')
    security = archive / SUITES[2] / 'InRelease'
    if answer == 'http error':
        security.unlink()
    elif answer == 'login page':
        security.write_text('<html><body>Sign in to use this network</body></html>\n')
    elif answer == 'other suite':
        security.write_text(fake_inrelease(SUITES[1], PACKAGE_INDEXES[2]))
    else:
        index = f' {"e" * 64}  2208609 main/binary-amd64/Packages\n'
        security.write_text(security.read_text().replace('SHA256:\n', 'SHA256:\n' + index))
    weeks = {this_week()}
    result = system_refresh(tmp_path, archive)
    weeks.add(this_week())  # in case the week turned meanwhile
    assert result.returncode == 0
    assert result.stdout in weeks
    assert 'keying the system packages on the ISO week instead' in result.stderr


def test_the_system_package_key_reads_the_base_images_release():
    release = re.search(r'^ARG PYTHON_IMAGE=python:[0-9.]+-slim-(\w+)@', read('Dockerfile'), re.M).group(1)
    assert re.search(r'^CODENAME=(\w+)$', read('scripts/system_refresh.sh'), re.M).group(1) == release


# ------------------------------------------------------------------ model downloads

BODY = b'model bytes ' * 1000


def reply(status=200, body=BODY, length=None, stall=0.0):
    """An answer of the model server: half the body, a pause, then the rest."""
    def answer(handler):
        if status != 200:
            handler.send_error(status)
            return
        handler.send_response(200)
        handler.send_header('Content-Length', str(len(body) if length is None else length))
        handler.end_headers()
        handler.wfile.write(body[:len(body) // 2])
        handler.wfile.flush()
        time.sleep(stall)
        try:
            handler.wfile.write(body[len(body) // 2:])
        except OSError:
            pass  # the client gave up waiting
        handler.close_connection = True
    return answer


@pytest.fixture
def model_server(monkeypatch):
    """A local HTTP server that answers each request with the next of `answers`."""
    answers, requests = [], []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            answers.pop(0)(self)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.block_on_close = False
    server.handle_error = lambda request, client_address: None  # a client that gave up
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
    monkeypatch.setenv('no_proxy', '*')
    monkeypatch.setattr(model_pins, 'RETRY_DELAY', 0)
    yield f'http://127.0.0.1:{server.server_port}/model.onnx', answers, requests
    server.shutdown()
    server.server_close()


def test_a_failed_model_download_is_tried_again(model_server, tmp_path):
    url, answers, requests = model_server
    # An error from the server, then a connection that closes early, then the file.
    answers += [reply(503), reply(length=len(BODY) + 10), reply()]
    dest = tmp_path / 'model.onnx'
    assert model_pins.fetch(url, str(dest), hashlib.sha256(BODY).hexdigest())
    assert dest.read_bytes() == BODY and len(requests) == 3
    assert not os.path.exists(f'{dest}.part')


def test_a_stalled_model_download_fails_instead_of_hanging(model_server, tmp_path, monkeypatch):
    url, answers, requests = model_server
    monkeypatch.setattr(model_pins, 'DOWNLOAD_TIMEOUT', 0.2)
    monkeypatch.setattr(model_pins, 'DOWNLOAD_ATTEMPTS', 2)
    answers += [reply(stall=3), reply(stall=3)]
    dest = tmp_path / 'model.onnx'
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='Could not download'):
        model_pins.fetch(url, str(dest), hashlib.sha256(BODY).hexdigest())
    assert time.monotonic() - started < 2.5 and len(requests) == 2
    assert not dest.exists() and not os.path.exists(f'{dest}.part')


@pytest.mark.parametrize('first, error', [(reply(404), '404'), (reply(body=b'not the model'), 'pinned sha256')],
                         ids=['missing', 'other bytes'])
def test_a_wrong_model_download_is_not_tried_again(model_server, tmp_path, first, error):
    url, answers, requests = model_server
    answers += [first, reply()]
    dest = tmp_path / 'model.onnx'
    with pytest.raises(RuntimeError, match=error):
        model_pins.fetch(url, str(dest), hashlib.sha256(BODY).hexdigest())
    assert len(requests) == 1
    assert not dest.exists() and not os.path.exists(f'{dest}.part')


def test_the_browser_tests_score_with_answers_the_server_gives():
    # e2e/result.spec.mjs answers the page's scoring request with e2e/scores/*.json, made
    # by the server's own code (e2e/scores/make_scores.py): they must still be what it makes.
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location('make_scores', os.path.join(ROOT, 'e2e', 'scores', 'make_scores.py'))
    make_scores = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_scores)
    files = sorted(glob.glob(os.path.join(ROOT, 'e2e', 'scores', '*.json')))
    assert [os.path.basename(path)[:-5] for path in files] == sorted(make_scores.CASES)
    for name, case in make_scores.cases().items():
        with open(os.path.join(ROOT, 'e2e', 'scores', f'{name}.json'), encoding='utf-8') as f:
            assert json.load(f) == case, f'{name}.json is stale: run python e2e/scores/make_scores.py'
