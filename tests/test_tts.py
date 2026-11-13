import base64
import io
import wave

import pytest

import piperTTS


class FakeVoice:
    """Writes one frame of silence per character instead of running the ONNX model."""

    def synthesize_wav(self, text, wav_file, set_wav_format=True):
        if set_wav_format:
            wav_file.setframerate(22050)
            wav_file.setsampwidth(2)
            wav_file.setnchannels(1)
        wav_file.writeframes(b'\x00\x00' * len(text) * 100)


@pytest.fixture
def fake_voice(monkeypatch):
    monkeypatch.setattr(piperTTS, '_load_model', lambda language: FakeVoice())
    monkeypatch.setattr(piperTTS, '_cache', piperTTS.OrderedDict())
    monkeypatch.setattr(piperTTS, '_cache_bytes', 0)


def test_split_keeps_words_whole_and_pieces_short():
    text = ('This is a fairly long sentence without much punctuation that keeps going on and on '
            'until it is clearly longer than the limit, and then it continues a little more. Short one!')
    pieces = piperTTS.split_for_synthesis(text, max_chars=60)
    assert all(len(piece) <= 60 for piece in pieces)
    assert ' '.join(pieces).split() == text.split()


def test_generated_wav_contains_every_piece(fake_voice):
    text = 'word ' * 50
    wav_bytes = base64.b64decode(piperTTS.generate_wav_base64(text.strip()))
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getnframes() == sum(len(p) for p in piperTTS.split_for_synthesis(text.strip())) * 100


def test_cache_is_bounded_by_bytes(fake_voice, monkeypatch):
    monkeypatch.setattr(piperTTS, '_CACHE_MAX_BYTES', 200_000)
    for i in range(100):
        piperTTS.generate_wav_base64(f'sentence number {i} ' + 'x' * 100)
    assert piperTTS._cache_bytes <= 200_000
    assert piperTTS._cache_bytes == sum(len(v) for v in piperTTS._cache.values())
