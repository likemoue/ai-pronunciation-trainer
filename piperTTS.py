import base64
import hashlib
import io
import os
import platform
import re
import sys
import tempfile
import threading
import wave
from collections import OrderedDict

import logging_setup
import model_pins

# ONNX Runtime (onnxruntime, imported on first use below) uploads usage events
# to Microsoft on Linux unless ORT_DISABLE_TELEMETRY is set when it is first
# imported; onnxruntime.disable_telemetry_events() does not stop that. The
# Dockerfile sets it too; this covers runs outside the image.
os.environ.setdefault('ORT_DISABLE_TELEMETRY', '1')

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
# warm-up thread or another gthread thread can synthesise while a request does.
_synth_lock = threading.Lock()
# Texts this worker is synthesising or waiting to synthesise. Each holds a
# gunicorn thread, so more than this are turned away with BusyError (the
# browser then reads the text with its own voice) rather than queued.
_SYNTH_QUEUE_LIMIT = int(os.environ.get('PIPER_QUEUE_LIMIT', '2'))
_synth_pending = 0
logger = logging_setup.get_logger(__name__)
_onnxruntime = None
_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')


def import_onnxruntime():
    """onnxruntime, imported with its start-up messages logged as JSON lines.

    ONNX Runtime looks for GPUs as soon as it is imported, and its own logger
    writes to stderr directly. On a virtual machine whose display is not a PCI
    device (Hyper-V's, as on GitHub's runners) it warns in plain text, which
    would break the log's one JSON object per line. So the first import runs
    with stderr pointed at a file, and what ONNX Runtime wrote there is logged
    here instead; later, it only reports errors. stderr belongs to the whole
    process, so that first import happens before other threads can log:
    webApp.start_warm_up calls is_available() first.
    """
    global _onnxruntime
    if _onnxruntime is None:
        if 'onnxruntime' not in sys.modules:
            sys.stderr.flush()
            saved = os.dup(2)
            with tempfile.TemporaryFile() as captured:
                os.dup2(captured.fileno(), 2)
                try:
                    import onnxruntime  # noqa: F401
                finally:
                    os.dup2(saved, 2)
                    os.close(saved)
                captured.seek(0)
                for line in captured.read().decode('utf-8', 'replace').splitlines():
                    line = _ANSI_ESCAPE.sub('', line).strip()
                    if line:
                        logger.warning('onnxruntime: %s', line)
        import onnxruntime
        onnxruntime.set_default_logger_severity(3)  # errors only
        _onnxruntime = onnxruntime
    return _onnxruntime


class TextTooLongError(ValueError):
    """The text would take far longer to say than its length suggests."""


class BusyError(RuntimeError):
    """This worker is already synthesising as many texts as it takes."""


# The Docker image keeps the voices in PIPER_MODEL_DIR (Dockerfile); a
# development checkout downloads them to models/piper on first use.
MODEL_DIR = os.environ.get('PIPER_MODEL_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'models', 'piper')
_VOICE_FILES = model_pins.PIPER_VOICE_FILES
VOICES = model_pins.PIPER_VOICES

_DEFAULT_VOICES = {
    # American English, to match the reference IPA from the CMU dictionary (eng_to_ipa).
    'en': model_pins.DEFAULT_ENGLISH_VOICE,
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
        import_onnxruntime()  # before piper imports it, see import_onnxruntime
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def _download_model(language):
    """Make sure the voice files are in MODEL_DIR and match their pinned sha256."""
    voice = VOICE_CONFIGS[language]
    for name in model_pins.download_piper_voice(voice, MODEL_DIR, VOICES[voice]):
        logger.info('Downloaded Piper voice file %s for %s', name, language)


def _session_options():
    onnxruntime = import_onnxruntime()
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
            onnxruntime = import_onnxruntime()
            from piper import PiperVoice
            # On Windows, ONNX Runtime writes its usage events to ETW instead and
            # ignores ORT_DISABLE_TELEMETRY; this call turns those events off.
            onnxruntime.disable_telemetry_events()
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


def _cached(key):
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def _remember(key, value):
    """Bounded LRU: users can submit arbitrary text, so the cache must not grow forever."""
    global _cache_bytes
    with _lock:
        if key not in _cache:
            _cache[key] = value
            _cache_bytes += len(value)
        _cache.move_to_end(key)
        while _cache_bytes > _CACHE_MAX_BYTES and len(_cache) > 1:
            _, evicted = _cache.popitem(last=False)
            _cache_bytes -= len(evicted)
    return value


def generate_wav_base64(text, language='en'):
    key = f'{language}:wav:{hashlib.md5(text.encode()).hexdigest()}'
    cached = _cached(key)
    if cached is not None:
        return cached
    return _remember(key, base64.b64encode(_synthesize_limited(text, language)).decode('utf-8'))


def generate_mp3(text, language='en'):
    """The text read aloud as MP3, mono at MP3_BITRATE: about a tenth of the
    size of the WAV (served to browsers for bank sentences, webApp.py)."""
    key = f'{language}:mp3:{hashlib.md5(text.encode()).hexdigest()}'
    cached = _cached(key)
    if cached is not None:
        return cached
    return _remember(key, encode_mp3(_synthesize_limited(text, language)))


MP3_BITRATE = os.environ.get('PIPER_MP3_BITRATE', '48k')
# Encoding a few seconds of speech takes ffmpeg well under a second.
_MP3_TIMEOUT_SECONDS = 15


def encode_mp3(wav_bytes) -> bytes:
    import subprocess

    import audioPreprocessing
    command = [audioPreprocessing.ffmpeg_binary(), '-nostdin', '-hide_banner', '-loglevel', 'error',
               '-f', 'wav', '-i', 'pipe:0', '-ac', '1', '-codec:a', 'libmp3lame', '-b:a', MP3_BITRATE,
               '-f', 'mp3', 'pipe:1']
    try:
        result = subprocess.run(command, input=wav_bytes, capture_output=True, timeout=_MP3_TIMEOUT_SECONDS,
                                check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Encoding MP3 took too long.') from None
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode('utf-8', 'replace').strip()[-300:]
        raise RuntimeError(f'Could not encode MP3: {detail or result.returncode}')
    return result.stdout


def _synthesize_limited(text, language):
    """Synthesise unless this worker already has _SYNTH_QUEUE_LIMIT texts in
    hand (BusyError). Returns the WAV file's bytes."""
    global _synth_pending
    with _lock:
        if _synth_pending >= _SYNTH_QUEUE_LIMIT:
            raise BusyError(f'{_synth_pending} texts are being synthesised')
        _synth_pending += 1
    try:
        return _synthesize_wav(text, language)
    finally:
        with _lock:
            _synth_pending -= 1


def _synthesize_wav(text, language):
    model = _load_model(language)
    pieces = split_for_synthesis(text)
    wav_buffer = io.BytesIO()
    with _synth_lock:
        counts = [_phoneme_count(model, piece) for piece in pieces]
        if sum(counts) > _MAX_PHONEMES:
            raise TextTooLongError(f'{sum(counts)} phonemes (limit {_MAX_PHONEMES})')
        pieces = [part for piece, count in zip(pieces, counts, strict=True) for part in _split_dense_piece(model, piece, count)]
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
    return wav_buffer.getvalue()


def is_linux():
    return platform.system() == 'Linux'
