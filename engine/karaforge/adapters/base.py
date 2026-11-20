"""Adapter interfaces: every model sits behind one of these protocols.

An adapter wraps one third-party model family (a separator, a speech recogniser, a forced
aligner, …) and declares what it is — name, version, licence, languages, devices, memory —
through :class:`AdapterInfo`.  The name and version become part of the pipeline's cache keys,
so bumping an adapter's ``version`` invalidates exactly the results it produced.

See ``docs/adapters.md`` for a walk-through of adding a new adapter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from karaforge.audio.io import FloatArray
from karaforge.device import DeviceKind
from karaforge.runtime import CancelToken, ProgressFn
from karaforge.text.tokenize import TokenKind


@dataclass(frozen=True)
class AdapterInfo:
    """Self-description that every adapter must provide."""

    name: str
    version: str
    license: str
    """Licence of the *weights* the adapter loads (the code licence is in docs/LICENSES.md)."""
    languages: tuple[str, ...]
    """BCP-47 language prefixes it supports; ``("*",)`` means language independent."""
    devices: tuple[DeviceKind, ...]
    memory_mb: int
    """Approximate peak memory (RAM, or VRAM on a GPU) in megabytes."""
    description_zh: str = ""
    description_en: str = ""
    models: tuple[str, ...] = ()
    """Registry ids of the weights the adapter needs (downloaded before it first runs)."""

    @property
    def tag(self) -> str:
        """``name@version``, as used in cache keys."""
        return f"{self.name}@{self.version}"

    def supports_language(self, language: str) -> bool:
        """Whether ``language`` (e.g. ``zh-TW``) is covered."""
        prefix = language.split("-")[0].lower()
        return "*" in self.languages or prefix in self.languages


# ------------------------------------------------------------------------------ separation


@dataclass(frozen=True)
class SeparationResult:
    """Paths of the stems written by a :class:`Separator`.

    Both files have the same sample rate, channel count and length as the input.
    """

    vocals: Path
    instrumental: Path


@runtime_checkable
class Separator(Protocol):
    """Splits a mix into a vocal stem and an accompaniment stem."""

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        ...

    def separate(
        self,
        audio: Path,
        out_dir: Path,
        *,
        progress: ProgressFn,
        cancel: CancelToken,
    ) -> SeparationResult:
        """Separate ``audio`` (a WAV file) and write ``vocals.wav`` / ``instrumental.wav``."""
        ...


# ------------------------------------------------------------------------------------ ASR


@dataclass(frozen=True)
class AsrWord:
    """A recognised word (for Chinese usually a single character) with its time span."""

    text: str
    start_s: float
    end_s: float
    probability: float = 1.0


@dataclass(frozen=True)
class AsrSegment:
    """A recognised phrase."""

    text: str
    start_s: float
    end_s: float
    words: tuple[AsrWord, ...] = ()


@dataclass(frozen=True)
class Transcript:
    """The output of a :class:`Transcriber`."""

    language: str
    segments: tuple[AsrSegment, ...] = ()

    @property
    def words(self) -> list[AsrWord]:
        """All words of all segments in order."""
        return [word for segment in self.segments for word in segment.words]


@runtime_checkable
class Transcriber(Protocol):
    """Speech recogniser that returns word-level timestamps."""

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        ...

    def transcribe(
        self,
        audio: FloatArray,
        *,
        language: str | None,
        prompt: str | None,
        progress: ProgressFn,
        cancel: CancelToken,
    ) -> Transcript:
        """Transcribe 16 kHz mono ``audio``.

        Args:
            audio: Mono float32 samples at :data:`karaforge.audio.MODEL_RATE`.
            language: Language hint (``zh``, ``en`` …) or ``None`` to auto-detect.
            prompt: Text that biases recognition, e.g. the known lyrics.
            progress: Progress callback.
            cancel: Cancellation token.
        """
        ...


# ------------------------------------------------------------------------------ alignment


@dataclass(frozen=True)
class AlignUnit:
    """One token to be placed in time by an :class:`Aligner`."""

    text: str
    """The token's core text (no punctuation), e.g. ``我`` or ``together``."""
    kind: TokenKind
    reading: str | None = None
    """Romanised pronunciation when known (toneless pinyin for Chinese), else ``None``."""


@dataclass(frozen=True)
class UnitTiming:
    """Where an aligner placed a unit, relative to the start of the audio it was given."""

    start_s: float
    end_s: float
    score: float
    """Aligner's own confidence in ``[0, 1]`` (posterior probability or similar)."""


@dataclass(frozen=True)
class AlignRequest:
    """Audio and text handed to an aligner for one window."""

    audio: FloatArray
    """16 kHz mono samples of the window."""
    units: Sequence[AlignUnit]
    language: str
    open_start: bool = True
    """The window may begin with sound that is *not* part of ``units`` (a neighbouring line)."""
    open_end: bool = True
    """The window may end with sound that is not part of ``units``."""
    prefix_units: Sequence[AlignUnit] = ()
    """The last tokens of the previous line, when its tail may be audible at the start of the
    window.  Aligners can use them to soak up that sound; they are never returned."""
    suffix_units: Sequence[AlignUnit] = ()
    """The first tokens of the next line, when its head may be audible at the end."""
    offset_s: float | None = None
    """Where ``audio`` begins inside the recording last passed to ``prepare`` (see
    :class:`Aligner`); ``None`` when the window is not a slice of that recording."""
    extra: dict[str, object] = field(default_factory=dict[str, object])


@runtime_checkable
class Aligner(Protocol):
    """Forced aligner: given audio and its transcript, finds when each unit is sung.

    Optional extras that the alignment passes look for with ``getattr``:

    ``prepare(audio)``
        Called once with the whole vocal stem before the per-line requests.  An aligner whose
        acoustic model is independent of the text (CTC) can run it once here and answer every
        request — and every later re-alignment of the same stem — from the stored result.
    ``max_window_s``
        Longest window the aligner accepts.
    ``lead_ms``
        The aligner's systematic lateness, subtracted from every start it reports.
    ``weak_score``
        Score below which the aligner had no real evidence for a token's position.
    """

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        ...

    def align(self, request: AlignRequest) -> list[UnitTiming]:
        """Align ``request.units`` to ``request.audio``.

        Returns:
            One timing per unit, in order, with non-decreasing start times.
        """
        ...
