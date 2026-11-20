"""Lyric draft from a transcript: the "no lyrics" flow.

When a project has no lyrics, the recognised words become its first lyrics.  The transcript
is cleaned of what was not sung, written in the script of the project language, cut into
lines where the singer pauses, and every token gets the recogniser's rough time.  The result
is a *draft*: it is meant to be proofread, and it goes through the same alignment as lyrics
that were typed in.

Everything here is pure (no audio, no models), so it is tested with hand-made transcripts.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

from karaforge.adapters.base import AsrWord, Transcript
from karaforge.align.coarse import drop_collapsed_words
from karaforge.project.schema import Line, Token
from karaforge.text.script import convert_script
from karaforge.text.tokenize import is_han, is_hangul, is_kana, tokenize

_ANNOTATION = re.compile(r"[\[(（【〔<＜][^\])）】〕>＞]*[\])）】〕>＞]")
"""Recognisers describe non-speech in brackets: ``[Music]``, ``(音樂)``."""
_APOSTROPHES = frozenset("'’")
"""Kept next to a letter: ``don't``, ``believin'``, ``'cause``."""
_HYPHENS = frozenset("-‐")
"""Kept between two letters: ``sing-along``."""


@dataclass(frozen=True)
class DraftSettings:
    """How a transcript is cut into lines."""

    line_gap_s: float = 0.7
    """A pause at least this long between two words ends the line."""
    paragraph_gap_s: float = 4.0
    """A pause at least this long between two lines starts a new paragraph."""
    max_width: float = 16.0
    """Longest line, measured in CJK characters (a Latin letter counts as half of one)."""
    min_width: float = 3.0
    """Lines shorter than this are joined to a neighbour when no real pause separates them."""
    region_slack_s: float = 0.5
    """How far outside the detected singing a recognised phrase may lie before it is dropped."""


@dataclass(frozen=True)
class DraftToken:
    """One token of the draft with its rough time."""

    text: str
    start_s: float
    end_s: float
    probability: float


@dataclass(frozen=True)
class DraftLine:
    """One line of the draft."""

    text: str
    tokens: tuple[DraftToken, ...]
    start_s: float
    end_s: float
    paragraph: int


@dataclass(frozen=True)
class _Word:
    """A recognised word after cleaning."""

    text: str
    start_s: float
    end_s: float
    probability: float
    segment: int


def _is_cjk(char: str) -> bool:
    return is_han(char) or is_kana(char) or is_hangul(char)


def clean_text(text: str, language: str) -> str:
    """Reduce recognised text to what a lyric sheet would show.

    Bracketed annotations and all punctuation and symbols go (apostrophes next to a letter
    and hyphens inside a word stay), the text is written in the script of ``language`` and
    runs of whitespace collapse.  Lyrics conventionally separate phrases by spaces and line
    breaks rather than by punctuation, and a recogniser's punctuation is a guess anyway.
    """
    text = unicodedata.normalize("NFC", _ANNOTATION.sub(" ", text))

    def latin(position: int) -> bool:
        return (
            0 <= position < len(text) and text[position].isalnum() and not _is_cjk(text[position])
        )

    kept: list[str] = []
    for index, char in enumerate(text):
        category = unicodedata.category(char)
        if category[0] in "PS":
            if char in _APOSTROPHES:
                keep = latin(index - 1) or latin(index + 1)
            else:
                keep = char in _HYPHENS and latin(index - 1) and latin(index + 1)
            kept.append(char if keep else " ")
        elif category[0] == "C":
            kept.append(" ")
        else:
            kept.append(char)
    return convert_script(" ".join("".join(kept).split()), language)


def _overlaps(
    start_s: float, end_s: float, regions: Sequence[tuple[float, float]], slack: float
) -> bool:
    return any(start_s <= stop + slack and end_s >= begin - slack for begin, stop in regions)


def usable_words(
    transcript: Transcript,
    language: str,
    regions: Sequence[tuple[float, float]] = (),
    settings: DraftSettings | None = None,
) -> list[_Word]:
    """The recognised words that are worth showing as lyrics.

    Dropped are: words that all sit on one instant (invented text, see
    :func:`~karaforge.align.coarse.drop_collapsed_words`), words without anything to sing,
    and whole phrases that lie where nobody sings — recognisers fill silence with stock
    sentences.  The last rule only applies when voice-activity regions are known.
    """
    settings = settings or DraftSettings()
    segment_of: dict[int, int] = {}
    flat: list[AsrWord] = []
    for index, segment in enumerate(transcript.segments):
        if regions and not _overlaps(
            segment.start_s, segment.end_s, regions, settings.region_slack_s
        ):
            continue
        for word in segment.words:
            segment_of[id(word)] = index
            flat.append(word)
    words: list[_Word] = []
    for word in drop_collapsed_words(flat):
        text = clean_text(word.text, language)
        if not any(piece.core for piece in tokenize(text)):
            continue
        start = max(0.0, word.start_s)
        words.append(
            _Word(text, start, max(start, word.end_s), word.probability, segment_of[id(word)])
        )
    return words


def _width(text: str) -> float:
    """Display width in CJK characters."""
    return sum(1.0 if _is_cjk(char) else 0.5 for char in text if not char.isspace())


def _line_width(words: Sequence[_Word]) -> float:
    # A space between two words costs about half a character.
    spaces = sum(_needs_space(first.text, second.text) for first, second in pairwise(words))
    return sum(_width(word.text) for word in words) + 0.5 * spaces


def _needs_space(before: str, after: str) -> bool:
    """Whether two adjacent words are written apart (everything but CJK next to CJK)."""
    return not (_is_cjk(before[-1]) and _is_cjk(after[0]))


def _wrap(words: list[_Word], settings: DraftSettings) -> list[list[_Word]]:
    """Cut an over-long line at its longest pause (near the middle when pauses are equal)."""
    if len(words) < 2 or _line_width(words) <= settings.max_width:
        return [words]
    middle = (len(words) - 1) / 2
    candidates = [
        index
        for index in range(1, len(words))
        if _line_width(words[:index]) >= settings.min_width
        and _line_width(words[index:]) >= settings.min_width
    ] or list(range(1, len(words)))
    cut = max(
        candidates,
        key=lambda index: (
            round(words[index].start_s - words[index - 1].end_s, 2),
            -abs(index - 0.5 - middle),
        ),
    )
    return _wrap(words[:cut], settings) + _wrap(words[cut:], settings)


def split_lines(words: Sequence[_Word], settings: DraftSettings | None = None) -> list[list[_Word]]:
    """Cut the word stream into lines.

    A line ends where the recogniser ended a phrase or where the singer pauses for
    ``line_gap_s``.  Very short lines are then joined to a neighbour that no real pause
    separates them from, and lines too long for the screen are cut at their longest pause.
    """
    settings = settings or DraftSettings()
    lines: list[list[_Word]] = []
    for word in words:
        previous = lines[-1][-1] if lines else None
        if (
            previous is None
            or word.segment != previous.segment
            or word.start_s - previous.end_s >= settings.line_gap_s
        ):
            lines.append([word])
        else:
            lines[-1].append(word)

    merged: list[list[_Word]] = []
    for line in lines:
        if merged:
            before = merged[-1]
            short = min(_line_width(before), _line_width(line)) < settings.min_width
            close = line[0].start_s - before[-1].end_s < settings.line_gap_s
            if short and close and _line_width([*before, *line]) <= settings.max_width:
                before.extend(line)
                continue
        merged.append(list(line))
    return [part for line in merged for part in _wrap(line, settings)]


def _build_line(words: Sequence[_Word], paragraph: int) -> DraftLine:
    """Join the words of a line and give every token the time of the characters it is made of."""
    chars: list[str] = []
    spans: list[tuple[float, float, float] | None] = []
    for index, word in enumerate(words):
        if index and _needs_space(words[index - 1].text, word.text):
            chars.append(" ")
            spans.append(None)
        sung = sum(not char.isspace() for char in word.text) or 1
        step = (word.end_s - word.start_s) / sung
        position = 0
        for char in word.text:
            chars.append(char)
            if char.isspace():
                spans.append(None)
                continue
            begin = word.start_s + position * step
            spans.append((begin, begin + step, word.probability))
            position += 1
    text = "".join(chars)
    start_s, end_s = words[0].start_s, max(word.end_s for word in words)
    pieces = tokenize(text)
    sung = [piece for piece in pieces if piece.core]
    tokens: list[DraftToken] = []
    if "".join(piece.text for piece in pieces) == text:
        offset = 0
        for piece in pieces:
            if piece.core:
                first = offset + max(piece.text.find(piece.core), 0)
                timed = [span for span in spans[first : first + len(piece.core)] if span]
                if timed:
                    begin = timed[0][0]
                    tokens.append(
                        DraftToken(
                            piece.text,
                            begin,
                            max(timed[-1][1], begin),
                            min(span[2] for span in timed),
                        )
                    )
            elif tokens:
                tokens[-1] = replace(tokens[-1], text=tokens[-1].text + piece.text)
            offset += len(piece.text)
    if len(tokens) != len(sung):
        # The tokenizer normalised the text in a way the bookkeeping above did not foresee:
        # spread the line evenly rather than guess.
        share = (end_s - start_s) / max(len(sung), 1)
        lowest = min(word.probability for word in words)
        tokens = [
            DraftToken(piece.text, start_s + index * share, start_s + (index + 1) * share, lowest)
            for index, piece in enumerate(sung)
        ]
    return DraftLine(text, tuple(tokens), start_s, end_s, paragraph)


def draft_lyrics(
    transcript: Transcript,
    language: str,
    regions: Sequence[tuple[float, float]] = (),
    settings: DraftSettings | None = None,
) -> list[DraftLine]:
    """Turn a transcript into draft lyric lines.

    Args:
        transcript: Recognised segments with word times.
        language: Project language; decides the script of Chinese text.
        regions: Voice-activity regions in seconds, used to drop text recognised in silence.
        settings: Line-cutting parameters.
    """
    settings = settings or DraftSettings()
    lines: list[DraftLine] = []
    paragraph = 0
    for words in split_lines(usable_words(transcript, language, regions, settings), settings):
        if lines and words[0].start_s - lines[-1].end_s >= settings.paragraph_gap_s:
            paragraph += 1
        line = _build_line(words, paragraph)
        if line.tokens:
            lines.append(line)
    return lines


def to_project_lines(draft: Sequence[DraftLine], *, singer: str = "m") -> list[Line]:
    """Project lines for a draft.

    The tokens carry the recogniser's times and its word probability as confidence; the
    line also keeps its time as a ``time_hint``, so that the alignment still knows where the
    line is after its text has been corrected beyond recognition.
    """
    lines: list[Line] = []
    floor = 0
    for number, item in enumerate(draft, start=1):
        starts: list[int] = []
        for token in item.tokens:
            floor = max(round(token.start_s * 1000), floor)
            starts.append(floor)
        tokens: list[Token] = []
        for index, token in enumerate(item.tokens):
            # A token never runs into the next one, whatever the recogniser's word ends say.
            limit = starts[index + 1] if index + 1 < len(starts) else round(token.end_s * 1000)
            end = max(min(round(token.end_s * 1000), limit), starts[index])
            tokens.append(
                Token(
                    text=token.text,
                    start_ms=starts[index],
                    end_ms=end,
                    confidence=round(min(max(token.probability, 0.0), 1.0), 3),
                )
            )
            floor = max(floor, end) if index + 1 == len(starts) else floor
        line_start = starts[0]
        line_end = max(tokens[-1].end_ms or line_start, line_start)
        lines.append(
            Line(
                id=f"L{number:03d}",
                singer=singer,
                paragraph=item.paragraph,
                tokens=tokens,
                time_hint=(line_start, line_end),
            )
        )
    return lines
