"""Model files the app uses, pinned so that every build gets the same bytes.

The Docker build downloads them once, in a layer of their own
(scripts/download_models.py); on a development machine they are downloaded
on first use. Keep this module free of app imports: the Docker layer that
holds the models is rebuilt only when this file or the download script changes.
"""
import hashlib
import os
import urllib.request

# Whisper base at a fixed commit of https://huggingface.co/openai/whisper-base.
WHISPER_REPO = 'openai/whisper-base'
WHISPER_REVISION = 'e37978b90ca9030d5170a5c07aadb050351a65bb'
# The same weights in formats transformers does not load here.
WHISPER_IGNORE_PATTERNS = ['*.bin', '*.h5', '*.msgpack', '*.ot', '.gitattributes', 'README.md']

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


def download_piper_voice(voice, directory, spec=None) -> list:
    """Make sure the files of a Piper voice are in `directory` and match their
    pinned sha256. Returns the names of the files it downloaded."""
    spec = spec or PIPER_VOICES[voice]
    os.makedirs(directory, exist_ok=True)
    downloaded = []
    for suffix in PIPER_VOICE_FILES:
        name = voice + suffix
        dest = os.path.join(directory, name)
        expected = (spec['sha256'] or {}).get(suffix)
        if os.path.exists(dest):
            if expected and sha256(dest) != expected:
                raise RuntimeError(f'{dest} does not match its pinned sha256; delete it to download it again.')
            continue
        # Download to a temporary name first so an interrupted download
        # never leaves a truncated model that looks complete on the next run.
        partial = dest + '.part'
        urllib.request.urlretrieve(PIPER_VOICE_URL.format(path=spec['path'], file=name), partial)
        if expected and sha256(partial) != expected:
            os.remove(partial)
            raise RuntimeError(f'The downloaded {name} does not match its pinned sha256.')
        os.replace(partial, dest)
        downloaded.append(name)
    return downloaded
