import time

import pytest

import audioPreprocessing
from conftest import make_audio, requires_ffmpeg

pytestmark = requires_ffmpeg


@pytest.mark.parametrize('fmt', ['webm', 'ogg', 'mp4', 'wav'])
def test_browser_formats_decode_to_16k_mono(fmt):
    signal = audioPreprocessing.decode_audio(make_audio(fmt, seconds=1.0, rate=48000))
    assert signal.dim() == 2 and signal.shape[0] == 1
    assert str(signal.dtype) == 'torch.float32'
    assert abs(signal.shape[1] - 16000) < 1600  # codec padding varies a little
    assert float(signal.abs().max()) > 0.1


def test_stereo_44k_is_downmixed_and_resampled():
    signal = audioPreprocessing.decode_audio(make_audio('wav', seconds=2.0, rate=44100, channels=2))
    assert signal.shape[0] == 1
    assert abs(signal.shape[1] - 32000) < 10


@pytest.mark.parametrize('rate', [16001, 44099, 96001])
def test_odd_sample_rates_decode_quickly(rate):
    from test_api import odd_rate_wav
    start = time.perf_counter()
    signal = audioPreprocessing.decode_audio(odd_rate_wav(rate=rate, seconds=2.0))
    assert time.perf_counter() - start < 3
    assert abs(signal.shape[1] - 32000) < 50


def test_too_long_recording_raises():
    with pytest.raises(audioPreprocessing.AudioTooLongError):
        audioPreprocessing.decode_audio(make_audio('ogg', seconds=40))


def test_thirty_seconds_is_accepted():
    signal = audioPreprocessing.decode_audio(make_audio('webm', seconds=30))
    assert signal.shape[1] >= 29 * 16000


@pytest.mark.parametrize('payload', [b'', b'garbage', b'\x00' * 4096])
def test_garbage_raises_decode_error(payload):
    with pytest.raises(audioPreprocessing.AudioDecodeError):
        audioPreprocessing.decode_audio(payload)
