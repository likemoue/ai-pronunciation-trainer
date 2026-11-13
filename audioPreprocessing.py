"""Decode browser recordings into 16 kHz mono float audio with ffmpeg.

One ffmpeg call does the container parsing, down-mixing and resampling, with
hard limits on what it may read and how long it may run:

* only a few container formats are accepted (whatever MediaRecorder produces,
  plus WAV) and ffmpeg may not open other files or URLs;
* at most MAX_AUDIO_SECONDS (+0.5 s to detect longer input) are decoded, so a
  tiny upload that declares hours of audio cannot exhaust memory;
* the subprocess is killed after DECODE_TIMEOUT_SECONDS.
"""
import os
import shutil
import subprocess
import tempfile

import numpy as np
import torch


class AudioDecodeError(ValueError):
    """The upload is not audio we can read."""


class AudioTooLongError(ValueError):
    """The recording is longer than MAX_AUDIO_SECONDS."""


MAX_AUDIO_SECONDS = float(os.environ.get('MAX_AUDIO_SECONDS', '35'))
DECODE_TIMEOUT_SECONDS = float(os.environ.get('AUDIO_DECODE_TIMEOUT', '20'))
# Demuxers for webm/Matroska (Chrome, Firefox), Ogg (Firefox), MP4 (Safari) and WAV.
_FORMAT_WHITELIST = 'matroska,webm,ogg,mov,mp4,m4a,wav'


def _ffmpeg_binary() -> str:
    return os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg') or 'ffmpeg'


def _is_mp4(raw_bytes: bytes) -> bool:
    # ISO base media files start with a size field followed by 'ftyp'.
    return len(raw_bytes) >= 12 and raw_bytes[4:8] == b'ftyp'


def decode_audio(raw_bytes: bytes, target_rate: int = 16000) -> torch.Tensor:
    """Return the recording as a float32 tensor of shape [1, samples] at target_rate."""
    if not raw_bytes:
        raise AudioDecodeError('Empty recording.')

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
            '-protocol_whitelist', protocols,
            '-format_whitelist', _FORMAT_WHITELIST,
            '-i', source,
            '-map', '0:a:0', '-vn', '-sn', '-dn',
            '-t', f'{MAX_AUDIO_SECONDS + 0.5:.2f}',
            '-ac', '1', '-ar', str(target_rate),
            '-f', 'f32le', 'pipe:1',
        ]
        try:
            completed = subprocess.run(command, input=stdin_bytes, capture_output=True,
                                       timeout=DECODE_TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            raise AudioDecodeError('Decoding the recording took too long.')
        except OSError as e:
            raise RuntimeError(f'ffmpeg could not be started: {e}') from e
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if completed.returncode != 0:
        detail = completed.stderr.decode('utf-8', 'replace').strip()[-300:]
        raise AudioDecodeError(f'Could not decode the recording: {detail}')

    pcm = completed.stdout
    usable = len(pcm) - len(pcm) % 4
    samples = np.frombuffer(pcm[:usable], dtype=np.float32)
    if samples.size > int(MAX_AUDIO_SECONDS * target_rate):
        raise AudioTooLongError(f'Recordings are limited to {MAX_AUDIO_SECONDS:g} seconds.')
    if samples.size == 0:
        raise AudioDecodeError('The recording contains no audio.')

    return torch.from_numpy(samples.copy()).unsqueeze(0)
