import base64
import hashlib
import io
import os
import platform
import threading
import urllib.request
import wave
from collections import OrderedDict

_models = {}
_cache = OrderedDict()
_CACHE_MAX_ITEMS = int(os.environ.get('PIPER_CACHE_SIZE', '256'))
_lock = threading.Lock()

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'piper')

VOICE_CONFIGS = {
    'de': {
        'filename': 'de_DE-thorsten-low.onnx',
        'model_url': (
            'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/'
            'de/de_DE/thorsten/low/de_DE-thorsten-low.onnx?download=true'
        ),
        'config_url': (
            'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/'
            'de/de_DE/thorsten/low/de_DE-thorsten-low.onnx.json?download=true'
        ),
    },
    'en': {
        'filename': 'en_GB-northern_english_male-medium.onnx',
        'model_url': (
            'https://huggingface.co/rhasspy/piper-voices/resolve/main/'
            'en/en_GB/northern_english_male/medium/'
            'en_GB-northern_english_male-medium.onnx?download=true'
        ),
        'config_url': (
            'https://huggingface.co/rhasspy/piper-voices/resolve/main/'
            'en/en_GB/northern_english_male/medium/'
            'en_GB-northern_english_male-medium.onnx.json?download=true'
        ),
    },
}


def is_available() -> bool:
    """True when the piper-tts package can be imported on this host."""
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def _download_model(language):
    config = VOICE_CONFIGS[language]
    os.makedirs(MODEL_DIR, exist_ok=True)

    filename = config['filename']
    for url, fname in [(config['model_url'], filename), (config['config_url'], f'{filename}.json')]:
        dest = os.path.join(MODEL_DIR, fname)
        if os.path.exists(dest):
            continue
        print(f'Downloading Piper model ({language}): {fname} ...')
        # Download to a temporary name first so an interrupted download
        # never leaves a truncated model that looks complete on the next run.
        partial = dest + '.part'
        urllib.request.urlretrieve(url, partial)
        os.replace(partial, dest)
        print(f'Downloaded {fname} ({os.path.getsize(dest)} bytes)')


def _load_model(language):
    if language not in VOICE_CONFIGS:
        raise ValueError(f'No Piper voice configured for language "{language}"')
    with _lock:
        if language not in _models:
            _download_model(language)
            from piper import PiperVoice
            filename = VOICE_CONFIGS[language]['filename']
            model_path = os.path.join(MODEL_DIR, filename)
            _models[language] = PiperVoice.load(model_path)
        return _models[language]


def generate_wav_base64(text, language='en'):
    key = f'{language}:{hashlib.md5(text.encode()).hexdigest()}'
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    model = _load_model(language)
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        model.synthesize_wav(text, wav_file)
    result = base64.b64encode(wav_buffer.getvalue()).decode('utf-8')

    # Bounded LRU: users can submit arbitrary text, so the cache must not grow forever.
    with _lock:
        _cache[key] = result
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX_ITEMS:
            _cache.popitem(last=False)
    return result


def is_linux():
    return platform.system() == 'Linux'
