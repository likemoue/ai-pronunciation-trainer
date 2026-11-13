"""Decode browser recordings into 16 kHz mono float audio with ffmpeg.

One ffmpeg call does the container parsing, down-mixing and resampling, with
hard limits on what it may read, allocate and produce:

* only a few container formats and codecs are accepted (whatever MediaRecorder
  produces, plus WAV), and ffmpeg may not open other files or URLs;
* a file with more than one stream is refused: ffmpeg opens a decoder for
  every stream while it probes a file, so extra streams would multiply its
  memory, and browsers record a single audio stream;
* no single allocation inside ffmpeg may exceed _MAX_ALLOC_BYTES, so values a
  file declares (sample tables, sample rates) cannot make it reserve gigabytes;
* the decoded audio is capped by size, not only by timestamps: `-t` trusts the
  timestamps in the upload, which can be crafted so it never fires, so at most
  MAX_AUDIO_SECONDS (+0.5 s to detect longer input) of samples are read before
  ffmpeg is stopped;
* the subprocess is killed after DECODE_TIMEOUT_SECONDS.
"""
import os
import shutil
import subprocess
import tempfile
import threading
from typing import NamedTuple

import numpy as np
import torch


class AudioDecodeError(ValueError):
    """The upload is not audio we can read."""


class AudioTooLongError(ValueError):
    """The recording is longer than MAX_AUDIO_SECONDS."""


MAX_AUDIO_SECONDS = float(os.environ.get('MAX_AUDIO_SECONDS', '35'))
# A 35 s recording decodes in about 0.3 s. Some valid but hostile files (Matroska
# with bzip2-compressed blocks) keep ffmpeg busy without output until this fires.
DECODE_TIMEOUT_SECONDS = float(os.environ.get('AUDIO_DECODE_TIMEOUT', '5'))
# Demuxers for webm/Matroska (Chrome, Firefox), Ogg (Firefox), MP4 (Safari) and WAV.
_FORMAT_WHITELIST = 'matroska,webm,ogg,mov,mp4,m4a,wav'
# Decoders for what browsers record: Opus (Chrome, Firefox, Edge), AAC (Safari)
# and PCM (WAV, and Chrome's audio/webm;codecs=pcm). Not Vorbis: no browser
# records it, and a 9 KB Vorbis header makes the decoder allocate about 600 MB
# in pieces that are each under _MAX_ALLOC_BYTES.
_CODEC_WHITELIST = 'opus,aac,pcm_s16le,pcm_f32le'
# Largest single allocation ffmpeg may make (demuxer indexes, resampler filters,
# frames). A 30 s recording needs a few MB.
_MAX_ALLOC_BYTES = 64 * 1024 * 1024
_STDERR_LINES = 20


def _ffmpeg_binary() -> str:
    return os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg') or 'ffmpeg'


def _is_mp4(raw_bytes: bytes) -> bool:
    # ISO base media files start with a size field followed by 'ftyp'.
    return len(raw_bytes) >= 12 and raw_bytes[4:8] == b'ftyp'


class _FfmpegResult(NamedTuple):
    returncode: int
    stdout: bytes
    stderr_tail: bytes
    timed_out: bool
    # ffmpeg hit -max_streams. Matroska then stops reading the track list part
    # way and may still exit 0 with a few samples, so the exit code is not enough.
    too_many_streams: bool


def _run_ffmpeg(command, stdin_bytes, max_output_bytes) -> _FfmpegResult:
    """Run ffmpeg with a time limit and a cap on how much of its output is read.

    At most max_output_bytes + 4 bytes of stdout are read; if ffmpeg produces
    more, it is killed and the returned stdout is longer than max_output_bytes.
    """
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise RuntimeError(f'ffmpeg could not be started: {e}') from e

    timed_out = threading.Event()
    too_many_streams = threading.Event()

    def kill_on_timeout():
        timed_out.set()
        proc.kill()

    stderr_tail = []

    def drain_stderr():
        # Keep only the last lines: a broken file can make ffmpeg log a lot.
        for line in proc.stderr:
            if b'max_streams' in line:
                too_many_streams.set()
            stderr_tail.append(line)
            del stderr_tail[:-_STDERR_LINES]

    def feed_stdin():
        try:
            proc.stdin.write(stdin_bytes)
        except OSError:  # ffmpeg stopped reading (finished, failed or killed)
            pass
        _close_quietly(proc.stdin)

    helpers = [threading.Thread(target=drain_stderr, daemon=True)]
    if stdin_bytes is not None:
        helpers.append(threading.Thread(target=feed_stdin, daemon=True))
    killer = threading.Timer(DECODE_TIMEOUT_SECONDS, kill_on_timeout)
    killer.daemon = True
    started = []
    stdout = b''
    # Every thread is started inside try, so ffmpeg is killed and reaped even if
    # starting one fails or is interrupted.
    try:
        killer.start()
        for helper in helpers:
            helper.start()
            started.append(helper)
        stdout = proc.stdout.read(max_output_bytes + 4)
        if len(stdout) <= max_output_bytes:
            proc.wait()
    finally:
        killer.cancel()  # also fine if it never started
        proc.kill()  # no-op if ffmpeg has already exited
        proc.wait()
        _close_quietly(proc.stdout)
        if stdin_bytes is not None and len(started) < len(helpers):
            _close_quietly(proc.stdin)  # the feeder never started, so nothing closed it
        for helper in started:
            helper.join(timeout=1)
        if not helpers[0].is_alive():
            _close_quietly(proc.stderr)
    return _FfmpegResult(proc.returncode, stdout, b''.join(stderr_tail), timed_out.is_set(),
                         too_many_streams.is_set())


def _close_quietly(stream):
    try:
        stream.close()
    except (OSError, ValueError):
        pass


def decode_audio(raw_bytes: bytes, target_rate: int = 16000) -> torch.Tensor:
    """Return the recording as a float32 tensor of shape [1, samples] at target_rate."""
    if not raw_bytes:
        raise AudioDecodeError('Empty recording.')

    # f32le output: 4 bytes per sample.
    max_output_bytes = int((MAX_AUDIO_SECONDS + 0.5) * target_rate) * 4
    tmp_path = None
    try:
        if _is_mp4(raw_bytes):
            # MP4 may keep its index at the end of the file, which needs seeking,
            # so it is read from a temporary file instead of a pipe.
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = tmp.name
            source, protocols, stdin_bytes = tmp_path, 'file', None
        else:
            source, protocols, stdin_bytes = 'pipe:0', 'pipe', raw_bytes

        command = [
            _ffmpeg_binary(), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-max_alloc', str(_MAX_ALLOC_BYTES),
            # A recording has one audio stream. A 41 KB WebM with 128 Opus
            # tracks of 255 channels each took 6.6 GB without this.
            '-max_streams', '1',
            '-protocol_whitelist', protocols,
            '-format_whitelist', _FORMAT_WHITELIST,
            '-codec_whitelist', _CODEC_WHITELIST,
            '-i', source,
            '-map', '0:a:0', '-vn', '-sn', '-dn',
            '-t', f'{MAX_AUDIO_SECONDS + 0.5:.2f}',
            '-ac', '1', '-ar', str(target_rate),
            '-f', 'f32le', 'pipe:1',
        ]
        result = _run_ffmpeg(command, stdin_bytes, max_output_bytes)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    pcm = result.stdout
    if result.too_many_streams:
        raise AudioDecodeError('The recording has more than one stream.')
    if len(pcm) > max_output_bytes:
        raise AudioTooLongError(f'Recordings are limited to {MAX_AUDIO_SECONDS:g} seconds.')
    if result.returncode != 0:
        if result.timed_out:
            raise AudioDecodeError('Decoding the recording took too long.')
        detail = result.stderr_tail.decode('utf-8', 'replace').strip()[-300:]
        raise AudioDecodeError(f'Could not decode the recording: {detail or f"exit status {result.returncode}"}')

    usable = len(pcm) - len(pcm) % 4
    samples = np.frombuffer(pcm[:usable], dtype=np.float32)
    if samples.size > int(MAX_AUDIO_SECONDS * target_rate):
        raise AudioTooLongError(f'Recordings are limited to {MAX_AUDIO_SECONDS:g} seconds.')
    if samples.size == 0:
        raise AudioDecodeError('The recording contains no audio.')

    return torch.from_numpy(samples.copy()).unsqueeze(0)
