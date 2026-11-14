"""Model files the app uses, pinned so that every build gets the same bytes.

The Docker build downloads them once, in a stage of their own that needs only
the Python standard library (scripts/download_models.py); on a development
machine they are downloaded on first use. Keep this module free of imports
outside the standard library: the Docker layer that holds the models is
rebuilt only when this file or the download script changes.
"""
import hashlib
import http.client
import os
import shutil
import time
import urllib.error
import urllib.request

# A download that receives nothing for this many seconds fails instead of
# hanging the Docker build, and deploy.sh with it (it holds its lock meanwhile).
DOWNLOAD_TIMEOUT = 60
# Tries per file. Network errors, truncated files and HTTP 408, 429 and 5xx are
# tried again after RETRY_DELAY seconds, then twice that; other errors are not.
DOWNLOAD_ATTEMPTS = 3
RETRY_DELAY = 10

# Whisper base at a fixed commit of https://huggingface.co/openai/whisper-base.
WHISPER_REPO = 'openai/whisper-base'
WHISPER_REVISION = 'e37978b90ca9030d5170a5c07aadb050351a65bb'
WHISPER_URL = 'https://huggingface.co/{repo}/resolve/{revision}/{file}'
# The files transformers loads, with their sha256 at that commit (the weights
# only as safetensors; the repository also has them as .bin, .h5 and .msgpack).
WHISPER_FILES = {
    'added_tokens.json': '9715fd2243b6f06a5858b5e32950d2853f73dd5bc201aafcf76f5082a2d8acd1',
    'config.json': 'a153c53883a6799b6f056b4a8d1a515c9926d03994682ba88a7616618d7da0c1',
    'generation_config.json': '444b3f636d2fff89dd9ecf549e2a085b61f7ff0fa0246d4628bac6a3b8cc9ba4',
    'merges.txt': '2df2990a395e35e8dfbc7511e08c12d56018d8d04691e0133e5d63b21e154dc6',
    'model.safetensors': '07cadb9f25677c8d50df603e66a98fbd842cce45047139baeb16e6219a1e807b',
    'normalizer.json': 'bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd',
    'preprocessor_config.json': '9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666',
    'special_tokens_map.json': 'e67ae3a0aaa99abcd9f187138e12db1f65c16a14761c50ef10eef2c174a7a691',
    'tokenizer.json': '27fc476bfe7f17299480be2273fc0608e4d5a99aba2ab5dec5374b4482d1a566',
    'tokenizer_config.json': '2a4c4281cf9f51ac6ccc406fdc711a087afe6530f671fa7b80953edc498275ce',
    'vocab.json': '8f680bba319e01a653d2e8a5dbc17a9157179e0576e6ce74ce0c06356c6e24f9',
}

PIPER_VOICE_URL = 'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{path}/{file}?download=true'
PIPER_VOICE_FILES = ('.onnx', '.onnx.json')

# Voices the app can use, with the sha256 of each file in rhasspy/piper-voices v1.0.0.
PIPER_VOICES = {
    # LJ Speech: one American speaker, recordings in the public domain.
    'en_US-ljspeech-medium': {
        'path': 'en/en_US/ljspeech/medium',
        'sha256': {'.onnx': '6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22',
                   '.onnx.json': '141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860'},
    },
    # Same speaker, slightly clearer, about five times slower to synthesise.
    'en_US-ljspeech-high': {
        'path': 'en/en_US/ljspeech/high',
        'sha256': {'.onnx': '5d4f08ba6a2a48c44592eed3ce56bf85e9de3dd4e20df90541ae68a8310c029a',
                   '.onnx.json': '7e1f4634af596d83cca997fb7a931ba80b70f8a316a2655ee69c55365e0ace14'},
    },
    # The previous English voice; its training data is licensed for research only.
    'en_US-lessac-medium': {
        'path': 'en/en_US/lessac/medium',
        'sha256': {'.onnx': '5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f',
                   '.onnx.json': 'efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0'},
    },
    # German is disabled in the English edition; its files are not pinned.
    'de_DE-thorsten-low': {'path': 'de/de_DE/thorsten/low', 'sha256': None},
}

# The English voice the app uses unless PIPER_VOICE_EN names another one.
DEFAULT_ENGLISH_VOICE = 'en_US-ljspeech-medium'


def sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _download(url, path):
    """Write the body of url to path. Fails when the connection stalls for
    DOWNLOAD_TIMEOUT seconds or closes before the whole body has arrived."""
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response, open(path, 'wb') as f:
        shutil.copyfileobj(response, f, 1 << 20)
        length = response.headers.get('Content-Length')
        if length is not None and f.tell() != int(length):
            raise ConnectionError(f'the connection closed after {f.tell()} of {length} bytes')


def _worth_retrying(error) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (408, 429) or error.code >= 500
    return True  # timeouts, resets, DNS failures, truncated files


def fetch(url, dest, expected=None) -> bool:
    """Download url to dest unless dest is there; check it against its sha256.
    Returns True when it downloaded the file."""
    if os.path.exists(dest):
        if expected and sha256(dest) != expected:
            raise RuntimeError(f'{dest} does not match its pinned sha256; delete it to download it again.')
        return False
    # Download to a temporary name first so an interrupted download never
    # leaves a truncated file that looks complete on the next run.
    name = os.path.basename(dest)
    partial = dest + '.part'
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            _download(url, partial)
            break
        except (OSError, http.client.HTTPException) as error:
            if attempt == DOWNLOAD_ATTEMPTS or not _worth_retrying(error):
                if os.path.exists(partial):
                    os.remove(partial)
                tries = 'once' if attempt == 1 else f'{attempt} times'
                raise RuntimeError(f'Could not download {url} (tried {tries}): {error}') from error
            time.sleep(RETRY_DELAY * 2 ** (attempt - 1))
    if expected and sha256(partial) != expected:
        os.remove(partial)
        raise RuntimeError(f'The downloaded {name} does not match its pinned sha256.')
    os.replace(partial, dest)
    return True


def download_whisper(directory) -> list:
    """The pinned Whisper files in `directory`, each checked against its sha256.
    Returns the names of the files it downloaded."""
    os.makedirs(directory, exist_ok=True)
    return [name for name, expected in WHISPER_FILES.items()
            if fetch(WHISPER_URL.format(repo=WHISPER_REPO, revision=WHISPER_REVISION, file=name),
                     os.path.join(directory, name), expected)]


def download_piper_voice(voice, directory, spec=None) -> list:
    """Make sure the files of a Piper voice are in `directory` and match their
    pinned sha256. Returns the names of the files it downloaded."""
    spec = spec or PIPER_VOICES[voice]
    os.makedirs(directory, exist_ok=True)
    downloaded = []
    for suffix in PIPER_VOICE_FILES:
        name = voice + suffix
        url = PIPER_VOICE_URL.format(path=spec['path'], file=name)
        if fetch(url, os.path.join(directory, name), (spec['sha256'] or {}).get(suffix)):
            downloaded.append(name)
    return downloaded
