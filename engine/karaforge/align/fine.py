"""Pass 2 — fine alignment: place every token of a line inside the line's window.

Each line is aligned on its own, in its coarse window padded by about a second on each side.
Locked tokens split a line into independent runs: a run between two locked tokens is aligned
only within the time between them, so a user's correction acts as a hard constraint for
everything around it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from karaforge.adapters.base import Aligner, AlignRequest, AlignUnit
from karaforge.align.coarse import LineWindow, LyricLine
from karaforge.align.features import VocalFeatures
from karaforge.audio.io import MODEL_RATE, FloatArray
from karaforge.runtime import CancelToken, ProgressFn

_MIN_RUN_S_PER_TOKEN = 0.03
_CONTEXT_TOKENS = 4


@dataclass
class TokenTiming:
    """Timing of one token after the fine pass."""

    start_s: float
    end_s: float
    score: float
    """Aligner confidence in ``[0, 1]``; 1.0 for locked tokens, 0.0 when nothing was aligned."""
    locked: bool = False
    estimated: bool = False
    """The time was interpolated because the aligner could not be run on this token."""


def _lock_bounds(lines: Sequence[LyricLine]) -> tuple[list[float | None], list[float | None]]:
    """For each line, the nearest locked time before it and after it in *other* lines."""
    count = len(lines)
    before: list[float | None] = [None] * count
    after: list[float | None] = [None] * count
    latest: float | None = None
    for index, line in enumerate(lines):
        before[index] = latest
        ends = [value[1] for value in line.locked if value is not None]
        if ends:
            latest = ends[-1]
    earliest: float | None = None
    for index in range(count - 1, -1, -1):
        after[index] = earliest
        starts = [value[0] for value in lines[index].locked if value is not None]
        if starts:
            earliest = starts[0]
    return before, after


def _units(line: LyricLine, *, from_end: bool, count: int = _CONTEXT_TOKENS) -> list[AlignUnit]:
    """A few pronounceable tokens from the end (or the start) of a line, as context."""
    indices = [index for index in range(line.size) if line.cores[index]]
    chosen = indices[-count:] if from_end else indices[:count]
    return [
        AlignUnit(text=line.cores[i], kind=line.kinds[i], reading=line.readings[i] or None)
        for i in chosen
    ]


def _voiced(features: VocalFeatures | None, time_s: float) -> bool:
    """Whether somebody is singing at ``time_s`` (false when no features are available)."""
    if features is None or features.frames == 0:
        return False
    return bool(features.energy_db[features.frame_of(time_s)] >= features.active_threshold_db)


def _spread(start: float, end: float, count: int) -> list[tuple[float, float]]:
    """Evenly spaced ``(start, end)`` spans; used when a run cannot be aligned."""
    if count <= 0:
        return []
    step = max(0.0, end - start) / count
    return [(start + index * step, start + (index + 1) * step) for index in range(count)]


def _align_run(
    line: LyricLine,
    indices: list[int],
    start_s: float,
    end_s: float,
    audio: FloatArray,
    aligner: Aligner,
    language: str,
    *,
    open_start: bool,
    open_end: bool,
    prefix: Sequence[AlignUnit] = (),
    suffix: Sequence[AlignUnit] = (),
) -> list[TokenTiming]:
    """Align the tokens ``indices`` of ``line`` inside ``[start_s, end_s]``."""
    voiced = [index for index in indices if line.cores[index]]
    span = end_s - start_s
    if not voiced or span < _MIN_RUN_S_PER_TOKEN * len(voiced):
        return [
            TokenTiming(low, high, 0.0, estimated=True)
            for low, high in _spread(start_s, max(start_s, end_s), len(indices))
        ]
    first_sample = max(0, round(start_s * MODEL_RATE))
    last_sample = min(audio.size, round(end_s * MODEL_RATE))
    units = [
        AlignUnit(
            text=line.cores[index], kind=line.kinds[index], reading=line.readings[index] or None
        )
        for index in voiced
    ]
    timings = aligner.align(
        AlignRequest(
            audio=audio[first_sample:last_sample],
            units=units,
            language=language,
            open_start=open_start,
            open_end=open_end,
            prefix_units=prefix,
            suffix_units=suffix,
        )
    )
    offset = first_sample / MODEL_RATE
    by_index = {
        index: TokenTiming(
            start_s=min(end_s, max(start_s, offset + timing.start_s)),
            end_s=min(end_s, max(start_s, offset + timing.end_s)),
            score=timing.score,
        )
        for index, timing in zip(voiced, timings, strict=True)
    }
    # Tokens without anything pronounceable (pure punctuation) sit at the next token's start.
    result: list[TokenTiming] = []
    for position, index in enumerate(indices):
        if index in by_index:
            result.append(by_index[index])
            continue
        following = next((by_index[i] for i in indices[position + 1 :] if i in by_index), None)
        anchor = following.start_s if following is not None else end_s
        result.append(TokenTiming(anchor, anchor, 0.0, estimated=True))
    return result


def fine_align(
    lines: Sequence[LyricLine],
    windows: Sequence[LineWindow],
    audio: FloatArray,
    aligner: Aligner,
    *,
    language: str,
    pad_s: float,
    progress: ProgressFn,
    cancel: CancelToken,
    max_window_s: float | None = None,
    features: VocalFeatures | None = None,
) -> list[list[TokenTiming]]:
    """Run the aligner on every line.

    Args:
        lines: Lyric lines in order.
        windows: Coarse window of each line.
        audio: 16 kHz mono vocal stem.
        aligner: Forced aligner to use.
        language: Project language.
        pad_s: Audio kept on each side of a line's coarse window.
        progress: Progress callback.
        cancel: Cancellation token.
        max_window_s: Longest window the aligner accepts, if it has a limit.
        features: Vocal features; used to notice that a window starts or ends mid-singing.

    Returns:
        For each line, one :class:`TokenTiming` per token.
    """
    duration = audio.size / MODEL_RATE
    before, after = _lock_bounds(lines)
    results: list[list[TokenTiming]] = []

    for line_index, (line, window) in enumerate(zip(lines, windows, strict=True)):
        cancel.raise_if_cancelled()
        low = max(0.0, window.start_s - pad_s)
        high = min(duration, window.end_s + pad_s)
        lower_bound = before[line_index]
        upper_bound = after[line_index]
        if lower_bound is not None:
            low = max(low, min(lower_bound, high))
        if upper_bound is not None:
            high = min(high, max(upper_bound, low))
        if max_window_s is not None and high - low > max_window_s:
            centre = (window.start_s + window.end_s) / 2.0
            low = max(low, centre - max_window_s / 2.0)
            high = min(high, low + max_window_s)

        # Context for aligners that cannot ignore foreign sound on their own: the tail of
        # the previous line / head of the next one, when their windows reach into this one.
        prefix: list[AlignUnit] = []
        suffix: list[AlignUnit] = []
        if line_index > 0 and (windows[line_index - 1].end_s > low or _voiced(features, low)):
            prefix = _units(lines[line_index - 1], from_end=True)
        if line_index + 1 < len(lines) and (
            windows[line_index + 1].start_s < high or _voiced(features, high)
        ):
            suffix = _units(lines[line_index + 1], from_end=False)

        timings: list[TokenTiming | None] = [None] * line.size
        for index in line.locked_indices:
            lock = line.locked[index]
            assert lock is not None
            timings[index] = TokenTiming(lock[0], lock[1], 1.0, locked=True)

        index = 0
        while index < line.size:
            if timings[index] is not None:
                index += 1
                continue
            run_end = index
            while run_end < line.size and timings[run_end] is None:
                run_end += 1
            left = timings[index - 1] if index > 0 else None
            right = timings[run_end] if run_end < line.size else None
            run_start = left.end_s if left is not None else low
            run_stop = right.start_s if right is not None else high
            if left is not None and right is not None and run_stop < run_start:
                run_start = run_stop = (run_start + run_stop) / 2.0
            run_stop = max(run_stop, run_start)
            aligned = _align_run(
                line,
                list(range(index, run_end)),
                run_start,
                run_stop,
                audio,
                aligner,
                language,
                open_start=left is None,
                open_end=right is None,
                prefix=prefix if left is None else (),
                suffix=suffix if right is None else (),
            )
            timings[index:run_end] = aligned
            index = run_end

        results.append([timing for timing in timings if timing is not None])
        progress((line_index + 1) / max(1, len(lines)), "逐字對齊 / aligning tokens")
    return results
