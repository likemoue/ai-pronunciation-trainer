"""The build stays reproducible: dependencies declared and locked, models,
images and actions pinned, and the Docker context holding what the app reads."""
import ast
import glob
import os
import re
import subprocess
import sys

import pytest

import model_pins

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Top-level modules the app imports -> the requirement in requirements.in that provides them.
THIRD_PARTY = {
    'flask': 'flask', 'werkzeug': 'flask', 'gunicorn': 'gunicorn', 'numpy': 'numpy', 'pandas': 'pandas',
    'torch': 'torch', 'transformers': 'transformers', 'huggingface_hub': 'huggingface-hub',
    'piper': 'piper-tts', 'onnxruntime': 'onnxruntime', 'eng_to_ipa': 'eng-to-ipa', 'dtwalign': 'dtwalign',
}
# Imported only when German is enabled, which the English image does not install.
OPTIONAL = {'epitran'}


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
    assert requirement_names(read('requirements.in')) <= used


@pytest.mark.parametrize('lock', ['requirements.lock', 'requirements-dev.lock'])
def test_lock_pins_every_package_with_hashes(lock):
    text = read(lock)
    entries = re.findall(r'^([A-Za-z0-9_.-]+)==(\S+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)', text, re.M)
    pinned = {name.lower().replace('_', '-') for name, _, _ in entries}
    assert pinned and len(pinned) == len(re.findall(r'^[A-Za-z0-9_.-]+==', text, re.M))
    if lock == 'requirements.lock':
        assert requirement_names(read('requirements.in')) <= pinned
        assert re.search(r'^torch==[0-9.]+\+cpu ', text, re.M), 'torch must be the CPU build'
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


def test_docker_context_lets_in_what_the_app_reads():
    allowed = {line.strip() for line in read('.dockerignore').splitlines()}
    assert '*' in allowed
    for entry in ('!*.py', '!requirements.lock', '!scripts/download_models.py', '!databases/data_en.csv',
                  '!static/', '!templates/'):
        assert entry in allowed, entry
    # Every module the app imports sits at the top level, where `!*.py` lets it in.
    assert not glob.glob(os.path.join(ROOT, '*', '__init__.py'))


def test_dockerfile_installs_the_lock_with_hashes_and_both_indexes():
    dockerfile = read('Dockerfile')
    assert '--require-hashes -r /tmp/requirements.lock' in dockerfile
    assert '--extra-index-url https://download.pytorch.org/whl/cpu' in dockerfile
    assert 'WARMUP_STRICT=1' in dockerfile


def test_smoke_test_takes_a_user_agent_for_the_canary():
    result = subprocess.run([sys.executable, os.path.join(ROOT, 'deploy', 'smoke_test.py'), '--help'],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and '--user-agent' in result.stdout
    assert '--user-agent' in read('.github/workflows/canary.yml')


def test_shell_scripts_keep_lf_line_endings():
    assert '*.sh text eol=lf' in read('.gitattributes')
