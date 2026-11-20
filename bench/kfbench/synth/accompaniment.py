"""A small numpy "band": chord pad, bass, drums and an interlude lead.

The goal is not beauty but a backing track with the spectral and rhythmic ingredients that
make vocal separation and alignment non-trivial: sustained harmonic content in the vocal
range, a bass line, broadband percussive transients on the beat, and a melodic lead that
plays while nobody sings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float32]
F64Array = npt.NDArray[np.float64]

MAJOR = (0, 4, 7)
MINOR = (0, 3, 7)

# (semitones above the key, chord quality) per bar; each list is one four-bar loop.
PROGRESSIONS: tuple[tuple[tuple[int, tuple[int, int, int]], ...], ...] = (
    ((0, MAJOR), (7, MAJOR), (9, MINOR), (5, MAJOR)),
    ((9, MINOR), (5, MAJOR), (0, MAJOR), (7, MAJOR)),
    ((0, MAJOR), (9, MINOR), (5, MAJOR), (7, MAJOR)),
    ((0, MAJOR), (5, MAJOR), (7, MAJOR), (5, MAJOR)),
    ((2, MINOR), (7, MAJOR), (0, MAJOR), (9, MINOR)),
)


@dataclass(frozen=True)
class Section:
    """A run of bars with one arrangement style."""

    kind: str
    """``intro``, ``verse``, ``chorus``, ``interlude`` or ``outro``."""
    start_bar: int
    bars: int


@dataclass(frozen=True)
class Arrangement:
    """Everything the band needs to know about the song."""

    bpm: float
    key: int
    """Pitch class of the tonic (0 = C)."""
    progression: int
    """Index into :data:`PROGRESSIONS`."""
    sections: tuple[Section, ...]

    @property
    def beat_s(self) -> float:
        """Duration of one beat in seconds."""
        return 60.0 / self.bpm

    @property
    def bar_s(self) -> float:
        """Duration of one 4/4 bar in seconds."""
        return 4.0 * self.beat_s

    @property
    def total_bars(self) -> int:
        """Number of bars in the song."""
        return sum(section.bars for section in self.sections)

    @property
    def duration_s(self) -> float:
        """Length of the song in seconds."""
        return self.total_bars * self.bar_s

    def chord(self, bar: int) -> tuple[int, tuple[int, int, int]]:
        """Root (semitones above the key) and quality of the chord in ``bar``."""
        loop = PROGRESSIONS[self.progression]
        return loop[bar % len(loop)]

    def chord_pitch_classes(self, bar: int) -> tuple[int, ...]:
        """Pitch classes of the chord tones in ``bar``."""
        root, quality = self.chord(bar)
        return tuple((self.key + root + interval) % 12 for interval in quality)

    def section_at(self, bar: int) -> Section:
        """The section that contains ``bar``."""
        for section in self.sections:
            if section.start_bar <= bar < section.start_bar + section.bars:
                return section
        return self.sections[-1]


def _hz(midi: float) -> float:
    return float(440.0 * 2.0 ** ((midi - 69.0) / 12.0))


def _add(track: F64Array, start_s: float, sound: F64Array, sample_rate: int) -> None:
    start = round(start_s * sample_rate)
    if start >= track.size or start < 0:
        return
    end = min(track.size, start + sound.size)
    track[start:end] += sound[: end - start]


def _time(duration_s: float, sample_rate: int) -> F64Array:
    return np.arange(max(1, round(duration_s * sample_rate)), dtype=np.float64) / sample_rate


def _pad_note(midi: float, duration_s: float, sample_rate: int, detune_cents: float) -> F64Array:
    """Soft sawtooth-like tone built from a handful of harmonics."""
    t = _time(duration_s, sample_rate)
    base = _hz(midi) * 2.0 ** (detune_cents / 1200.0)
    tone = np.zeros_like(t)
    for harmonic in range(1, 7):
        frequency = base * harmonic
        if frequency < sample_rate / 2.5:
            tone += np.sin(2.0 * np.pi * frequency * t) / harmonic**1.4
    attack = np.clip(t / 0.08, 0.0, 1.0)
    release = np.clip((duration_s - t) / 0.15, 0.0, 1.0)
    return tone * attack * release


def _bass_note(midi: float, duration_s: float, sample_rate: int) -> F64Array:
    t = _time(duration_s, sample_rate)
    frequency = _hz(midi)
    tone = np.sin(2.0 * np.pi * frequency * t) + 0.35 * np.sin(4.0 * np.pi * frequency * t)
    envelope = np.exp(-t / 0.28) * np.clip(t / 0.004, 0.0, 1.0)
    return tone * envelope


def _kick(sample_rate: int) -> F64Array:
    t = _time(0.22, sample_rate)
    phase = 2.0 * np.pi * (48.0 * t + 100.0 * 0.03 * (1.0 - np.exp(-t / 0.03)))
    return np.sin(phase) * np.exp(-t / 0.09)


def _snare(sample_rate: int, rng: np.random.Generator) -> F64Array:
    t = _time(0.18, sample_rate)
    noise = rng.standard_normal(t.size)
    noise = noise - np.concatenate([[0.0], noise[:-1]]) * 0.6  # tilt towards the highs
    body = 0.4 * np.sin(2.0 * np.pi * 190.0 * t) * np.exp(-t / 0.05)
    return 0.6 * noise * np.exp(-t / 0.055) + body


def _hat(sample_rate: int, rng: np.random.Generator, length_s: float = 0.045) -> F64Array:
    t = _time(length_s, sample_rate)
    noise = np.diff(rng.standard_normal(t.size + 2), n=2)  # crude high-pass
    return 0.35 * noise * np.exp(-t / 0.012)


def _lead_note(midi: float, duration_s: float, sample_rate: int) -> F64Array:
    t = _time(duration_s, sample_rate)
    frequency = _hz(midi)
    tone = (
        np.sin(2.0 * np.pi * frequency * t)
        + 0.33 * np.sin(6.0 * np.pi * frequency * t)
        + 0.12 * np.sin(10.0 * np.pi * frequency * t)
    )
    envelope = np.exp(-t / 0.22) * np.clip(t / 0.006, 0.0, 1.0)
    return tone * envelope


def render_accompaniment(
    arrangement: Arrangement, sample_rate: int, rng: np.random.Generator
) -> FloatArray:
    """Render the backing track.

    Returns:
        Stereo float32 audio of shape ``(samples, 2)``, peak-normalised to 0.9.
    """
    samples = round(arrangement.duration_s * sample_rate) + sample_rate // 2
    pad_left = np.zeros(samples)
    pad_right = np.zeros(samples)
    centre = np.zeros(samples)
    hats = np.zeros(samples)
    lead = np.zeros(samples)

    beat = arrangement.beat_s
    bar = arrangement.bar_s
    kick, snare = _kick(sample_rate), _snare(sample_rate, rng)

    for index in range(arrangement.total_bars):
        section = arrangement.section_at(index)
        bar_start = index * bar
        root, quality = arrangement.chord(index)
        root_pitch = arrangement.key + root
        busy = section.kind == "chorus"
        quiet = section.kind in ("intro", "outro")

        # Pad: the triad around middle C, slightly detuned between the two channels.
        for interval in quality:
            midi = 55 + (root_pitch + interval - 55) % 12
            _add(pad_left, bar_start, 0.22 * _pad_note(midi, bar, sample_rate, -6.0), sample_rate)
            _add(pad_right, bar_start, 0.22 * _pad_note(midi, bar, sample_rate, 7.0), sample_rate)

        # Bass: root on beats 1 and 3, fifth as a pickup before the next bar.
        bass_root = 36 + (root_pitch - 36) % 12
        _add(centre, bar_start, 0.55 * _bass_note(bass_root, 1.9 * beat, sample_rate), sample_rate)
        _add(
            centre,
            bar_start + 2.0 * beat,
            0.5 * _bass_note(bass_root, 1.4 * beat, sample_rate),
            sample_rate,
        )
        _add(
            centre,
            bar_start + 3.5 * beat,
            0.4 * _bass_note(bass_root + 7, 0.5 * beat, sample_rate),
            sample_rate,
        )

        # Drums.
        if not quiet or index % 2 == 1:
            for beat_index in (0, 2):
                _add(centre, bar_start + beat_index * beat, 0.8 * kick, sample_rate)
            for beat_index in (1, 3):
                _add(centre, bar_start + beat_index * beat, 0.5 * snare, sample_rate)
        subdivisions = 16 if busy else 8
        for step in range(subdivisions):
            accent = 1.0 if step % (subdivisions // 4) == 0 else 0.55
            _add(
                hats,
                bar_start + step * 4.0 * beat / subdivisions,
                accent * _hat(sample_rate, rng),
                sample_rate,
            )

        # Lead: an arpeggio whenever the singer rests for a whole section.
        if section.kind in ("intro", "interlude", "outro"):
            tones = [72 + (root_pitch + interval - 72) % 12 for interval in quality]
            pattern = (0, 1, 2, 1, 0, 2, 1, 2)
            for step, tone_index in enumerate(pattern):
                _add(
                    lead,
                    bar_start + step * beat / 2.0,
                    0.3 * _lead_note(tones[tone_index], beat * 0.9, sample_rate),
                    sample_rate,
                )

    left = pad_left + centre + 0.7 * hats + 1.15 * lead
    right = pad_right + centre + 1.2 * hats + 0.8 * lead
    stereo = np.stack([left, right], axis=1)
    peak = float(np.abs(stereo).max())
    if peak > 0:
        stereo = stereo * (0.9 / peak)
    return stereo.astype(np.float32)
