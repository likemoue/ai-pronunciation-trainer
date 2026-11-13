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
# Long texts are synthesised in pieces so one request cannot hold a large
# inference buffer.
_MAX_PIECE_CHARS = 120
# espeak-ng reads numbers, symbols and emoji as whole words, so the character
# limit alone does not bound how long the audio is: 300 characters of emoji
# take about 4,500 phonemes (over 4 minutes of speech). Practice sentences need
# at most about 260 phonemes, and number-heavy 300-character texts about 570.
_MAX_PHONEMES = int(os.environ.get('PIPER_MAX_PHONEMES', '900'))
# One inference holds about 16 MB per second of audio it produces, and 120
# characters of emoji or symbols are ~900 phonemes (~56 s, ~0.9 GB), so pieces
# with more phonemes than this are cut further. Practice sentences never are:
# no piece of a bank sentence comes near it.
_MAX_PIECE_PHONEMES = int(os.environ.get('PIPER_MAX_PIECE_PHONEMES', '300'))
# Pieces are not cut shorter than this. The densest characters (Braille
# patterns) read as about 44 phonemes each, so a piece this short has at most ~350.
_MIN_PIECE_CHARS = 8
_lock = threading.Lock()
# espeak-ng, which Piper uses to phonemise text, is not thread-safe, and the
# warm-up thread can synthesise while a request does.
_synth_lock = threading.Lock()


class TextTooLongError(ValueError):
    """The text would take far longer to say than its length suggests."""


MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'piper')
_VOICE_URL = 'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{path}/{file}?download=true'
_VOICE_FILES = ('.onnx', '.onnx.json')

# Voices the app can download, with the sha256 of each file in rhasspy/piper-voices v1.0.0.
VOICES = {
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

_DEFAULT_VOICES = {
    # American English, to match the reference IPA from the CMU dictionary (eng_to_ipa).
    'en': 'en_US-ljspeech-medium',
    'de': 'de_DE-thorsten-low',
}


def _configured_voices(environ) -> dict:
    """Voice per language: PIPER_VOICE_EN / PIPER_VOICE_DE, else the default.
    The Docker image only contains the voice it was built with."""
    voices = {}
    for language, default in _DEFAULT_VOICES.items():
        voice = environ.get(f'PIPER_VOICE_{language.upper()}') or default
        if voice not in VOICES:
            raise ValueError(f'Unknown Piper voice "{voice}" for "{language}"; known: {", ".join(VOICES)}')
        voices[language] = voice
    return voices


VOICE_CONFIGS = _configured_voices(os.environ)


def is_available() -> bool:
    """True when the piper-tts package can be imported on this host."""
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _download_model(language):
    """Make sure the voice files are in MODEL_DIR and match their pinned sha256."""
    voice = VOICE_CONFIGS[language]
    spec = VOICES[voice]
    os.makedirs(MODEL_DIR, exist_ok=True)
    for suffix in _VOICE_FILES:
        fname = voice + suffix
        dest = os.path.join(MODEL_DIR, fname)
        expected = (spec['sha256'] or {}).get(suffix)
        if os.path.exists(dest):
            if expected and _sha256(dest) != expected:
                raise RuntimeError(f'{dest} does not match its pinned sha256; delete it to download it again.')
            continue
        print(f'Downloading Piper voice ({language}): {fname} ...')
        # Download to a temporary name first so an interrupted download
        # never leaves a truncated model that looks complete on the next run.
        partial = dest + '.part'
        urllib.request.urlretrieve(_VOICE_URL.format(path=spec['path'], file=fname), partial)
        if expected and _sha256(partial) != expected:
            os.remove(partial)
            raise RuntimeError(f'The downloaded {fname} does not match its pinned sha256.')
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
            model_path = os.path.join(MODEL_DIR, VOICE_CONFIGS[language] + '.onnx')
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
    """Split text into pieces of at most max_chars for synthesis.

    A text that fits is synthesised in one piece, so its prosody is exactly
    what the voice produces for the whole sentence. Longer texts are split at
    sentence boundaries and the sentences are packed into pieces; a sentence
    that is still too long is cut at a comma or a space, never inside a word.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    pieces, current = [], ''
    for sentence in re.split(r'(?<=[.!?;:])\s+', text):
        while len(sentence) > max_chars:
            comma = sentence.rfind(', ', 0, max_chars)
            cut = comma + 1 if comma >= max_chars // 2 else sentence.rfind(' ', 0, max_chars + 1)
            if cut <= 0:
                cut = max_chars
            if current:
                pieces.append(current)
                current = ''
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) <= max_chars:
            current = f'{current} {sentence}'
        else:
            if current:
                pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def _phoneme_count(model, text):
    return sum(len(sentence) for sentence in model.phonemize(text))


def _split_dense_piece(model, piece, phonemes):
    """Cut a piece into parts of at most _MAX_PIECE_PHONEMES phonemes, or of
    _MIN_PIECE_CHARS characters. The first cut assumes even density; text
    whose density varies (emoji, then words) is measured again and cut
    further. Every cut makes the parts shorter, so this ends."""
    if phonemes <= _MAX_PIECE_PHONEMES or len(piece) <= _MIN_PIECE_CHARS:
        return [piece]
    max_chars = max(_MIN_PIECE_CHARS, len(piece) * _MAX_PIECE_PHONEMES // phonemes)
    return [smaller for part in split_for_synthesis(piece, max_chars) if part
            for smaller in _split_dense_piece(model, part, _phoneme_count(model, part))]


def generate_wav_base64(text, language='en'):
    global _cache_bytes
    key = f'{language}:{hashlib.md5(text.encode()).hexdigest()}'
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    model = _load_model(language)
    pieces = split_for_synthesis(text)
    wav_buffer = io.BytesIO()
    with _synth_lock:
        counts = [_phoneme_count(model, piece) for piece in pieces]
        if sum(counts) > _MAX_PHONEMES:
            raise TextTooLongError(f'{sum(counts)} phonemes (limit {_MAX_PHONEMES})')
        pieces = [part for piece, count in zip(pieces, counts) for part in _split_dense_piece(model, piece, count)]
        with wave.open(wav_buffer, 'wb') as wav_file:
            format_set = False
            for piece in pieces:
                # The first piece that produces audio sets the WAV format; later
                # pieces append their frames to the same file.
                model.synthesize_wav(piece, wav_file, set_wav_format=not format_set)
                format_set = format_set or _has_wav_format(wav_file)
            if not format_set:
                # Give the file a format so closing it does not hide this error.
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
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
