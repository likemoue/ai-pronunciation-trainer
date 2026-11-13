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
}


def make_audio(fmt: str, seconds: float = 1.0, rate: int = 48000, channels: int = 1,
               silent: bool = False) -> bytes:
    """Generate a test recording with ffmpeg's built-in signal sources."""
    source = (f'anullsrc=r={rate}:cl={"stereo" if channels == 2 else "mono"}' if silent
              else f'sine=frequency=440:sample_rate={rate}')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, f'audio.{fmt}')
        command = [ffmpeg_binary(), '-nostdin', '-loglevel', 'error', '-f', 'lavfi', '-i', source,
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


@pytest.fixture
def client():
    import webApp
    webApp.app.config['TESTING'] = True
    return webApp.app.test_client()
