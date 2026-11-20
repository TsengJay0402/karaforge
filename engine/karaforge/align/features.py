"""Frame-level features of the vocal stem: energy, voice activity and onsets.

Everything is computed at 16 kHz on a 10 ms grid (:data:`HOP_S`).

* **Energy** — RMS level per frame in dB.
* **Voice activity** — frames that are loud enough *and* tonal enough to be a voice; the
  tonality test (spectral flatness) rejects the broadband residue that separation leaves
  from drums.  Runs of active frames are merged into regions.
* **Onsets** — peaks of the spectral flux (the half-wave rectified frame-to-frame increase of
  a log-compressed mel spectrogram), each traced back to where its rise began, because a sung
  syllable starts where the energy starts to grow, not where the growth is fastest.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from karaforge.audio.io import MODEL_RATE, FloatArray

F32 = npt.NDArray[np.float32]
F64 = npt.NDArray[np.float64]

HOP_S = 0.01
_HOP = round(MODEL_RATE * HOP_S)
_FFT = 512
_MELS = 40
FEATURES_VERSION = "1"


@dataclass(frozen=True)
class VocalFeatures:
    """Features of a vocal stem, one value per 10 ms frame unless noted."""

    energy_db: F32
    """RMS level of each frame in dBFS."""
    flatness: F32
    """Spectral flatness in ``[0, 1]`` (0 = pure tone, 1 = white noise)."""
    onset_strength: F32
    """Spectral flux, normalised so that a typical onset peak is around 1."""
    onsets_s: F64
    """Times of detected onsets (start of the energy rise), ascending."""
    onset_peaks: F32
    """Flux value at each detected onset's peak (same length as ``onsets_s``)."""
    regions_s: tuple[tuple[float, float], ...]
    """Voice-activity regions ``(start, end)`` in seconds."""
    noise_floor_db: float
    active_threshold_db: float

    @property
    def frames(self) -> int:
        """Number of frames."""
        return int(self.energy_db.size)

    @property
    def duration_s(self) -> float:
        """Duration covered by the features."""
        return self.frames * HOP_S

    def frame_of(self, time_s: float) -> int:
        """Index of the frame that contains ``time_s`` (clamped to the valid range)."""
        return int(min(max(0, round(time_s / HOP_S)), max(0, self.frames - 1)))

    def is_active(self, time_s: float) -> bool:
        """Whether ``time_s`` falls inside a voice-activity region."""
        return any(start <= time_s <= end for start, end in self.regions_s)


def _frames(signal: FloatArray) -> F32:
    """Slice ``signal`` into overlapping, Hann-windowed frames (centred on the hop grid)."""
    padded = np.pad(signal.astype(np.float32), (_FFT // 2, _FFT // 2))
    count = 1 + (padded.size - _FFT) // _HOP
    index = np.arange(_FFT)[np.newaxis, :] + _HOP * np.arange(count)[:, np.newaxis]
    window = np.hanning(_FFT).astype(np.float32)
    return padded[index] * window


def _mel_filterbank() -> F32:
    """Triangular mel filters covering 60 Hz – 7.6 kHz."""

    def to_mel(hz: F64) -> F64:
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    def to_hz(mel: F64) -> F64:
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    edges = to_hz(np.linspace(to_mel(np.array(60.0)), to_mel(np.array(7600.0)), _MELS + 2))
    bins = np.fft.rfftfreq(_FFT, 1.0 / MODEL_RATE)
    bank = np.zeros((_MELS, bins.size), dtype=np.float32)
    for index in range(_MELS):
        low, centre, high = edges[index], edges[index + 1], edges[index + 2]
        rising = (bins - low) / max(centre - low, 1e-9)
        falling = (high - bins) / max(high - centre, 1e-9)
        bank[index] = np.clip(np.minimum(rising, falling), 0.0, None)
    return bank


def _moving_mean(values: F32, radius: int) -> F32:
    if radius <= 0 or values.size == 0:
        return values
    kernel = np.ones(2 * radius + 1, dtype=np.float32) / (2 * radius + 1)
    return np.convolve(np.pad(values, radius, mode="edge"), kernel, mode="valid").astype(np.float32)


def _moving_max(values: F32, radius: int) -> F32:
    if radius <= 0 or values.size == 0:
        return values
    padded = np.pad(values, radius, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * radius + 1)
    return windows.max(axis=1).astype(np.float32)


def detect_regions(
    energy_db: F32,
    flatness: F32,
    *,
    min_region_ms: int = 200,
    merge_gap_ms: int = 300,
) -> tuple[tuple[tuple[float, float], ...], float, float]:
    """Find voice-activity regions from frame energy and spectral flatness.

    Returns:
        ``(regions, noise_floor_db, threshold_db)``.
    """
    if energy_db.size == 0:
        return (), -120.0, -120.0
    floor = float(np.percentile(energy_db, 10))
    peak = float(np.percentile(energy_db, 99))
    threshold = max(floor + 12.0, peak - 40.0)
    smoothed = _moving_mean(energy_db, 2)
    loud = smoothed >= threshold
    # Quiet-ish frames only count when they are tonal; clearly loud frames always count.
    active = loud & ((flatness < 0.45) | (smoothed >= threshold + 10.0))

    regions: list[list[int]] = []
    start: int | None = None
    for index, flag in enumerate(active):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            regions.append([start, index])
            start = None
    if start is not None:
        regions.append([start, int(active.size)])

    merge_gap = round(merge_gap_ms / 1000 / HOP_S)
    merged: list[list[int]] = []
    for region in regions:
        if merged and region[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = region[1]
        else:
            merged.append(region)
    min_frames = round(min_region_ms / 1000 / HOP_S)
    kept = [region for region in merged if region[1] - region[0] >= min_frames]
    return (
        tuple((region[0] * HOP_S, region[1] * HOP_S) for region in kept),
        floor,
        threshold,
    )


def pick_onsets(flux: F32, energy_db: F32, threshold_db: float) -> tuple[F64, F32]:
    """Pick onset peaks from a flux curve and trace each back to the start of its rise.

    Returns:
        ``(onset_times_s, peak_values)``.
    """
    if flux.size < 5:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float32)
    local_max = _moving_max(flux, 3)
    local_mean = _moving_mean(flux, 10)
    is_peak = (flux >= local_max) & (flux >= local_mean + 0.15) & (flux >= 0.2)
    # A peak must lead somewhere audible: the level shortly after it has to be near the
    # activity threshold, otherwise it is noise-floor jitter.
    ahead = _moving_max(np.concatenate([energy_db[3:], np.repeat(energy_db[-1:], 3)]), 3)
    is_peak &= ahead >= threshold_db - 6.0
    peaks = np.flatnonzero(is_peak)

    times: list[float] = []
    values: list[float] = []
    last_frame = -10
    for peak in peaks:
        if peak - last_frame < 5:  # at most one onset per 50 ms
            if values and flux[peak] > values[-1]:
                values[-1] = float(flux[peak])
            continue
        frame = int(peak)
        limit = max(0, frame - 8)
        while (
            frame > limit and flux[frame - 1] < flux[frame] and flux[frame - 1] > 0.1 * flux[peak]
        ):
            frame -= 1
        times.append(frame * HOP_S)
        values.append(float(flux[peak]))
        last_frame = int(peak)
    return np.asarray(times, dtype=np.float64), np.asarray(values, dtype=np.float32)


def compute_features(
    mono: FloatArray,
    *,
    min_region_ms: int = 200,
    merge_gap_ms: int = 300,
) -> VocalFeatures:
    """Compute :class:`VocalFeatures` for a 16 kHz mono vocal stem."""
    if mono.size < _FFT:
        empty = np.zeros(0, dtype=np.float32)
        return VocalFeatures(empty, empty, empty, np.zeros(0), empty, (), -120.0, -120.0)
    frames = _frames(mono)
    spectrum = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)
    power = spectrum**2

    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) / 0.375)  # undo Hann gain
    energy_db = (20.0 * np.log10(np.maximum(rms, 1e-7))).astype(np.float32)

    band = power[:, 3:200] + 1e-10  # ~90 Hz – 6.2 kHz
    flatness = (np.exp(np.mean(np.log(band), axis=1)) / np.mean(band, axis=1)).astype(np.float32)

    mel = np.log1p(10.0 * (spectrum @ _mel_filterbank().T))
    rise = np.maximum(mel[2:] - mel[:-2], 0.0).sum(axis=1)
    flux = np.concatenate([np.zeros(2, dtype=np.float32), rise.astype(np.float32)])
    scale = float(np.percentile(flux, 98)) if flux.size else 0.0
    flux = (flux / scale).astype(np.float32) if scale > 1e-6 else flux

    regions, floor, threshold = detect_regions(
        energy_db, flatness, min_region_ms=min_region_ms, merge_gap_ms=merge_gap_ms
    )
    onsets, peaks = pick_onsets(flux, energy_db, threshold)
    return VocalFeatures(
        energy_db=energy_db,
        flatness=flatness,
        onset_strength=flux,
        onsets_s=onsets,
        onset_peaks=peaks,
        regions_s=regions,
        noise_floor_db=floor,
        active_threshold_db=threshold,
    )
