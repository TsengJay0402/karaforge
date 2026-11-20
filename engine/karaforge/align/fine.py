"""Pass 2 — fine alignment: place every token of a line inside the line's window.

Each line is aligned on its own, in its coarse window padded by about a second on each side.
Locked tokens split a line into independent runs: a run between two locked tokens is aligned
only within the time between them, so a user's correction acts as a hard constraint for
everything around it.

Answers are remembered per request (same aligner, same stretch of the same audio, same
tokens).  When the user locks a few tokens and re-aligns, only the runs whose boundaries
changed go to the model again; everything else is answered from memory.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass

from karaforge.adapters.base import Aligner, AlignRequest, AlignUnit, UnitTiming
from karaforge.align.coarse import LineWindow, LyricLine
from karaforge.align.features import VocalFeatures
from karaforge.audio.io import MODEL_RATE, FloatArray
from karaforge.runtime import CancelToken, ProgressFn

_MIN_RUN_S_PER_TOKEN = 0.03
_ANCHOR_TAIL_S = 0.3
"""Audio kept after the start of a locked token that follows a run, so that the aligner
hears enough of it to recognise it even when the token is very short."""
_MEMO_SIZE = 4096
_memo: OrderedDict[tuple[object, ...], list[UnitTiming]] = OrderedDict()
_memo_lock = threading.Lock()


def clear_memo() -> None:
    """Forget all remembered aligner answers."""
    with _memo_lock:
        _memo.clear()


def _ask(aligner: Aligner, request: AlignRequest, audio_key: str) -> list[UnitTiming]:
    """``aligner.align(request)``, answered from memory when the same question was asked."""
    info = aligner.info
    key: tuple[object, ...] = (
        info.tag,
        info.models,
        audio_key,
        request.offset_s,
        request.audio.size,
        request.language,
        request.open_start,
        request.open_end,
        tuple((unit.text, unit.reading) for unit in request.units),
        tuple((unit.text, unit.reading) for unit in request.prefix_units),
        tuple((unit.text, unit.reading) for unit in request.suffix_units),
    )
    with _memo_lock:
        known = _memo.get(key)
        if known is not None:
            _memo.move_to_end(key)
            return list(known)
    answer = aligner.align(request)
    with _memo_lock:
        _memo[key] = list(answer)
        while len(_memo) > _MEMO_SIZE:
            _memo.popitem(last=False)
    return answer


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


def _units(line: LyricLine, *, from_end: bool, count: int) -> list[AlignUnit]:
    """A few pronounceable tokens from the end (or the start) of a line, as context."""
    indices = [index for index in range(line.size) if line.cores[index]]
    if count <= 0:
        return []
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


def _unit(line: LyricLine, index: int) -> AlignUnit:
    return AlignUnit(
        text=line.cores[index], kind=line.kinds[index], reading=line.readings[index] or None
    )


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
    audio_key: str = "",
    lead: AlignUnit | None = None,
    trail: AlignUnit | None = None,
    floor_s: float | None = None,
    ceiling_s: float | None = None,
) -> list[TokenTiming]:
    """Align the tokens ``indices`` of ``line`` inside the audio ``[start_s, end_s]``.

    Args:
        line: The line the tokens belong to.
        indices: The tokens to align (a run of unlocked tokens).
        start_s: Start of the audio given to the aligner.
        end_s: End of that audio.
        audio: The whole vocal stem.
        aligner: The forced aligner.
        language: Project language.
        open_start: The audio may begin with sound that belongs to none of the units.
        open_end: The same for its end.
        prefix: Context units of the previous line.
        suffix: Context units of the next line.
        audio_key: Identifies ``audio`` for the memo of aligner answers.
        lead: A locked token directly before the run.  It is aligned together with the run —
            the audio then starts where that token starts — and its timing is thrown away.
        trail: A locked token directly after the run, likewise.
        floor_s: Earliest time a token of the run may get (default ``start_s``).
        ceiling_s: Latest time (default ``end_s``).
    """
    floor = start_s if floor_s is None else floor_s
    ceiling = end_s if ceiling_s is None else ceiling_s
    ceiling = max(ceiling, floor)
    voiced = [index for index in indices if line.cores[index]]
    if not voiced or ceiling - floor < _MIN_RUN_S_PER_TOKEN * len(voiced):
        return [
            TokenTiming(low, high, 0.0, estimated=True)
            for low, high in _spread(floor, ceiling, len(indices))
        ]
    first_sample = max(0, round(start_s * MODEL_RATE))
    last_sample = min(audio.size, round(end_s * MODEL_RATE))
    units = [_unit(line, index) for index in voiced]
    request = AlignRequest(
        audio=audio[first_sample:last_sample],
        units=[*([lead] if lead else []), *units, *([trail] if trail else [])],
        language=language,
        open_start=open_start,
        open_end=open_end,
        prefix_units=prefix,
        suffix_units=suffix,
        offset_s=first_sample / MODEL_RATE,
    )
    timings = _ask(aligner, request, audio_key) if audio_key else aligner.align(request)
    timings = list(timings)[(1 if lead else 0) : len(timings) - (1 if trail else 0)]
    offset = first_sample / MODEL_RATE
    by_index = {
        index: TokenTiming(
            start_s=min(ceiling, max(floor, offset + timing.start_s)),
            end_s=min(ceiling, max(floor, offset + timing.end_s)),
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
        anchor = following.start_s if following is not None else ceiling
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
    context_tokens: int = 4,
    anchor_context: bool = True,
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
        context_tokens: Tokens of the neighbouring lines passed to the aligner as context.
        anchor_context: Align the tokens next to a locked token together with that token
            (see ``AlignSettings.anchor_context``).

    Returns:
        For each line, one :class:`TokenTiming` per token.
    """
    duration = audio.size / MODEL_RATE
    before, after = _lock_bounds(lines)
    results: list[list[TokenTiming]] = []
    prepare = getattr(aligner, "prepare", None)
    if callable(prepare):
        prepare(audio)
    audio_key = hashlib.blake2b(audio.tobytes(), digest_size=16).hexdigest()

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

        # Is there sound in the padded window that belongs to a neighbouring line?  That is
        # the case when the neighbour's own window reaches into this one, or when somebody
        # is singing right at the window's edge.  Aligners are told (``open_start`` /
        # ``open_end``) and given the neighbour's nearest tokens as context.
        foreign_before = line_index > 0 and (
            windows[line_index - 1].end_s > low or _voiced(features, low)
        )
        foreign_after = line_index + 1 < len(lines) and (
            windows[line_index + 1].start_s < high or _voiced(features, high)
        )
        prefix: list[AlignUnit] = []
        suffix: list[AlignUnit] = []
        if foreign_before:
            prefix = _units(lines[line_index - 1], from_end=True, count=context_tokens)
        if foreign_after:
            suffix = _units(lines[line_index + 1], from_end=False, count=context_tokens)

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
            # A locked neighbour is aligned together with the run instead of cutting the
            # audio at its edge: an aligner needs to hear whole syllables, and where the
            # user says a token starts is firmer knowledge than where it ends.
            lead = trail = None
            audio_start, audio_stop = run_start, run_stop
            floor = run_start
            if anchor_context and left is not None and line.cores[index - 1]:
                lead = _unit(line, index - 1)
                audio_start = left.start_s
                floor = left.start_s + _MIN_RUN_S_PER_TOKEN
            if anchor_context and right is not None and line.cores[run_end]:
                trail = _unit(line, run_end)
                audio_stop = min(duration, max(right.end_s, right.start_s + _ANCHOR_TAIL_S))
            if max_window_s is not None and audio_stop - audio_start > max_window_s:
                lead = trail = None
                audio_start, audio_stop, floor = run_start, run_stop, run_start
            if lead is None and trail is None and left is not None and right is not None:
                # Cut at both locks: when they overlap, the run gets the instant in between.
                if run_stop < run_start:
                    run_start = run_stop = (run_start + run_stop) / 2.0
                audio_start, audio_stop, floor = run_start, run_stop, run_start
            ceiling = max(run_stop, floor) if lead is None else run_stop
            audio_stop = max(audio_stop, audio_start)
            aligned = _align_run(
                line,
                list(range(index, run_end)),
                audio_start,
                audio_stop,
                audio,
                aligner,
                language,
                open_start=left is None and foreign_before,
                open_end=right is None and foreign_after,
                prefix=prefix if left is None else (),
                suffix=suffix if right is None else (),
                audio_key=audio_key,
                lead=lead,
                trail=trail,
                floor_s=floor,
                ceiling_s=ceiling,
            )
            timings[index:run_end] = aligned
            index = run_end

        results.append([timing for timing in timings if timing is not None])
        progress((line_index + 1) / max(1, len(lines)), "逐字對齊 / aligning tokens")
    return results
