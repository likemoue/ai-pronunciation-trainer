import base64
import hashlib
import io
import os
import platform
import re
import threading
import urllib.request
import wave
from collections import OrderedDict

_models = {}
_cache = OrderedDict()
_cache_bytes = 0
# The cache is bounded by size, not by item count: one long text is ~1 MB of base64 WAV.
_CACHE_MAX_BYTES = int(os.environ.get('PIPER_CACHE_MAX_MB', '64')) * 1024 * 1024
# ONNX Runtime ignores OMP_NUM_THREADS and by default starts one thread per core,
# which competes with Whisper in the other worker. A short sentence needs 1-2.
_PIPER_THREADS = int(os.environ.get('PIPER_THREADS', '2'))
# Long sentences are synthesised in pieces so one request cannot hold a large
# inference buffer.
_MAX_PIECE_CHARS = 120
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
    # American voice: the reference IPA comes from eng_to_ipa (CMU dictionary),
    # which is American English, so the model voice should match it.
    'en': {
        'filename': 'en_US-lessac-medium.onnx',
        'model_url': (
            'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/'
            'en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true'
        ),
        'config_url': (
            'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/'
            'en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true'
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


def _session_options():
    import onnxruntime
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = _PIPER_THREADS
    options.inter_op_num_threads = 1
    # Without the arena, memory used by one long synthesis is returned afterwards.
    options.enable_cpu_mem_arena = False
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    options.add_session_config_entry('session.inter_op.allow_spinning', '0')
    return options


def _load_model(language):
    if language not in VOICE_CONFIGS:
        raise ValueError(f'No Piper voice configured for language "{language}"')
    with _lock:
        if language not in _models:
            _download_model(language)
            import onnxruntime
            from piper import PiperVoice
            filename = VOICE_CONFIGS[language]['filename']
            model_path = os.path.join(MODEL_DIR, filename)
            voice = PiperVoice.load(model_path)
            # PiperVoice.load builds its session with default options; replace it
            # with one that uses a small, non-spinning thread pool.
            voice.session = onnxruntime.InferenceSession(
                model_path, sess_options=_session_options(), providers=['CPUExecutionProvider'])
            _models[language] = voice
        return _models[language]


def warm_up(language):
    """Download (if needed) and load the voice ahead of the first request."""
    _load_model(language)


def _has_wav_format(wav_file) -> bool:
    try:
        wav_file.getnchannels()
        return True
    except wave.Error:
        return False


def split_for_synthesis(text, max_chars=_MAX_PIECE_CHARS):
    """Split text into pieces of at most max_chars, preferring sentence and
    clause boundaries and never splitting inside a word."""
    pieces = []
    for sentence in re.split(r'(?<=[.!?;:])\s+', text.strip()):
        while len(sentence) > max_chars:
            cut = max(sentence.rfind(', ', 0, max_chars), sentence.rfind(' ', 0, max_chars))
            if cut <= 0:
                cut = max_chars
            pieces.append(sentence[:cut + 1].strip())
            sentence = sentence[cut + 1:].strip()
        if sentence:
            pieces.append(sentence)
    return pieces


def generate_wav_base64(text, language='en'):
    global _cache_bytes
    key = f'{language}:{hashlib.md5(text.encode()).hexdigest()}'
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    model = _load_model(language)
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        format_set = False
        for piece in split_for_synthesis(text):
            # The first piece that produces audio sets the WAV format; later
            # pieces append their frames to the same file.
            model.synthesize_wav(piece, wav_file, set_wav_format=not format_set)
            format_set = format_set or _has_wav_format(wav_file)
        if not format_set:
            raise ValueError('The text produced no audio.')
    result = base64.b64encode(wav_buffer.getvalue()).decode('utf-8')

    # Bounded LRU: users can submit arbitrary text, so the cache must not grow forever.
    with _lock:
        if key not in _cache:
            _cache[key] = result
            _cache_bytes += len(result)
        _cache.move_to_end(key)
        while _cache_bytes > _CACHE_MAX_BYTES and len(_cache) > 1:
            _, evicted = _cache.popitem(last=False)
            _cache_bytes -= len(evicted)
    return result


def is_linux():
    return platform.system() == 'Linux'
