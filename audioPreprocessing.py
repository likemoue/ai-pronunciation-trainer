import os
import tempfile
import numpy as np
import torch
import audioread

_resamplers = {}


def _get_resampler(source_rate, target_rate):
    key = (source_rate, target_rate)
    if key not in _resamplers:
        from torchaudio.transforms import Resample
        _resamplers[key] = Resample(orig_freq=source_rate, new_freq=target_rate)
    return _resamplers[key]


def decode_audio(raw_bytes, target_rate=16000):
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    tmp_name = tmp.name

    try:
        tmp.write(raw_bytes)
        tmp.flush()
        tmp.close()

        signal, source_rate = _audioread_load(tmp_name)
    finally:
        os.remove(tmp_name)

    signal = torch.Tensor(signal)

    if signal.dim() > 1:
        # Down-mix multi-channel recordings to mono.
        signal = signal.mean(dim=0)

    if source_rate != target_rate:
        signal = _get_resampler(source_rate, target_rate)(signal)

    return signal.unsqueeze(0)


def _audioread_load(path, offset=0.0, duration=None, dtype=np.float32):
    """Load an audio buffer using audioread.

    This loads one block at a time, and then concatenates the results.
    Adapted from Librosa (BSD-3).
    """
    y = []
    with audioread.audio_open(path) as input_file:
        sr_native = input_file.samplerate
        n_channels = input_file.channels

        s_start = int(np.round(sr_native * offset)) * n_channels

        if duration is None:
            s_end = np.inf
        else:
            s_end = s_start + \
                (int(np.round(sr_native * duration)) * n_channels)

        n = 0

        for frame in input_file:
            frame = _buf_to_float(frame, dtype=dtype)
            n_prev = n
            n = n + len(frame)

            if n < s_start:
                continue

            if s_end < n_prev:
                break

            if s_end < n:
                frame = frame[: s_end - n_prev]

            if n_prev <= s_start <= n:
                frame = frame[(s_start - n_prev):]

            y.append(frame)

    if y:
        y = np.concatenate(y)
        if n_channels > 1:
            y = y.reshape((-1, n_channels)).T
    else:
        y = np.empty(0, dtype=dtype)

    return y, sr_native


def _buf_to_float(x, n_bytes=2, dtype=np.float32):
    """Convert an integer buffer to floating point values.

    Adapted from Librosa (BSD-3).
    """
    scale = 1.0 / float(1 << ((8 * n_bytes) - 1))
    fmt = "<i{:d}".format(n_bytes)
    return scale * np.frombuffer(x, fmt).astype(dtype)
