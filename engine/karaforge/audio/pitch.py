"""Pitch tracking of the vocal stem (pYIN) and note pitch per token.

Used by the UltraStar export, which needs a note height for every syllable.
"""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import numpy.typing as npt

from karaforge.audio.io import MODEL_RATE, FloatArray
from karaforge.project.schema import Project

F32 = npt.NDArray[np.float32]

HOP_S = 0.02
PITCH_VERSION = "1"
_FMIN_HZ = 65.4  # C2
_FMAX_HZ = 1046.5  # C6
_FRAME = 1024
_MIN_VOICED_FRAMES = 2


def estimate_f0(samples: FloatArray, rate: int = MODEL_RATE) -> F32:
    """Fundamental frequency of a mono signal every :data:`HOP_S` seconds.

    Args:
        samples: Mono audio.
        rate: Sample rate of ``samples``.

    Returns:
        Frequency in Hz per frame; ``nan`` where no pitch was found (silence, consonants).
    """
    if samples.size < _FRAME:
        return np.full(max(1, round(samples.size / rate / HOP_S)), np.nan, dtype=np.float32)
    f0, _voiced, _probability = librosa.pyin(
        samples.astype(np.float32),
        fmin=_FMIN_HZ,
        fmax=_FMAX_HZ,
        sr=rate,
        frame_length=_FRAME * rate // MODEL_RATE,
        hop_length=round(HOP_S * rate),
        resolution=0.25,
    )
    return np.asarray(f0, dtype=np.float32)


def save_f0(path: Path, f0: F32) -> None:
    """Store a pitch track."""
    np.savez_compressed(path, f0=f0, hop_s=np.float32(HOP_S))


def load_f0(path: Path) -> F32:
    """Load a pitch track written by :func:`save_f0`."""
    with np.load(path) as data:
        return np.asarray(data["f0"], dtype=np.float32)


def note_of(f0: F32, start_s: float, end_s: float) -> int | None:
    """MIDI note of the span: the median pitch of its voiced frames, or ``None``."""
    first = max(0, round(start_s / HOP_S))
    last = min(f0.size, max(first + 1, round(end_s / HOP_S)))
    voiced = f0[first:last]
    voiced = voiced[np.isfinite(voiced)]
    if voiced.size < _MIN_VOICED_FRAMES:
        return None
    midi = 69.0 + 12.0 * np.log2(float(np.median(voiced)) / 440.0)
    return round(midi)


def token_pitches(project: Project, f0: F32) -> dict[tuple[str, int], int]:
    """MIDI note for every timed token, keyed by ``(line id, token index)``.

    A token without any voiced frame (a very short or whispered syllable) takes the note of
    the previous token of its line, so that the melody line has no holes.
    """
    result: dict[tuple[str, int], int] = {}
    for line in project.lines:
        previous: int | None = None
        pending: list[int] = []
        for index, token in enumerate(line.tokens):
            if token.start_ms is None or token.end_ms is None:
                continue
            note = note_of(f0, token.start_ms / 1000.0, token.end_ms / 1000.0)
            if note is None:
                if previous is None:
                    pending.append(index)
                else:
                    result[(line.id, index)] = previous
                continue
            for waiting in pending:
                result[(line.id, waiting)] = note
            pending.clear()
            result[(line.id, index)] = note
            previous = note
    return result
