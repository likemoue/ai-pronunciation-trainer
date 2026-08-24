import platform
import hashlib
import base64
import io
import wave
from piper import PiperVoice

_model = None
_cache = {}

MODEL_PATH = 'models/piper/en_GB-northern_english_male-medium.onnx'


def _load_model():
    global _model
    if _model is None:
        _model = PiperVoice.load(MODEL_PATH)
    return _model


def generate_wav_base64(text):
    key = hashlib.md5(text.encode()).hexdigest()
    if key in _cache:
        return _cache[key]

    model = _load_model()
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
