import os
import subprocess
import sys
import threading
import time

import pytest

import audioPreprocessing
import resource_probe
from conftest import make_audio, requires_ffmpeg
from crafted_media import (mp4_declaring_samples, opus_webm, opus_webm_with_extra_tracks, pcm_mkv,
                           pcm_mkv_one_block)

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


def test_codecs_browsers_do_not_record_are_rejected():
    with pytest.raises(audioPreprocessing.AudioDecodeError):
        audioPreprocessing.decode_audio(make_audio('mkv_flac', seconds=1.0))


def test_vorbis_is_rejected():
    # A small Vorbis header can make the decoder allocate hundreds of MB.
    try:
        vorbis = make_audio('ogg_vorbis', seconds=1.0)
    except subprocess.CalledProcessError:
        pytest.skip('this ffmpeg has no libvorbis encoder')
    with pytest.raises(audioPreprocessing.AudioDecodeError):
        audioPreprocessing.decode_audio(vorbis)


def test_float_pcm_in_matroska_is_accepted():
    # Chrome's audio/webm;codecs=pcm.
    signal = audioPreprocessing.decode_audio(make_audio('mkv_pcm_f32', seconds=1.0))
    assert abs(signal.shape[1] - 16000) < 50


# ------------------------------------------------------------------ hostile files
# Each file is a few KB to a few hundred KB. Before the decoder capped its
# output by size and ffmpeg's allocations, they produced or reserved gigabytes.

@pytest.mark.parametrize('name,payload', [
    # WebM/Opus as Chrome records it: 20,000 x 120 ms = 40 min, 1 us apart.
    ('opus, 1 us timestamps', lambda: opus_webm(20000)),
    # Every block at timestamp 0.
    ('opus, all at timestamp 0', lambda: opus_webm(20000, microsecond_timestamps=False)),
    # PCM at 1 Hz: every sample becomes a second of output at 16 kHz.
    ('pcm 1 Hz, 1 us timestamps', lambda: pcm_mkv(3000, rate=1)),
])
def test_crafted_timestamps_cannot_bypass_the_length_limit(name, payload):
    data = payload()
    assert len(data) < 200_000
    start = time.perf_counter()
    with pytest.raises(audioPreprocessing.AudioTooLongError):
        audioPreprocessing.decode_audio(data)
    assert time.perf_counter() - start < 5, name


def test_honest_long_pcm_is_still_reported_as_too_long():
    # 100 blocks of 1 s each at 1 Hz with real timestamps: plainly 100 s long.
    with pytest.raises(audioPreprocessing.AudioTooLongError):
        audioPreprocessing.decode_audio(pcm_mkv(100, rate=1, timestamp_scale_ns=1_000_000, ts_step=1000))


def test_output_is_capped_by_size_even_if_the_decoder_keeps_writing(monkeypatch, tmp_path):
    # Stand-in for ffmpeg that ignores every limit: 200 MB of output, then a
    # marker file. The decoder must stop it long before it gets there.
    finished = tmp_path / 'finished'
    script = '\n'.join([
        'import pathlib, sys',
        'chunk = bytes(1 << 20)',
        'for _ in range(200):',
        '    sys.stdout.buffer.write(chunk)',
        'sys.stdout.flush()',
        f'pathlib.Path({str(finished)!r}).write_text("done")',
    ])
    real_popen = subprocess.Popen
    monkeypatch.setattr(subprocess, 'Popen',
                        lambda command, **kwargs: real_popen([sys.executable, '-c', script], **kwargs))
    start = time.perf_counter()
    with pytest.raises(audioPreprocessing.AudioTooLongError):
        audioPreprocessing.decode_audio(b'any upload')
    assert time.perf_counter() - start < 5
    time.sleep(0.5)
    assert not finished.exists()


def test_declared_sample_table_cannot_reserve_gigabytes():
    bomb = mp4_declaring_samples(make_audio('mp4', seconds=0.5), 40_000_000)
    assert len(bomb) < 50_000
    with resource_probe.child_peak_rss() as peak:
        with pytest.raises(audioPreprocessing.AudioDecodeError):
            audioPreprocessing.decode_audio(bomb)
    peak.assert_below(300 * 1024 * 1024)


def test_extra_streams_cannot_multiply_the_decoder_memory():
    # 16 extra Opus tracks of 255 channels: about 0.9 GB if every stream is
    # probed, although no single allocation is near -max_alloc.
    bomb = opus_webm_with_extra_tracks(16)
    assert len(bomb) < 20_000
    start = time.perf_counter()
    with resource_probe.child_peak_rss() as peak:
        with pytest.raises(audioPreprocessing.AudioDecodeError, match='more than one stream'):
            audioPreprocessing.decode_audio(bomb)
    assert time.perf_counter() - start < 3
    peak.assert_below(300 * 1024 * 1024)


@pytest.mark.parametrize('fmt', ['webm', 'ogg', 'mp4', 'mkv_pcm_f32'])
def test_recordings_with_two_audio_tracks_are_refused(fmt):
    # Browsers record one track. With two, ffmpeg stops at -max_streams: Ogg
    # and MP4 fail, and Matroska exits 0 with a few garbled samples.
    with pytest.raises(audioPreprocessing.AudioDecodeError, match='more than one stream'):
        audioPreprocessing.decode_audio(make_audio(fmt, seconds=2.0, tracks=2))


@pytest.mark.parametrize('rate', [100_000_001, 250_000_001])
def test_declared_sample_rate_cannot_build_a_huge_resampler(rate):
    start = time.perf_counter()
    with resource_probe.child_peak_rss() as peak:
        with pytest.raises(audioPreprocessing.AudioDecodeError):
            audioPreprocessing.decode_audio(pcm_mkv_one_block(rate))
    assert time.perf_counter() - start < 3
    peak.assert_below(300 * 1024 * 1024)


def _fake_ffmpeg(monkeypatch, script):
    """Replace ffmpeg with a Python script; return the list of processes started."""
    real_popen = subprocess.Popen
    procs = []

    def fake_popen(command, **kwargs):
        proc = real_popen([sys.executable, '-c', script], **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    return procs


def _decode_with_watchdog(limit_seconds):
    """Run decode_audio in a thread, so a decoder that never returns fails the
    test instead of hanging the suite."""
    result = {}

    def run():
        try:
            result['value'] = audioPreprocessing.decode_audio(b'any upload')
        except Exception as e:  # noqa: BLE001 - the test inspects it
            result['error'] = e

    thread = threading.Thread(target=run, daemon=True)
    start = time.perf_counter()
    thread.start()
    thread.join(limit_seconds)
    return thread, result, time.perf_counter() - start


def test_decoder_that_hangs_is_killed_after_the_timeout(monkeypatch):
    procs = _fake_ffmpeg(monkeypatch, 'import time\nwhile True:\n    time.sleep(1)')
    monkeypatch.setattr(audioPreprocessing, 'DECODE_TIMEOUT_SECONDS', 1.0)
    thread, result, elapsed = _decode_with_watchdog(10)
    try:
        assert not thread.is_alive(), 'decode_audio did not return'
        error = result.get('error')
        assert isinstance(error, audioPreprocessing.AudioDecodeError) and 'too long' in str(error), result
        assert elapsed < 5
        assert procs[0].poll() is not None
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
        thread.join(5)


def test_decoder_that_fails_silently_is_reported_with_its_exit_status(monkeypatch):
    # For example ffmpeg killed by the kernel when memory runs out: no stderr.
    _fake_ffmpeg(monkeypatch, 'import sys\nsys.exit(3)')
    with pytest.raises(audioPreprocessing.AudioDecodeError, match='exit status 3'):
        audioPreprocessing.decode_audio(b'any upload')


def test_default_decode_timeout_is_five_seconds():
    # A 35 s recording decodes in about 0.3 s; a longer limit lets one upload
    # hold a worker for longer.
    if 'AUDIO_DECODE_TIMEOUT' in os.environ:
        pytest.skip('AUDIO_DECODE_TIMEOUT is set in this environment')
    assert audioPreprocessing.DECODE_TIMEOUT_SECONDS == 5


@pytest.mark.parametrize('helper', ['drain_stderr', 'feed_stdin'])
def test_ffmpeg_is_stopped_when_a_helper_thread_cannot_start(monkeypatch, helper):
    procs = _fake_ffmpeg(monkeypatch, 'import time\nwhile True:\n    time.sleep(1)')
    real_start = threading.Thread.start

    def start(thread):
        target = getattr(thread, '_target', None)
        if target is not None and target.__name__ == helper:
            raise RuntimeError("can't start new thread")
        return real_start(thread)

    monkeypatch.setattr(threading.Thread, 'start', start)
    try:
        with pytest.raises(RuntimeError, match="can't start new thread"):
            audioPreprocessing.decode_audio(b'any upload')
        proc = procs[0]
        assert proc.poll() is not None, 'ffmpeg is still running'
        assert proc.stdin.closed and proc.stdout.closed
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()


def test_decoder_that_writes_a_lot_to_stderr_does_not_block(monkeypatch):
    # More than the 64 KB a pipe holds: without a reader, ffmpeg would block on
    # stderr before it writes its output.
    script = '\n'.join([
        'import sys',
        'for i in range(5000):',
        '    sys.stderr.write("warning %05d: " % i + "x" * 80 + "\\n")',
        'sys.stderr.flush()',
        'sys.stdout.buffer.write(bytes(16000 * 4))',
    ])
    procs = _fake_ffmpeg(monkeypatch, script)
    monkeypatch.setattr(audioPreprocessing, 'DECODE_TIMEOUT_SECONDS', 3.0)
    thread, result, elapsed = _decode_with_watchdog(15)
    try:
        assert not thread.is_alive(), 'decode_audio did not return'
        assert 'error' not in result, result
        assert result['value'].shape[1] == 16000
        assert elapsed < 2.5
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
        thread.join(5)


def test_recording_at_the_limit_is_accepted_and_just_over_it_is_not(monkeypatch):
    monkeypatch.setattr(audioPreprocessing, 'MAX_AUDIO_SECONDS', 1.0)
    signal = audioPreprocessing.decode_audio(make_audio('wav', seconds=0.9))
    assert abs(signal.shape[1] - 14400) < 50
    with pytest.raises(audioPreprocessing.AudioTooLongError):
        audioPreprocessing.decode_audio(make_audio('wav', seconds=1.2))
    with pytest.raises(audioPreprocessing.AudioTooLongError):
        audioPreprocessing.decode_audio(make_audio('wav', seconds=2.0))
