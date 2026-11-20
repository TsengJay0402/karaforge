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
any transcript match that contradicts them is dropped.  A line that came with a time from an
imported file (LRC, SRT, ASS) uses that time as its window and is not searched for at all.

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

WindowSource = Literal["asr", "anchor", "hint", "regions", "interpolated"]

_DEFAULT_TOKEN_S = 0.4
_MIN_TOKEN_S = 0.1
_MAX_TOKEN_S = 1.5
_MIN_REGION_PIECE_S = 0.25
_COLLAPSED_WORD_S = 0.02
_COLLAPSED_SPAN_S = 0.05
_COLLAPSED_RUN = 3
_PHRASE_GAP_S = 0.3
_BRIDGED_PAUSE_S = 0.5
"""A word that begins this long before a voice-activity region and ends inside it."""
_MAX_WORD_S = 0.6
"""Longest plausible duration per token of a phrase-initial recognised word."""
_HINT_QUALITY = 0.8
_HINT_SLACK_S = 2.0
_SOURCE_RANK: dict[str, int] = {"anchor": 2, "hint": 1}


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
    hint: tuple[float, float | None] | None = None
    """``(start_s, end_s)`` of the line from an imported file with line-level timing."""

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
    anchors_use_transcript: bool = True
    """A line with locked tokens takes its window from the locks *and* the recognised tokens
    that agree with them.  ``False`` uses the locks alone (algorithm version 7), which
    replaces a good window by a guess from the token count as soon as one token is locked."""


def _letter_sequence(lines: Sequence[LyricLine]) -> tuple[str, list[tuple[int, int]]]:
    letters: list[str] = []
    owners: list[tuple[int, int]] = []
    for line_index, line in enumerate(lines):
        for token_index, reading in enumerate(line.readings):
            for letter in reading:
                letters.append(letter)
                owners.append((line_index, token_index))
    return "".join(letters), owners


def _token_count(text: str) -> int:
    return max(1, sum(1 for token in tokenize(text) if token.core))


def drop_collapsed_words(words: Sequence[AsrWord]) -> list[AsrWord]:
    """Remove runs of recognised words that all sit on one instant.

    When a recogniser invents text (typically a copy of the lyrics it was primed with), its
    word timing has nothing to hold on to and several words in a row come out with no
    duration at the same timestamp.  Three or more such words are physically impossible and
    are discarded; they would otherwise anchor a lyric line to a place where it is not sung.
    """
    kept: list[AsrWord] = []
    index = 0
    while index < len(words):
        stop = index
        while (
            stop < len(words)
            and words[stop].end_s - words[stop].start_s <= _COLLAPSED_WORD_S
            and words[stop].start_s - words[index].start_s <= _COLLAPSED_SPAN_S
        ):
            stop += 1
        if stop - index >= _COLLAPSED_RUN:
            index = stop
            continue
        kept.append(words[index])
        index += 1
    return kept


def clean_words(
    words: Sequence[AsrWord], regions: Sequence[tuple[float, float]], reach_s: float = 4.0
) -> list[AsrWord]:
    """Repair the typical defects of recognised word times before they are used as anchors.

    1. Collapsed runs are dropped (:func:`drop_collapsed_words`).
    2. A word that *spans a pause* — it starts in at least half a second of silence and a
       voice-activity region begins before it ends — was dragged back across that pause; it
       starts where the region starts.
    3. The first word after a gap in the transcript is where recognisers are least reliable:

       * If it starts where nobody is singing and no other word lies between it and the next
         voice-activity region, it is moved to the start of that region.
       * Otherwise, if it is implausibly long, only its *end* is trusted and the start is
         pulled up to a normal word length before the end.

       Other words are left alone even when the voice-activity detector says "silence"
       there — a run of consistently timed words is better evidence than the detector,
       which misses quiet singing in a noisy mix.
    4. A word without duration takes the start of the word after it.
    """
    kept = drop_collapsed_words(words)
    starts = [region[0] for region in regions]
    result: list[AsrWord] = []
    previous_end: float | None = None
    for index, word in enumerate(kept):
        following = kept[index + 1].start_s if index + 1 < len(kept) else None
        phrase_initial = previous_end is None or word.start_s - previous_end >= _PHRASE_GAP_S
        if word.end_s - word.start_s > _COLLAPSED_WORD_S:
            previous_end = word.end_s
        start, end = word.start_s, word.end_s
        bridged = [
            low
            for low in starts
            if start + _BRIDGED_PAUSE_S <= low <= end
            and not any(a < low and b > start for a, b in regions if a != low)
        ]
        if bridged:
            start = bridged[-1]
            end = max(end, start + 0.05)
        elif phrase_initial:
            limit = _MAX_WORD_S * _token_count(word.text)
            in_voice = any(low - 0.05 <= start <= high for low, high in regions)
            region = next((low for low in starts if low >= start), None)
            if (
                not in_voice
                and region is not None
                and region - start <= reach_s
                and (following is None or following >= region - 0.05)
            ):
                length = min(max(end - start, 0.05), limit)
                start, end = region, region + length
            elif end - start > limit:
                start = end - limit
        result.append(AsrWord(word.text, start, max(end, start), word.probability))
    # Words without duration lean on the word after them.
    for index in range(len(result) - 2, -1, -1):
        word, later = result[index], result[index + 1]
        if word.end_s - word.start_s <= _COLLAPSED_WORD_S and later.start_s > word.start_s:
            result[index] = AsrWord(word.text, later.start_s, later.start_s, word.probability)
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


def _anchor_window(line: LyricLine, hits: list[tuple[int, float]]) -> LineWindow:
    """Window of a line that has locked tokens, from ``hits`` (the locks and what agrees)."""
    start, end = _window_from_hits(line, hits)
    last = line.locked[line.size - 1] if line.size else None
    if last is not None:
        end = last[1]
    return LineWindow(start, max(end, start), 1.0, "anchor")


def _agrees(
    position: int, time_s: float, locks: Sequence[tuple[int, float]], max_gap_s: float
) -> bool:
    """Whether a recognised token time is compatible with every locked token of its line.

    It has to lie on the right side of each lock, and no further from it than tokens can
    plausibly be apart (the same allowance as between two recognised tokens).
    """
    for lock_position, lock_time in locks:
        distance = (time_s - lock_time) if position > lock_position else (lock_time - time_s)
        allowed = max(max_gap_s, 1.5 * abs(position - lock_position) + 2.0)
        if not 0.0 <= distance <= allowed:
            return False
    return True


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
    lock_hits: dict[int, list[tuple[int, float]]] = {}
    for index, line in enumerate(lines):
        locked = line.locked_indices
        if not locked:
            continue
        lock_hits[index] = [
            (position, lock[0])
            for position in locked
            if (lock := line.locked[position]) is not None
        ]
        windows[index] = _anchor_window(line, lock_hits[index])

    # ---- line times of an imported file
    for index, line in enumerate(lines):
        if windows[index] is not None or line.hint is None:
            continue
        start, end = line.hint
        if end is None:
            end = start + max(_HINT_SLACK_S, line.size * _DEFAULT_TOKEN_S * 1.5)
        # A file's line often "lasts" until the next line starts, interlude included; the
        # line itself cannot be longer than its tokens sung very slowly.
        end = min(end, start + line.size * _MAX_TOKEN_S + _HINT_SLACK_S)
        windows[index] = LineWindow(start, max(end, start), _HINT_QUALITY, "hint")

    # ---- transcript matching
    lyric_letters, owners = _letter_sequence(lines)
    asr_letters, asr_times = transcript_letters(clean_words(words, regions))
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

    if transcript_usable and config.anchors_use_transcript:
        # A locked token says where *it* is; where the rest of its line is, the transcript
        # still knows better than a guess from the token count.  The line's window therefore
        # comes from the locks together with every recognised token that agrees with them.
        for index, locks in lock_hits.items():
            line = lines[index]
            agreeing = [
                (position, hint)
                for position, reading in enumerate(line.readings)
                if reading
                and line.locked[position] is None
                and (hint := hints[index][position]) is not None
                and matched_equal[index][position] * 2 >= len(reading)
                and _agrees(position, hint, locks, config.max_hit_gap_s)
            ]
            merged: list[tuple[int, float]] = []
            for hit in sorted([*locks, *agreeing]):
                if not merged or hit[1] >= merged[-1][1] or line.locked[hit[0]] is not None:
                    merged.append(hit)
            if len(merged) > len(locks):
                windows[index] = _anchor_window(line, merged)

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
    """Remove windows that contradict the order of the lines.

    Locked anchors win over imported line times, which win over transcript matches; between
    two transcript matches the better-matched line stays.
    """
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
                    rank = _SOURCE_RANK.get(window.source, 0)
                    previous_rank = _SOURCE_RANK.get(previous.source, 0)
                    if rank > previous_rank:
                        loser = previous_index
                    elif previous_rank > rank:
                        loser = index
                    elif rank > 0:
                        # Two user-given times that disagree: keep both as they are.
                        previous_index = index
                        continue
                    else:
                        loser = index if window.quality <= previous.quality else previous_index
                    windows[loser] = None
                    changed = True
                    break
            previous_index = index
    del lines
