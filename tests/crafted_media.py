"""Hostile but well-formed media files for the decoder tests.

Each one is small, yet makes ffmpeg produce or allocate far more than its size
suggests when nothing bounds it:

* Matroska/WebM whose block timestamps are 1 microsecond apart (or all zero),
  so ffmpeg's `-t` limit, which counts timestamps, never fires;
* Matroska PCM that declares an enormous sample rate (huge resampler filter);
* MP4 whose sample table declares tens of millions of samples (huge index).
"""
import struct

_UNKNOWN_SIZE = bytes([0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])

# Opus TOC 0xFB: config 31 (CELT-only, fullband, 20 ms), mono, code 3 (several
# frames); count byte 0x06: six zero-length frames. 2 bytes -> 120 ms of audio.
OPUS_120MS_PACKET = bytes([0xFB, 0x06])


def _size(n: int) -> bytes:
    for length in range(1, 9):
        if n < (1 << (7 * length)) - 1:
            return ((1 << (7 * length)) | n).to_bytes(length, 'big')
    raise ValueError(n)


def _element(element_id: int, payload: bytes) -> bytes:
    return element_id.to_bytes((element_id.bit_length() + 7) // 8, 'big') + _size(len(payload)) + payload


def _uint(element_id: int, value: int) -> bytes:
    return _element(element_id, value.to_bytes(max(1, (value.bit_length() + 7) // 8), 'big'))


def _float(element_id: int, value: float) -> bytes:
    return _element(element_id, struct.pack('>d', value))


def _string(element_id: int, text: str) -> bytes:
    return _element(element_id, text.encode('ascii'))


def _audio_track(codec: str, rate: float, bit_depth=None, private=None) -> bytes:
    audio = _float(0xB5, float(rate)) + _uint(0x9F, 1)
    if bit_depth:
        audio += _uint(0x6264, bit_depth)
    entry = _uint(0xD7, 1) + _uint(0x73C5, 1) + _uint(0x83, 2) + _string(0x86, codec)
    if private is not None:
        entry += _element(0x63A2, private)
    entry += _element(0xE1, audio)
    return _element(0x1654AE6B, _element(0xAE, entry))


def _matroska(doctype: str, track: bytes, blocks, timestamp_scale_ns: int, ts_step: int) -> bytes:
    """blocks: frame payloads; block i gets timestamp i * ts_step (in TimestampScale units)."""
    header = _element(0x1A45DFA3, _uint(0x4286, 1) + _uint(0x42F7, 1) + _uint(0x42F2, 4)
                      + _uint(0x42F3, 8) + _string(0x4282, doctype) + _uint(0x4287, 4) + _uint(0x4285, 2))
    info = _element(0x1549A966, _uint(0x2AD7B1, timestamp_scale_ns) + _string(0x4D80, 't') + _string(0x5741, 't'))
    out = [header, (0x18538067).to_bytes(4, 'big'), _UNKNOWN_SIZE, info, track]
    per_cluster = min(30000, 32767 // max(1, ts_step))
    for first in range(0, len(blocks), per_cluster):
        chunk = blocks[first:first + per_cluster]
        body = _uint(0xE7, first * ts_step) + b''.join(
            _element(0xA3, bytes([0x81]) + struct.pack('>h', i * ts_step) + bytes([0x80]) + data)
            for i, data in enumerate(chunk))
        out.append(_element(0x1F43B675, body))
    return b''.join(out)


def _opus_head() -> bytes:
    return b'OpusHead' + bytes([1, 1]) + struct.pack('<HIhB', 312, 48000, 0, 0)


def opus_webm(packets: int, microsecond_timestamps: bool = True) -> bytes:
    """WebM/Opus (what Chrome records) declaring packets x 120 ms of audio. With
    microsecond timestamps, the whole file claims to last packets microseconds;
    otherwise every block has timestamp 0."""
    track = _audio_track('A_OPUS', 48000, private=_opus_head())
    blocks = [OPUS_120MS_PACKET] * packets
    if microsecond_timestamps:
        return _matroska('webm', track, blocks, timestamp_scale_ns=1000, ts_step=1)
    return _matroska('webm', track, blocks, timestamp_scale_ns=1_000_000, ts_step=0)


def pcm_mkv(samples: int, rate: float, timestamp_scale_ns: int = 1000, ts_step: int = 1) -> bytes:
    """Matroska 16-bit PCM, one sample per block."""
    track = _audio_track('A_PCM/INT/LIT', rate, bit_depth=16)
    return _matroska('matroska', track, [struct.pack('<h', 8000)] * samples, timestamp_scale_ns, ts_step)


def pcm_mkv_one_block(rate: float, samples: int = 2000) -> bytes:
    """Matroska 16-bit PCM with a single block of samples at the given declared rate."""
    pcm = b''.join(struct.pack('<h', (i * 37) % 16000 - 8000) for i in range(samples))
    return _matroska('matroska', _audio_track('A_PCM/INT/LIT', rate, bit_depth=16), [pcm], 1_000_000, 1)


_MP4_CONTAINERS = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts', b'dinf'}


def _mp4_atoms(buf: bytes):
    pos, atoms = 0, []
    while pos + 8 <= len(buf):
        size, kind = struct.unpack('>I4s', buf[pos:pos + 8])
        size = size or len(buf) - pos
        body = buf[pos + 8:pos + size]
        atoms.append((kind, _mp4_atoms(body) if kind in _MP4_CONTAINERS else body))
        pos += size
    return atoms


def _mp4_emit(atoms) -> bytes:
    out = b''
    for kind, body in atoms:
        body = _mp4_emit(body) if isinstance(body, list) else body
        out += struct.pack('>I4s', len(body) + 8, kind) + body
    return out


def mp4_declaring_samples(base_mp4: bytes, samples: int) -> bytes:
    """Rewrite a small AAC .mp4 so its sample table declares `samples` samples."""
    def rewrite(atoms):
        new = []
        for kind, body in atoms:
            if kind == b'stbl':
                table = []
                for k, b in body:
                    if k == b'stts':
                        b = struct.pack('>IIII', 0, 1, samples, 1024)
                    elif k == b'stsc':
                        b = struct.pack('>IIIII', 0, 1, 1, samples, 1)
                    elif k == b'stsz':
                        b = struct.pack('>III', 0, 1, samples)
                    elif k == b'stco':
                        b = struct.pack('>III', 0, 1, 40)
                    elif k in (b'stss', b'ctts', b'sgpd', b'sbgp'):
                        continue
                    table.append((k, b))
                body = table
            elif isinstance(body, list):
                body = rewrite(body)
            new.append((kind, body))
        return new
    return _mp4_emit(rewrite(_mp4_atoms(base_mp4)))
