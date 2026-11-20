"""Turn a spoken TTS clip into a "sung" note with the WORLD vocoder.

A clip is analysed into pitch, spectral envelope and aperiodicity.  The pitch contour is
replaced by the target note (with an onset glide and, on long notes, vibrato) and the clip is
stretched or squeezed to the note's duration.  Only the steady middle of the clip is
time-warped; the consonant at the start and the release at the end keep their natural speed,
which is how a singer sustains a syllable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pyworld
from scipy.signal import resample_poly

FloatArray = npt.NDArray[np.float32]
F64Array = npt.NDArray[np.float64]

FRAME_MS = 5.0
ACTIVE_THRESHOLD = 0.05
"""A clip is "sounding" where its RMS envelope is at least this fraction of its maximum.

This single definition is used both to trim TTS clips and to measure the ground-truth start
and end of every rendered token, so it *is* the benchmark's definition of when a syllable
starts: the first moment its level comes within 26 dB of its loudest point.
"""
_ENVELOPE_MS = 5.0
_HEAD_AFTER_VOICING_FRAMES = 6
_TAIL_FRAMES = 8


@dataclass(frozen=True)
class NoteSpec:
    """How a token should be sung."""

    midi: float
    duration_s: float
    glide_cents: float = 0.0
    """Pitch offset at the voicing onset; decays to zero within a few tens of milliseconds."""
    detune_cents: float = 0.0
    vibrato_cents: float = 0.0
    vibrato_hz: float = 5.5
    fade_out_ms: float = 12.0
    """Length of the release.  Legato notes use a long one and overlap the next note."""


def rms_envelope(audio: FloatArray, sample_rate: int, window_ms: float = _ENVELOPE_MS) -> F64Array:
    """Short-time RMS of ``audio`` (centred moving window), same length as the input."""
    window = max(1, round(sample_rate * window_ms / 1000))
    squared = np.asarray(audio, dtype=np.float64) ** 2
    kernel = np.ones(window, dtype=np.float64) / window
    return np.sqrt(np.convolve(squared, kernel, mode="same"))


def active_bounds(
    audio: FloatArray, sample_rate: int, threshold: float = ACTIVE_THRESHOLD
) -> tuple[int, int] | None:
    """Return ``(first, last + 1)`` sample indices of the sounding part, or ``None`` if silent."""
    if audio.size == 0:
        return None
    envelope = rms_envelope(audio, sample_rate)
    peak = float(envelope.max())
    if peak <= 1e-6:
        return None
    above = np.flatnonzero(envelope >= threshold * peak)
    return int(above[0]), int(above[-1]) + 1


def trim_to_active(
    audio: FloatArray, sample_rate: int, pre_ms: float = 4.0, post_ms: float = 12.0
) -> FloatArray:
    """Cut leading and trailing silence, keeping a few milliseconds of context."""
    bounds = active_bounds(audio, sample_rate)
    if bounds is None:
        return audio
    start = max(0, bounds[0] - round(sample_rate * pre_ms / 1000))
    end = min(audio.size, bounds[1] + round(sample_rate * post_ms / 1000))
    return audio[start:end]


def midi_to_hz(midi: float) -> float:
    """Frequency of a MIDI note number (A4 = 69 = 440 Hz)."""
    return float(440.0 * 2.0 ** ((midi - 69.0) / 12.0))


def hz_to_midi(hz: float) -> float:
    """MIDI note number of a frequency."""
    return float(69.0 + 12.0 * np.log2(hz / 440.0))


def _analyse(clip: FloatArray, sample_rate: int) -> tuple[F64Array, F64Array, F64Array]:
    signal = np.ascontiguousarray(clip, dtype=np.float64)
    f0, times = pyworld.dio(
        signal, sample_rate, f0_floor=65.0, f0_ceil=650.0, frame_period=FRAME_MS
    )
    f0 = pyworld.stonemask(signal, f0, times, sample_rate)
    spectrum = pyworld.cheaptrick(signal, f0, times, sample_rate)
    aperiodicity = pyworld.d4c(signal, f0, times, sample_rate)
    return f0, spectrum, aperiodicity


def median_f0(clip: FloatArray, sample_rate: int) -> float | None:
    """Median fundamental frequency of the voiced part of a clip, or ``None`` if unvoiced."""
    if clip.size < sample_rate // 50:
        return None
    signal = np.ascontiguousarray(clip, dtype=np.float64)
    f0, times = pyworld.dio(
        signal, sample_rate, f0_floor=65.0, f0_ceil=650.0, frame_period=FRAME_MS
    )
    f0 = pyworld.stonemask(signal, f0, times, sample_rate)
    voiced = f0[f0 > 0]
    if voiced.size < 4:
        return None
    return float(np.median(voiced))


def _warp_positions(frames: int, target: int, first_voiced: int | None) -> F64Array:
    """Map each output frame to a (fractional) source frame."""
    head = (
        frames if first_voiced is None else min(frames, first_voiced + _HEAD_AFTER_VOICING_FRAMES)
    )
    tail = min(_TAIL_FRAMES, max(0, frames - head))
    middle_target = target - head - tail
    if first_voiced is None or middle_target < 2 or frames - head - tail < 2:
        return np.linspace(0.0, frames - 1, target)
    return np.concatenate(
        [
            np.arange(head, dtype=np.float64),
            np.linspace(head, frames - tail - 1, middle_target),
            np.arange(frames - tail, frames, dtype=np.float64),
        ]
    )


def _pitch_contour(spec: NoteSpec, voiced: npt.NDArray[np.bool_]) -> F64Array:
    """Target f0 (Hz) for every output frame; zero where unvoiced."""
    count = voiced.size
    times = np.arange(count, dtype=np.float64) * (FRAME_MS / 1000.0)
    voiced_frames = np.flatnonzero(voiced)
    onset_time = float(times[voiced_frames[0]]) if voiced_frames.size else 0.0
    since_onset = np.maximum(times - onset_time, 0.0)
    cents = spec.detune_cents + spec.glide_cents * np.exp(-since_onset / 0.035)
    if spec.vibrato_cents > 0.0:
        ramp = np.clip((since_onset - 0.25) / 0.25, 0.0, 1.0)
        cents = cents + spec.vibrato_cents * ramp * np.sin(
            2.0 * np.pi * spec.vibrato_hz * since_onset
        )
    contour = midi_to_hz(spec.midi) * 2.0 ** (cents / 1200.0)
    return np.where(voiced, contour, 0.0)


def render_note(clip: FloatArray, sample_rate: int, spec: NoteSpec) -> FloatArray:
    """Re-synthesise ``clip`` as a note of the requested pitch and duration.

    Args:
        clip: Trimmed mono speech clip of one character or word.
        sample_rate: Sample rate of ``clip``.
        spec: Target pitch, duration and ornaments.

    Returns:
        Mono float32 audio, RMS-normalised, of approximately ``spec.duration_s`` seconds.
    """
    if clip.size < sample_rate // 100:
        return np.zeros(max(1, round(spec.duration_s * sample_rate)), dtype=np.float32)
    f0, spectrum, aperiodicity = _analyse(clip, sample_rate)
    frames = int(f0.size)
    target = max(4, round(spec.duration_s * 1000.0 / FRAME_MS))
    voiced_source = np.flatnonzero(f0 > 0)
    first_voiced = int(voiced_source[0]) if voiced_source.size else None

    positions = _warp_positions(frames, target, first_voiced)
    lower = np.floor(positions).astype(np.int64)
    upper = np.minimum(lower + 1, frames - 1)
    weight = (positions - lower)[:, np.newaxis]
    warped_spectrum = (1.0 - weight) * spectrum[lower] + weight * spectrum[upper]
    warped_aperiodicity = (1.0 - weight) * aperiodicity[lower] + weight * aperiodicity[upper]
    voiced = f0[np.clip(np.rint(positions).astype(np.int64), 0, frames - 1)] > 0

    synthesised = pyworld.synthesize(
        np.ascontiguousarray(_pitch_contour(spec, voiced)),
        np.ascontiguousarray(warped_spectrum),
        np.ascontiguousarray(warped_aperiodicity),
        sample_rate,
        FRAME_MS,
    )
    audio = np.asarray(synthesised[: round(spec.duration_s * sample_rate)], dtype=np.float32)
    return apply_fades(normalise_rms(audio), sample_rate, fade_out_ms=spec.fade_out_ms)


def apply_fades(
    audio: FloatArray, sample_rate: int, fade_in_ms: float = 2.0, fade_out_ms: float = 12.0
) -> FloatArray:
    """Apply short linear fades so that clips can be butted together without clicks."""
    result = audio.copy()
    fade_in = min(result.size, round(sample_rate * fade_in_ms / 1000))
    fade_out = min(result.size, round(sample_rate * fade_out_ms / 1000))
    if fade_in > 0:
        result[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out > 0:
        result[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    return result


def normalise_rms(audio: FloatArray, target_rms: float = 0.1) -> FloatArray:
    """Scale ``audio`` so that its sounding part has the given RMS level."""
    envelope = np.abs(audio)
    peak = float(envelope.max()) if audio.size else 0.0
    if peak <= 1e-6:
        return audio
    sounding = audio[envelope >= 0.1 * peak]
    level = float(np.sqrt(np.mean(sounding.astype(np.float64) ** 2)))
    if level <= 1e-9:
        return audio
    scaled = audio * np.float32(target_rms / level)
    ceiling = float(np.abs(scaled).max())
    if ceiling > 0.95:
        scaled = scaled * np.float32(0.95 / ceiling)
    return scaled.astype(np.float32)


def upsample(audio: FloatArray, source_rate: int, target_rate: int) -> FloatArray:
    """Resample with a zero-phase polyphase filter (no time shift)."""
    if source_rate == target_rate:
        return audio
    divisor = int(np.gcd(source_rate, target_rate))
    resampled = resample_poly(
        np.asarray(audio, dtype=np.float64), target_rate // divisor, source_rate // divisor
    )
    return np.asarray(resampled, dtype=np.float32)
