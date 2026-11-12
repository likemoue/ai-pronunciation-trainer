import platform
import hashlib
import base64
import io
import os
import wave
import urllib.request

_models = {}
_cache = {}

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models', 'piper')

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


def _download_model(language):
    config = VOICE_CONFIGS[language]
    os.makedirs(MODEL_DIR, exist_ok=True)

    filename = config['filename']
    for url, fname in [(config['model_url'], filename), (config['config_url'], f'{filename}.json')]:
        dest = os.path.join(MODEL_DIR, fname)
        if os.path.exists(dest):
            continue
        print(f'Downloading Piper model ({language}): {fname} ...')
        urllib.request.urlretrieve(url, dest)
        print(f'Downloaded {fname} ({os.path.getsize(dest)} bytes)')


def _load_model(language):
    if language not in _models:
        _download_model(language)
        from piper import PiperVoice
        filename = VOICE_CONFIGS[language]['filename']
        model_path = os.path.join(MODEL_DIR, filename)
        _models[language] = PiperVoice.load(model_path)
    return _models[language]


def generate_wav_base64(text, language='en'):
    key = f'{language}:{hashlib.md5(text.encode()).hexdigest()}'
    if key in _cache:
        return _cache[key]

    model = _load_model(language)
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        model.synthesize_wav(text, wav_file)
    wav_buffer.seek(0)
    audio_bytes = wav_buffer.read()
    result = base64.b64encode(audio_bytes).decode('utf-8')
    _cache[key] = result
    return result


def is_linux():
    return platform.system() == 'Linux'
