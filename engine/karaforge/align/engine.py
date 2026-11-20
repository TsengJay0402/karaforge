"""Orchestrates the alignment passes: coarse → fine → refine → confidence."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from karaforge.adapters.base import Aligner, AsrWord
from karaforge.align.coarse import LineWindow, LyricLine, coarse_align, distribute_lines
from karaforge.align.confidence import score_tokens
from karaforge.align.features import VocalFeatures
from karaforge.align.fine import TokenTiming, fine_align
from karaforge.align.refine import RefinedToken, RefineSettings, refine
from karaforge.audio.io import MODEL_RATE, FloatArray
from karaforge.errors import AlignmentError
from karaforge.pipeline.profiles import AlignSettings
from karaforge.project.schema import Project
from karaforge.runtime import CancelToken, ProgressFn, null_progress, subprogress
from karaforge.text.romanize import romanize_tokens
from karaforge.text.tokenize import TokenKind, tokenize

ALIGN_ALGORITHM_VERSION = "5"
"""Bump when the algorithm changes in a way that alters results for the same inputs."""


@dataclass
class AlignmentOutput:
    """Everything the alignment produced."""

    tokens: list[list[RefinedToken]]
    confidences: list[list[float]]
    windows: list[LineWindow]
    seconds: dict[str, float] = field(default_factory=dict[str, float])
    """Wall-clock time of each pass."""


def lyric_lines(project: Project) -> list[LyricLine]:
    """Convert a project's lines into the form the alignment passes work on.

    Lines without tokens are skipped; the caller keeps the mapping through ``LyricLine.id``.
    """
    result: list[LyricLine] = []
    for line in project.lines:
        if not line.tokens:
            continue
        cores: list[str] = []
        kinds: list[TokenKind] = []
        for token in line.tokens:
            pieces = [piece for piece in tokenize(token.text) if piece.core]
            cores.append("".join(piece.core for piece in pieces))
            kinds.append(pieces[0].kind if pieces else TokenKind.NONE)
        manual = [
            token.ruby if token.ruby and token.ruby_source == "manual" else None
            for token in line.tokens
        ]
        readings = romanize_tokens(cores, kinds, manual)
        locked = tuple(
            (token.start_ms / 1000.0, token.end_ms / 1000.0)
            if token.locked and token.start_ms is not None and token.end_ms is not None
            else None
            for token in line.tokens
        )
        result.append(
            LyricLine(
                id=line.id,
                cores=tuple(cores),
                kinds=tuple(kinds),
                readings=tuple(readings),
                locked=locked,
            )
        )
    return result


def run_alignment(
    lines: Sequence[LyricLine],
    *,
    audio: FloatArray,
    features: VocalFeatures,
    words: Sequence[AsrWord],
    aligner: Aligner,
    settings: AlignSettings,
    language: str,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
    max_window_s: float | None = None,
) -> AlignmentOutput:
    """Align lyric lines to the vocal stem.

    Args:
        lines: Lyric lines in singing order.
        audio: 16 kHz mono vocal stem.
        features: Features of the vocal stem (energy, regions, onsets).
        words: Speech-recognition words with timestamps (may be empty).
        aligner: Forced aligner for the fine pass.
        settings: Alignment parameters.
        language: Project language, e.g. ``zh-TW``.
        progress: Progress callback.
        cancel: Cancellation token.
        max_window_s: Longest audio window the aligner accepts, if limited.

    Raises:
        AlignmentError: If there is nothing to align or the audio is empty.
    """
    token = cancel or CancelToken()
    if not lines:
        raise AlignmentError(
            "沒有可以對齊的歌詞。",
            "There are no lyrics to align.",
            hint_zh="請先加入歌詞,或用「沒有歌詞,用 AI 辨識」產生草稿。",
            hint_en="Add lyrics first, or let speech recognition draft them.",
        )
    duration = audio.size / MODEL_RATE
    if duration <= 0.0:
        raise AlignmentError("人聲軌是空的,無法對齊。", "The vocal stem is empty.")
    seconds: dict[str, float] = {}

    started = time.monotonic()
    if settings.coarse == "asr":
        windows = coarse_align(lines, words, features.regions_s, duration)
    elif settings.coarse == "regions":
        windows = coarse_align(lines, [], features.regions_s, duration)
    else:
        windows = _global_windows(lines, features, duration)
    seconds["coarse"] = time.monotonic() - started
    progress(0.05, "行層級錨定 / anchoring lines")

    started = time.monotonic()
    if settings.coarse == "global":
        fine = _align_globally(lines, audio, aligner, language, token)
    else:
        fine = fine_align(
            lines,
            windows,
            audio,
            aligner,
            language=language,
            pad_s=settings.window_pad_ms / 1000.0,
            progress=subprogress(progress, 0.05, 0.9),
            cancel=token,
            max_window_s=max_window_s,
            features=features,
        )
    seconds["fine"] = time.monotonic() - started

    started = time.monotonic()
    refined = refine(
        fine,
        features,
        RefineSettings(
            onset_snap=settings.onset_snap,
            onset_snap_ms=settings.onset_snap_ms,
            min_token_ms=settings.min_token_ms,
            pause_threshold_ms=settings.pause_threshold_ms,
            long_note=settings.long_note,
            max_tail_ms=settings.max_tail_ms,
        ),
        duration,
    )
    confidences = score_tokens(refined, windows)
    seconds["refine"] = time.monotonic() - started
    progress(1.0, "精修時間 / refining")
    return AlignmentOutput(refined, confidences, list(windows), seconds)


def _global_windows(
    lines: Sequence[LyricLine], features: VocalFeatures, duration: float
) -> list[LineWindow]:
    """Nominal windows for the ``global`` mode (used only for confidence bookkeeping)."""
    placed = distribute_lines([line.size for line in lines], features.regions_s, 0.0, duration)
    return [
        LineWindow(start, end, 0.0, source, [None] * line.size)
        for line, (start, end, source) in zip(lines, placed, strict=True)
    ]


def _align_globally(
    lines: Sequence[LyricLine],
    audio: FloatArray,
    aligner: Aligner,
    language: str,
    cancel: CancelToken,
) -> list[list[TokenTiming]]:
    """Ablation mode: align every token of the song in one pass, without line windows."""
    merged = LyricLine(
        id="*",
        cores=tuple(core for line in lines for core in line.cores),
        kinds=tuple(kind for line in lines for kind in line.kinds),
        readings=tuple(reading for line in lines for reading in line.readings),
        locked=tuple(lock for line in lines for lock in line.locked),
    )
    duration = audio.size / MODEL_RATE
    window = LineWindow(0.0, duration, 0.0, "interpolated", [None] * merged.size)
    flat = fine_align(
        [merged],
        [window],
        audio,
        aligner,
        language=language,
        pad_s=0.0,
        progress=null_progress,
        cancel=cancel,
    )[0]
    result: list[list[TokenTiming]] = []
    cursor = 0
    for line in lines:
        result.append(list(flat[cursor : cursor + line.size]))
        cursor += line.size
    return result
