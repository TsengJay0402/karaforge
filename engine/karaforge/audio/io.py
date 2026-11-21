"""Reading, writing and resampling PCM audio.

Inside the engine audio is always ``float32`` in ``[-1, 1]``; stereo arrays have shape
``(samples, channels)``.  Speech models take 16 kHz mono (:data:`MODEL_RATE`).
"""

from __future__ import annotations

from math import gcd
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf
from scipy.signal import resample_poly

from karaforge.errors import MediaError

FloatArray = npt.NDArray[np.float32]

MODEL_RATE = 16000
"""Sample rate expected by the speech models (ASR, aligners, VAD)."""


def read_wav(path: Path) -> tuple[FloatArray, int]:
    """Read an audio file as float32 with shape ``(samples, channels)``.

    Raises:
        MediaError: If the file cannot be read.
    """
    try:
        data, rate = sf.read(path, dtype="float32", always_2d=True)
    except (OSError, RuntimeError) as exc:
        raise MediaError(
            f"無法讀取音訊檔：{path.name}",
            f"Cannot read audio file: {path.name}",
            detail=str(exc),
        ) from exc
    return np.asarray(data, dtype=np.float32), int(rate)


def resample(audio: FloatArray, source_rate: int, target_rate: int) -> FloatArray:
    """Resample along the first axis with a zero-phase polyphase filter (no time shift)."""
    if source_rate == target_rate or audio.shape[0] == 0:
        return audio
    divisor = gcd(source_rate, target_rate)
    result = resample_poly(
        np.asarray(audio, dtype=np.float64),
        target_rate // divisor,
        source_rate // divisor,
        axis=0,
    )
    return np.asarray(result, dtype=np.float32)


def read_mono(path: Path, rate: int = MODEL_RATE) -> FloatArray:
    """Read an audio file, mix it down to mono and resample it to ``rate``."""
    data, source_rate = read_wav(path)
    mono = np.asarray(data.mean(axis=1), dtype=np.float32)
    return resample(mono, source_rate, rate)


def write_wav(path: Path, audio: FloatArray, rate: int, *, subtype: str = "PCM_16") -> None:
    """Write float32 audio as a WAV file (16-bit PCM by default), atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    clipped = np.clip(audio, -1.0, 1.0)
    sf.write(temporary, clipped, rate, subtype=subtype, format="WAV")
    temporary.replace(path)


def audio_duration_ms(path: Path) -> int:
    """Duration of an audio file in milliseconds."""
    info = sf.info(path)
    return round(info.frames * 1000 / info.samplerate)
