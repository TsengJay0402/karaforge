"""Pass 3 — refinement: turn raw aligner output into clean karaoke timing.

Steps, in order (locked tokens are never touched):

0. **Leaving silence.**  A token cannot start while nobody is singing.  A start that falls in
   a silent stretch moves forward to where the voice comes in, if that is soon enough (three
   seconds for the first tokens of a line, whose window begins with the pause before the
   line; one second inside a line) and still before the next line.
1. **Onset snapping.**  A token's start moves to the nearest detected vocal onset within
   ``onset_snap_ms``.  Aligners place boundaries on a coarse grid (20–80 ms) and with a
   systematic lag; the onset detector sees the actual rise of the sound.

   **Tokens without evidence.**  Sometimes the aligner's acoustic model does not hear a
   token at all (a syllable swallowed between two others, a held vowel) and merely squeezes
   it in next to a neighbour.  Such a token (score below ``weak_score``) is moved to the
   strongest onset between its neighbours that no other token has taken: the onset detector
   noticed that something started there even though the recogniser could not say what.
2. **Ordering.**  Starts are made strictly increasing with at least ``min_token_ms`` between
   them, within a line and across lines.
3. **End times.**  A token ends where the next one starts.  If the voice falls silent for
   longer than ``pause_threshold_ms`` before the next token, it ends where the energy drops
   instead, so the fill stops during the breath.
4. **Long notes.**  The last token of a line is held until the vocal energy fades (bounded by
   the next line and by ``max_tail_ms``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from karaforge.align.features import HOP_S, VocalFeatures
from karaforge.align.fine import TokenTiming

_LEADING_REACH_S = 3.0
"""How far ahead the first tokens of a line look for the voice to come in."""
_INNER_REACH_S = 1.0
"""The same for tokens inside a line (a breath between phrases)."""
_WEAK_REACH_S = 1.0
"""How far the first or last token of a line may move to reach an unclaimed onset."""


@dataclass(frozen=True)
class RefineSettings:
    """Parameters of the refinement pass (mirrors :class:`AlignSettings`)."""

    onset_snap: bool = True
    onset_snap_ms: int = 60
    weak_score: float = 0.0
    """Aligner score below which a token counts as placed without evidence (0 = never)."""
    min_token_ms: int = 60
    pause_threshold_ms: int = 300
    long_note: bool = True
    max_tail_ms: int = 6000


@dataclass
class RefinedToken:
    """Final timing of a token plus what the refinement did to it."""

    start_s: float
    end_s: float
    score: float
    locked: bool
    estimated: bool
    raw_start_s: float
    """Start time before refinement (the aligner's answer)."""
    snapped: bool = False
    rescued: bool = False
    """The aligner had no evidence for the token; it was placed on an unclaimed onset."""
    left_silence: bool = False
    """The start was moved out of a silent stretch."""
    onset_distance_s: float | None = None
    """Distance from the final start to the nearest detected onset."""


def _leave_silence(
    lines: list[list[RefinedToken]], features: VocalFeatures, duration_s: float
) -> None:
    """Move starts that fall into silence forward to the next moment the voice is active.

    Tokens at the beginning of a line may look further ahead than tokens inside a line: a
    line's window starts with the pause before it, and an aligner can leave more than one
    token there.  A token never moves past the start of the next line.
    """
    if features.frames == 0:
        return
    active = features.energy_db >= features.active_threshold_db
    for line_index, line in enumerate(lines):
        line_limit = next(
            (later[0].start_s for later in lines[line_index + 1 :] if later), duration_s
        )
        leading = True
        for token in line:
            if token.locked or token.estimated:
                leading = False
                continue
            first = features.frame_of(token.start_s)
            if active[first]:
                leading = False
                continue
            reach = _LEADING_REACH_S if leading else _INNER_REACH_S
            last = min(features.frames, round(min(line_limit, token.start_s + reach) / HOP_S))
            ahead = np.flatnonzero(active[first:last]) if last > first else np.zeros(0, np.int64)
            if ahead.size:
                token.start_s = (first + int(ahead[0])) * HOP_S
                token.left_silence = True
            else:
                leading = False


def _snap_starts(tokens: list[RefinedToken], features: VocalFeatures, limit_s: float) -> None:
    onsets = features.onsets_s
    if onsets.size == 0:
        return
    used_until = -1.0
    for token in tokens:
        if token.locked:
            used_until = max(used_until, token.start_s)
            continue
        position = int(np.searchsorted(onsets, token.start_s))
        candidates = [
            float(onsets[i])
            for i in (position - 1, position)
            if 0 <= i < onsets.size and abs(float(onsets[i]) - token.start_s) <= limit_s
        ]
        candidates = [onset for onset in candidates if onset > used_until + 1e-6]
        if candidates and not token.estimated:
            best = min(candidates, key=lambda onset: abs(onset - token.start_s))
            token.start_s = best
            token.snapped = True
        used_until = max(used_until, token.start_s)


def _place_weak_tokens(
    lines: list[list[RefinedToken]],
    features: VocalFeatures,
    weak_score: float,
    min_gap_s: float,
) -> None:
    """Move tokens the aligner had no evidence for onto unclaimed onsets.

    A weak token inside a line may go anywhere between its neighbours' starts.  The first
    token of a line may look back up to :data:`_WEAK_REACH_S` (not into the previous line),
    the last one forward by the same amount (not into the next line).  Among the onsets in
    that span that are not already the start of another token, the strongest wins; without
    such an onset the token stays where the aligner put it.
    """
    onsets, peaks = features.onsets_s, features.onset_peaks
    if onsets.size == 0 or weak_score <= 0.0:
        return
    taken = {round(token.start_s, 3) for line in lines for token in line if token.snapped}
    for line_index, line in enumerate(lines):
        previous_line_end = max(
            (token.start_s for earlier in lines[:line_index] for token in earlier[-1:]),
            default=0.0,
        )
        next_line_start = next(
            (later[0].start_s for later in lines[line_index + 1 :] if later), float("inf")
        )
        for index, token in enumerate(line):
            if token.locked or token.estimated or token.snapped or token.score >= weak_score:
                continue
            if index > 0:
                low = line[index - 1].start_s + min_gap_s
            else:
                low = max(previous_line_end + min_gap_s, token.start_s - _WEAK_REACH_S)
            if index + 1 < len(line):
                high = line[index + 1].start_s - min_gap_s
            else:
                high = min(next_line_start - min_gap_s, token.start_s + _WEAK_REACH_S)
            first = int(np.searchsorted(onsets, low, side="left"))
            last = int(np.searchsorted(onsets, high, side="right"))
            best: int | None = None
            for candidate in range(first, last):
                if round(float(onsets[candidate]), 3) in taken:
                    continue
                if best is None or peaks[candidate] > peaks[best]:
                    best = candidate
            if best is not None:
                token.start_s = float(onsets[best])
                token.rescued = True
                taken.add(round(token.start_s, 3))


def _enforce_order(tokens: list[RefinedToken], min_gap_s: float, duration_s: float) -> None:
    """Make starts increase by at least ``min_gap_s`` without moving locked tokens."""
    count = len(tokens)
    # Forward: push tokens later when they collide with their predecessor.
    for index in range(1, count):
        token, previous = tokens[index], tokens[index - 1]
        if not token.locked and token.start_s < previous.start_s + min_gap_s:
            token.start_s = previous.start_s + min_gap_s
            token.snapped = False
    # Backward: a locked (or the final) position may now be violated; pull tokens earlier.
    ceiling = duration_s
    for index in range(count - 1, -1, -1):
        token = tokens[index]
        if not token.locked and token.start_s > ceiling:
            token.start_s = max(0.0, ceiling)
            token.snapped = False
        ceiling = token.start_s - min_gap_s
    # Squeezed between two locked tokens that leave no room: spread evenly.
    for index in range(1, count):
        token, previous = tokens[index], tokens[index - 1]
        if not token.locked and token.start_s < previous.start_s:
            token.start_s = previous.start_s


def _silence_start(
    features: VocalFeatures, start_s: float, stop_s: float, min_silence_s: float
) -> float | None:
    """Start of the first quiet stretch of at least ``min_silence_s`` in ``[start_s, stop_s]``."""
    first = features.frame_of(start_s)
    last = min(features.frames, max(first + 1, round(stop_s / HOP_S)))
    need = max(1, round(min_silence_s / HOP_S))
    quiet = features.energy_db[first:last] < features.active_threshold_db
    run = 0
    for offset, flag in enumerate(quiet):
        run = run + 1 if flag else 0
        if run >= need:
            return (first + offset - run + 1) * HOP_S
    return None


def _energy_fade(features: VocalFeatures, start_s: float, stop_s: float) -> float:
    """Time at which the vocal energy fades after ``start_s`` (at most ``stop_s``).

    The note ends where the voice first stays quiet for 120 ms.  A token that starts where
    it is already quiet therefore ends at once, instead of being stretched across the pause
    up to the next line.
    """
    first = features.frame_of(start_s)
    last = min(features.frames, max(first + 1, round(stop_s / HOP_S)))
    quiet = features.energy_db[first:last] < features.active_threshold_db
    need = 12
    run = 0
    for offset, flag in enumerate(quiet):
        run = run + 1 if flag else 0
        if run >= need:
            return (first + offset - run + 1) * HOP_S
    return stop_s


def refine(
    lines: Sequence[Sequence[TokenTiming]],
    features: VocalFeatures,
    settings: RefineSettings,
    duration_s: float,
) -> list[list[RefinedToken]]:
    """Refine the fine-pass timings of all lines.

    Args:
        lines: Fine-pass output, one sequence of token timings per line.
        features: Features of the vocal stem.
        settings: Refinement parameters.
        duration_s: Length of the audio.

    Returns:
        Final token timings, same shape as ``lines``.
    """
    refined = [
        [
            RefinedToken(
                start_s=timing.start_s,
                end_s=timing.end_s,
                score=timing.score,
                locked=timing.locked,
                estimated=timing.estimated,
                raw_start_s=timing.start_s,
            )
            for timing in line
        ]
        for line in lines
    ]
    flat = [token for line in refined for token in line]
    min_gap = settings.min_token_ms / 1000.0

    _leave_silence(refined, features, duration_s)
    if settings.onset_snap:
        _snap_starts(flat, features, settings.onset_snap_ms / 1000.0)
        _place_weak_tokens(refined, features, settings.weak_score, min_gap)
    _enforce_order(flat, min_gap, duration_s)

    pause = settings.pause_threshold_ms / 1000.0
    max_tail = settings.max_tail_ms / 1000.0
    for line_index, line in enumerate(refined):
        next_line_start = next(
            (later[0].start_s for later in refined[line_index + 1 :] if later), duration_s
        )
        for index, token in enumerate(line):
            if token.locked:
                continue
            is_last = index == len(line) - 1
            if not is_last:
                following = line[index + 1].start_s
                end = following
                if features.frames and following - token.start_s > pause:
                    silence = _silence_start(features, token.start_s + min_gap, following, pause)
                    if silence is not None:
                        end = silence
            elif settings.long_note and features.frames:
                limit = min(next_line_start, token.start_s + max_tail, duration_s)
                end = max(token.start_s + min_gap, _energy_fade(features, token.start_s, limit))
                end = min(end, max(limit, token.start_s))
            else:
                end = min(max(token.end_s, token.start_s + min_gap), next_line_start, duration_s)
            token.end_s = max(token.start_s + min_gap * 0.5, min(end, duration_s))
            if not is_last:
                token.end_s = min(token.end_s, line[index + 1].start_s)
            token.end_s = max(token.end_s, token.start_s)

    onsets = features.onsets_s
    for token in flat:
        if onsets.size:
            token.onset_distance_s = float(np.min(np.abs(onsets - token.start_s)))
    return refined
