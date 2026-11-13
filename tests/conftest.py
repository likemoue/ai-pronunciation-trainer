import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # the sentence databases are opened with relative paths
os.environ['PRELOAD_LANGUAGES'] = ''  # no background model warm-up during tests
os.environ.setdefault('ENABLED_LANGUAGES', 'en')
os.environ.setdefault('READY_DIR', os.path.join(tempfile.gettempdir(), 'aipt-test-ready'))


def ffmpeg_binary():
    return os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg')


requires_ffmpeg = pytest.mark.skipif(not ffmpeg_binary(), reason='ffmpeg is not installed')

_CODECS = {
    'webm': ['-c:a', 'libopus', '-f', 'webm'],
    'ogg': ['-c:a', 'libopus', '-f', 'ogg'],
    'mp4': ['-c:a', 'aac', '-f', 'mp4'],
    'wav': ['-c:a', 'pcm_s16le', '-f', 'wav'],
    'flac': ['-c:a', 'flac', '-f', 'flac'],
    # Matroska is a whitelisted container, but browsers never record FLAC in it.
    'mkv_flac': ['-c:a', 'flac', '-f', 'matroska'],
    # Chrome's audio/webm;codecs=pcm records 32-bit float PCM in Matroska.
    'mkv_pcm_f32': ['-c:a', 'pcm_f32le', '-f', 'matroska'],
    # No browser records Vorbis.
    'ogg_vorbis': ['-c:a', 'libvorbis', '-f', 'ogg'],
}


def make_audio(fmt: str, seconds: float = 1.0, rate: int = 48000, channels: int = 1,
               silent: bool = False, tracks: int = 1) -> bytes:
    """Generate a test recording with ffmpeg's built-in signal sources
    (tracks > 1: one audio track per tone, as no browser records)."""
    sources = []
    for track in range(tracks):
        sources += ['-f', 'lavfi', '-i',
                    f'anullsrc=r={rate}:cl={"stereo" if channels == 2 else "mono"}' if silent
                    else f'sine=frequency={440 + 220 * track}:sample_rate={rate}']
    maps = [arg for track in range(tracks) for arg in ('-map', str(track))] if tracks > 1 else []
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, f'audio.{fmt.split("_")[0]}')
        command = [ffmpeg_binary(), '-nostdin', '-loglevel', 'error', *sources, *maps,
                   '-t', str(seconds), '-ac', str(channels), '-ar', str(rate), *_CODECS[fmt], out]
        subprocess.run(command, check=True)
        with open(out, 'rb') as f:
            return f.read()


class FakeASR:
    """Stands in for Whisper: returns a fixed transcript with evenly spaced word timings."""

    def __init__(self, transcript='Hello world'):
        self.transcript = transcript
        self._word_locations = []

    def processAudio(self, audio):
        words = self.transcript.split()
        length = audio.shape[-1]
        step = max(1, length // max(1, len(words)))
        self._word_locations = [{'word': word, 'start_ts': i * step, 'end_ts': (i + 1) * step,
                                 'tag': 'processed'} for i, word in enumerate(words)]

    def getTranscript(self):
        return self.transcript

    def getWordLocations(self):
        return self._word_locations


@pytest.fixture
def fake_asr(monkeypatch):
    """Score with a fake ASR model instead of loading Whisper."""
    import lambdaSpeechToScore
    import pronunciationTrainer
    import RuleBasedModels
    asr = FakeASR()
    trainer = pronunciationTrainer.PronunciationTrainer(asr, RuleBasedModels.EngPhonemConverter())
    monkeypatch.setitem(lambdaSpeechToScore._trainer_cache, 'en', trainer)
    return asr


class FakeVoice:
    """Stands in for the Piper voice: phonemize() returns phonemes_per_char
    phonemes per character (dense_chars overrides that for some characters,
    the way espeak-ng reads emoji and digits as words), and synthesis writes
    100 frames of silence per character, instead of running espeak-ng and the
    ONNX model."""

    phonemes_per_char = 1

    def __init__(self):
        self.synthesized = []
        self.dense_chars = {}

    def phonemize(self, text):
        return [[ch for ch in text if not ch.isspace()
                 for _ in range(self.dense_chars.get(ch, self.phonemes_per_char))]]

    def synthesize_wav(self, text, wav_file, set_wav_format=True):
        self.synthesized.append(text)
        if set_wav_format:
            wav_file.setframerate(22050)
            wav_file.setsampwidth(2)
            wav_file.setnchannels(1)
        wav_file.writeframes(bytes(2) * len(text) * 100)


@pytest.fixture
def fake_voice(monkeypatch):
    """Synthesise with FakeVoice instead of loading Piper."""
    import piperTTS
    voice = FakeVoice()
    monkeypatch.setattr(piperTTS, '_load_model', lambda language: voice)
    monkeypatch.setattr(piperTTS, 'is_available', lambda: True)
    monkeypatch.setattr(piperTTS, '_cache', piperTTS.OrderedDict())
    monkeypatch.setattr(piperTTS, '_cache_bytes', 0)
    return voice


@pytest.fixture
def client():
    import webApp
    webApp.app.config['TESTING'] = True
    return webApp.app.test_client()
