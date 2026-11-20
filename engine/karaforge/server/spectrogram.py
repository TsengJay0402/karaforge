"""Spectrogram tiles of a stem for the editor's timeline, rendered to PNG on request."""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

from karaforge.audio.io import resample

_RATE = 16000
_FFT = 512
_MAX_HZ = 6000.0
_FLOOR_DB = -75.0
_CEILING_DB = -15.0
# Dark blue -> magenta -> orange -> pale yellow; control points of the colour ramp.
_RAMP = np.array(
    [
        [10, 12, 28],
        [48, 24, 104],
        [150, 36, 124],
        [232, 96, 60],
        [252, 196, 96],
        [255, 250, 220],
    ],
    dtype=np.float64,
)


def read_segment(path: Path, start_s: float, end_s: float) -> npt.NDArray[np.float32]:
    """Read ``[start_s, end_s)`` of an audio file as 16 kHz mono (silence outside the file)."""
    with sf.SoundFile(str(path)) as handle:
        rate = handle.samplerate
        first = max(0, round(start_s * rate))
        count = max(0, round(end_s * rate) - first)
        missing_before = max(0, round(-start_s * rate))
        if first >= handle.frames or count == 0:
            data = np.zeros((0, handle.channels), dtype=np.float32)
        else:
            handle.seek(first)
            data = handle.read(count, dtype="float32", always_2d=True)
    mono = np.asarray(data.mean(axis=1), dtype=np.float32)
    mono = resample(mono, rate, _RATE)
    wanted = round((end_s - start_s) * _RATE)
    before = round(missing_before * _RATE / rate)
    padded = np.zeros(max(wanted, 0), dtype=np.float32)
    usable = max(0, min(mono.size, wanted - before))
    padded[before : before + usable] = mono[:usable]
    return padded


def spectrogram_image(
    samples: npt.NDArray[np.float32], width: int, height: int
) -> npt.NDArray[np.uint8]:
    """Render a log-magnitude spectrogram as an ``(height, width, 3)`` RGB image.

    Low frequencies are at the bottom; the frequency axis is linear up to 6 kHz, which is
    where sung syllables show their structure.
    """
    width, height = max(1, width), max(1, height)
    if samples.size < _FFT:
        samples = np.pad(samples, (0, _FFT - samples.size))
    hop = max(1, (samples.size - _FFT) // width)
    starts = np.arange(width) * hop
    starts = np.minimum(starts, samples.size - _FFT)
    frames = samples[starts[:, np.newaxis] + np.arange(_FFT)[np.newaxis, :]]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(_FFT).astype(np.float32), axis=1))
    bins = int(_MAX_HZ / (_RATE / 2) * (spectrum.shape[1] - 1))
    level = 20.0 * np.log10(np.maximum(spectrum[:, :bins] / (_FFT / 4), 1e-6))
    scaled = np.clip((level - _FLOOR_DB) / (_CEILING_DB - _FLOOR_DB), 0.0, 1.0)
    # Resample the frequency axis to the requested height (row 0 = highest frequency).
    rows = np.linspace(bins - 1, 0, height)
    lower = np.floor(rows).astype(np.int64)
    upper = np.minimum(lower + 1, bins - 1)
    weight = (rows - lower)[np.newaxis, :]
    image = (1.0 - weight) * scaled[:, lower] + weight * scaled[:, upper]
    position = image.T * (len(_RAMP) - 1)
    index = np.minimum(position.astype(np.int64), len(_RAMP) - 2)
    blend = (position - index)[..., np.newaxis]
    colours = (1.0 - blend) * _RAMP[index] + blend * _RAMP[index + 1]
    return np.clip(np.rint(colours), 0, 255).astype(np.uint8)


def encode_png(image: npt.NDArray[np.uint8]) -> bytes:
    """Encode an ``(height, width, 3)`` RGB array as a PNG file."""
    height, width, _channels = image.shape
    raw = b"".join(b"\x00" + image[row].tobytes() for row in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    buffer = io.BytesIO()
    buffer.write(b"\x89PNG\r\n\x1a\n")
    buffer.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    buffer.write(chunk(b"IDAT", zlib.compress(raw, 6)))
    buffer.write(chunk(b"IEND", b""))
    return buffer.getvalue()


def render_tile(path: Path, start_s: float, end_s: float, width: int, height: int) -> bytes:
    """PNG spectrogram of ``[start_s, end_s)`` of an audio file."""
    return encode_png(spectrogram_image(read_segment(path, start_s, end_s), width, height))
