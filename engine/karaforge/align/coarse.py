"""Pass 1 — coarse alignment: anchor every lyric line to a time window.

The vocal stem is transcribed by a speech recogniser with word timestamps.  The recognised
text is usually *wrong in detail* on singing — homophones, dropped words, the occasional
hallucination — but right often enough to say roughly *when* each line is sung.  To use it:

1. Lyrics and transcript are both romanised to plain letters (see
   :mod:`karaforge.text.romanize`), so 請請慢慢聊起來 still matches 星星慢慢亮起來 in most
   positions and Chinese needs no word boundaries.
2. A global edit-distance alignment between the two letter sequences pairs lyric letters with
   recognised letters, and through them with times.
3. Each line takes its window from the densest run of its matched tokens.  Lines with too few
   matches are *not* guessed from the transcript; they are laid out afterwards between their
   anchored neighbours, following voice-activity regions in proportion to their token counts.

Locked tokens (corrected by the user) are exact anchors: their line is placed from them and
any transcript match that contradicts them is dropped.

The point of this pass is to stop errors from accumulating: every line gets its own window,
so a problem in one line cannot shift the lines after it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from rapidfuzz.distance import Levenshtein

from karaforge.adapters.base import AsrWord
from karaforge.text.romanize import romanize_tokens
from karaforge.text.tokenize import TokenKind, tokenize

WindowSource = Literal["asr", "anchor", "regions", "interpolated"]

_DEFAULT_TOKEN_S = 0.4
_MIN_TOKEN_S = 0.1
_MAX_TOKEN_S = 1.5
_MIN_REGION_PIECE_S = 0.25


@dataclass(frozen=True)
class LyricLine:
    """A lyric line as the alignment passes see it."""

    id: str
    cores: tuple[str, ...]
    kinds: tuple[TokenKind, ...]
    readings: tuple[str, ...]
    """Romanised reading per token; empty when the token has nothing pronounceable."""
    locked: tuple[tuple[float, float] | None, ...]
    """``(start_s, end_s)`` for tokens locked by the user, ``None`` for the others."""

    @property
    def size(self) -> int:
        """Number of tokens."""
        return len(self.cores)

    @property
    def locked_indices(self) -> list[int]:
        """Indices of locked tokens."""
        return [index for index, value in enumerate(self.locked) if value is not None]


@dataclass
class LineWindow:
    """Where a line is expected to be sung."""

    start_s: float
    end_s: float
    quality: float
    """Share of the line's letters that the transcript confirmed (1.0 for locked anchors)."""
    source: WindowSource
    token_hints: list[float | None] = field(default_factory=list[float | None])
    """Approximate start per token derived from the transcript, where available."""


@dataclass(frozen=True)
class CoarseSettings:
    """Tunable thresholds of the coarse pass."""

    min_line_quality: float = 0.34
    """Below this share of matched letters a line is not anchored from the transcript."""
    min_global_quality: float = 0.15
    """Below this overall share the transcript is ignored altogether."""
    max_hit_gap_s: float = 4.0
    """Matched tokens of one line further apart than this belong to different runs."""


def _letter_sequence(lines: Sequence[LyricLine]) -> tuple[str, list[tuple[int, int]]]:
    letters: list[str] = []
    owners: list[tuple[int, int]] = []
    for line_index, line in enumerate(lines):
        for token_index, reading in enumerate(line.readings):
            for letter in reading:
                letters.append(letter)
                owners.append((line_index, token_index))
    return "".join(letters), owners


def move_words_out_of_silence(
    words: Sequence[AsrWord], regions: Sequence[tuple[float, float]], reach_s: float = 4.0
) -> list[AsrWord]:
    """Correct recognised words whose timestamp falls where nobody is singing.

    Recognisers tend to stretch the first word after a pause back into the pause.  A word
    that starts outside every voice-activity region is moved to the start of the next region
    (if one begins within ``reach_s``); its duration is kept.
    """
    if not regions:
        return list(words)
    starts = [region[0] for region in regions]
    result: list[AsrWord] = []
    for word in words:
        inside = any(start - 0.05 <= word.start_s <= end for start, end in regions)
        if not inside:
            following = next((start for start in starts if start >= word.start_s), None)
            if following is not None and following - word.start_s <= reach_s:
                shift = following - word.start_s
                word = AsrWord(word.text, following, word.end_s + shift, word.probability)
        result.append(word)
    return result


def transcript_letters(words: Sequence[AsrWord]) -> tuple[str, list[float]]:
    """Romanise recognised words into letters, each with an interpolated time."""
    letters: list[str] = []
    times: list[float] = []
    for word in words:
        tokens = [token for token in tokenize(word.text) if token.core]
        if not tokens:
            continue
        readings = romanize_tokens([t.core for t in tokens], [t.kind for t in tokens])
        joined = "".join(readings)
        if not joined:
            continue
        span = max(0.0, word.end_s - word.start_s)
        for position, letter in enumerate(joined):
            letters.append(letter)
            times.append(word.start_s + span * position / len(joined))
    return "".join(letters), times


def _densest_run(hits: list[tuple[int, float]], max_gap_s: float) -> list[tuple[int, float]]:
    """Longest run of ``(token_index, time)`` hits without a large time gap."""
    if not hits:
        return []
    best: list[tuple[int, float]] = []
    current: list[tuple[int, float]] = [hits[0]]
    for hit in hits[1:]:
        previous = current[-1]
        allowed = max(max_gap_s, 1.5 * (hit[0] - previous[0]) + 2.0)
        if 0.0 <= hit[1] - previous[1] <= allowed:
            current.append(hit)
        else:
            if len(current) > len(best):
                best = current
            current = [hit]
    return current if len(current) > len(best) else best


def _window_from_hits(line: LyricLine, hits: list[tuple[int, float]]) -> tuple[float, float]:
    first_index, first_time = hits[0]
    last_index, last_time = hits[-1]
    if last_index > first_index:
        per_token = (last_time - first_time) / (last_index - first_index)
        per_token = float(np.clip(per_token, _MIN_TOKEN_S, _MAX_TOKEN_S))
    else:
        per_token = _DEFAULT_TOKEN_S
    start = first_time - first_index * per_token
    end = last_time + (line.size - last_index) * per_token
    return start, end


def _clip_regions(
    regions: Sequence[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    # A region that merely pokes into the interval (the tail of the previous line or the head
    # of the next one, whose window edges are only estimates) is not a place to put a line.
    clipped: list[tuple[float, float]] = []
    for region_start, region_end in regions:
        low, high = max(region_start, start), min(region_end, end)
        if high - low >= _MIN_REGION_PIECE_S:
            clipped.append((low, high))
    return clipped


def distribute_lines(
    sizes: Sequence[int],
    regions: Sequence[tuple[float, float]],
    start: float,
    end: float,
) -> list[tuple[float, float, WindowSource]]:
    """Lay lines out inside ``[start, end]`` when the transcript gives no anchor for them.

    When there are exactly as many voice-activity regions as lines, each line takes one
    region.  Otherwise the voiced time is shared in proportion to the lines' token counts;
    without any voiced time the interval itself is shared.
    """
    if not sizes:
        return []
    voiced = _clip_regions(regions, start, end)
    if len(voiced) == len(sizes):
        return [(low, high, "regions") for low, high in voiced]
    total_tokens = float(sum(max(1, size) for size in sizes))
    if not voiced:
        span = max(0.0, end - start)
        result: list[tuple[float, float, WindowSource]] = []
        cursor = start
        for size in sizes:
            share = span * max(1, size) / total_tokens
            result.append((cursor, cursor + share, "interpolated"))
            cursor += share
        return result

    voiced_total = sum(high - low for low, high in voiced)

    def to_time(position: float) -> float:
        remaining = position
        for low, high in voiced:
            length = high - low
            if remaining <= length:
                return low + remaining
            remaining -= length
        return voiced[-1][1]

    result = []
    cursor = 0.0
    for size in sizes:
        share = voiced_total * max(1, size) / total_tokens
        line_start = to_time(cursor + 1e-6)
        line_end = to_time(cursor + share)
        result.append((line_start, max(line_end, line_start), "interpolated"))
        cursor += share
    return result


def coarse_align(
    lines: Sequence[LyricLine],
    words: Sequence[AsrWord],
    regions: Sequence[tuple[float, float]],
    duration_s: float,
    settings: CoarseSettings | None = None,
) -> list[LineWindow]:
    """Compute a time window for every line.

    Args:
        lines: The lyric lines in singing order.
        words: Recognised words with timestamps (may be empty).
        regions: Voice-activity regions of the vocal stem.
        duration_s: Length of the audio.
        settings: Thresholds; defaults are used when omitted.

    Returns:
        One window per line, with non-decreasing start times.
    """
    config = settings or CoarseSettings()
    count = len(lines)
    windows: list[LineWindow | None] = [None] * count
    hints: list[list[float | None]] = [[None] * line.size for line in lines]

    # ---- locked tokens are exact anchors
    for index, line in enumerate(lines):
        locked = line.locked_indices
        if not locked:
            continue
        hits = [
            (position, lock[0])
            for position in locked
            if (lock := line.locked[position]) is not None
        ]
        start, end = _window_from_hits(line, hits)
        last_lock = line.locked[locked[-1]]
        if last_lock is not None and locked[-1] == line.size - 1:
            end = last_lock[1]
        windows[index] = LineWindow(start, max(end, start), 1.0, "anchor")

    # ---- transcript matching
    lyric_letters, owners = _letter_sequence(lines)
    asr_letters, asr_times = transcript_letters(move_words_out_of_silence(words, regions))
    matched_equal = [[0] * line.size for line in lines]
    if lyric_letters and asr_letters:
        for op in Levenshtein.opcodes(lyric_letters, asr_letters):
            if op.tag not in ("equal", "replace"):
                continue
            length = min(op.src_end - op.src_start, op.dest_end - op.dest_start)
            for offset in range(length):
                line_index, token_index = owners[op.src_start + offset]
                if hints[line_index][token_index] is None:
                    hints[line_index][token_index] = asr_times[op.dest_start + offset]
                if op.tag == "equal":
                    matched_equal[line_index][token_index] += 1

    total_letters = len(lyric_letters)
    total_matched = sum(sum(row) for row in matched_equal)
    transcript_usable = (
        total_letters > 0 and total_matched / total_letters >= config.min_global_quality
    )

    if transcript_usable:
        for index, line in enumerate(lines):
            if windows[index] is not None:
                continue
            letters = sum(len(reading) for reading in line.readings)
            if letters == 0:
                continue
            quality = sum(matched_equal[index]) / letters
            hits: list[tuple[int, float]] = []
            for position, reading in enumerate(line.readings):
                hint = hints[index][position]
                if (
                    reading
                    and hint is not None
                    and matched_equal[index][position] * 2 >= len(reading)
                ):
                    hits.append((position, hint))
            run = _densest_run(hits, config.max_hit_gap_s)
            if quality < config.min_line_quality or len(run) < min(2, line.size):
                continue
            start, end = _window_from_hits(line, run)
            windows[index] = LineWindow(start, max(end, start), quality, "asr")

    _drop_out_of_order(windows, lines)

    # ---- lines without an anchor are laid out between their neighbours
    index = 0
    while index < count:
        if windows[index] is not None:
            index += 1
            continue
        run_end = index
        while run_end < count and windows[run_end] is None:
            run_end += 1
        previous = windows[index - 1] if index > 0 else None
        following = windows[run_end] if run_end < count else None
        low = previous.end_s if previous is not None else 0.0
        high = following.start_s if following is not None else duration_s
        if high < low:
            low = high = (low + high) / 2.0
        placed = distribute_lines(
            [lines[i].size for i in range(index, run_end)], regions, low, high
        )
        for offset, (start, end, source) in enumerate(placed):
            windows[index + offset] = LineWindow(start, end, 0.0, source)
        index = run_end

    result: list[LineWindow] = []
    for index, window in enumerate(windows):
        assert window is not None
        window.start_s = float(np.clip(window.start_s, 0.0, duration_s))
        window.end_s = float(np.clip(window.end_s, window.start_s, duration_s))
        window.token_hints = hints[index] if transcript_usable else [None] * lines[index].size
        result.append(window)
    return result


def _drop_out_of_order(windows: list[LineWindow | None], lines: Sequence[LyricLine]) -> None:
    """Remove transcript anchors that contradict the order of the lines or a locked anchor."""
    changed = True
    while changed:
        changed = False
        previous_index: int | None = None
        for index, window in enumerate(windows):
            if window is None:
                continue
            if previous_index is not None:
                previous = windows[previous_index]
                assert previous is not None
                if window.start_s < previous.start_s - 0.05:
                    # Keep locked anchors; otherwise keep the better-matched line.
                    if window.source == "anchor" and previous.source != "anchor":
                        loser = previous_index
                    elif previous.source == "anchor" and window.source != "anchor":
                        loser = index
                    elif window.source == "anchor":
                        previous_index = index
                        continue
                    else:
                        loser = index if window.quality <= previous.quality else previous_index
                    windows[loser] = None
                    changed = True
                    break
            previous_index = index
    del lines
