"""Shared pieces of the timed-lyrics importers and exporters (LRC, SRT, ASS, UltraStar)."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from karaforge.project.schema import Line, Token
from karaforge.text.tokenize import tokenize

SINGER_PREFIXES = {"M": "m", "F": "f", "D": "all"}
"""Line prefixes of the "walaoke" LRC extension: ``M:`` male, ``F:`` female, ``D:`` duet."""
PREFIX_OF_SINGER = {"m": "M", "f": "F", "all": "D"}
SPLIT_CONFIDENCE = 0.3
"""Confidence given to tokens whose time was interpolated inside an imported unit."""


@dataclass
class ImportedUnit:
    """A piece of text with its own time, as found in a word-timed file."""

    text: str
    start_ms: int
    end_ms: int


@dataclass
class ImportedLine:
    """One line read from a timed-lyrics file."""

    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    units: list[ImportedUnit] = field(default_factory=list[ImportedUnit])
    """Word-level timing, when the file has it (otherwise only the line time is known)."""
    singer: str | None = None


def clock(ms: int, *, digits: int = 2, hours: bool = False, separator: str = ".") -> str:
    """Format milliseconds as ``mm:ss.xx`` (or ``hh:mm:ss,xxx`` style with ``hours``)."""
    total = max(0, ms)
    unit = 10 ** (3 - digits)
    fraction = round(total / unit) if digits < 3 else total
    whole, part = divmod(fraction, 10**digits)
    minutes, seconds = divmod(whole, 60)
    if hours:
        hour, minutes = divmod(minutes, 60)
        return f"{hour:02d}:{minutes:02d}:{seconds:02d}{separator}{part:0{digits}d}"
    return f"{minutes:02d}:{seconds:02d}{separator}{part:0{digits}d}"


def tokens_from_units(units: list[ImportedUnit]) -> list[Token]:
    """Turn word-timed units into project tokens.

    A unit that is exactly one token keeps its times and is locked: imported timing is
    preserved unless the user unlocks it.  A unit that covers several tokens (``你好`` timed
    as one word) is split evenly; only its first token — whose start is known exactly — is
    locked, the others are marked as estimates so that a later re-alignment may refine them.
    Text without anything to sing (spaces, punctuation) is attached to the token before it.
    """
    tokens: list[Token] = []
    for unit in units:
        pieces = tokenize(unit.text)
        if not any(piece.core for piece in pieces):
            if tokens and unit.text:
                last = tokens[-1]
                tokens[-1] = last.model_copy(update={"text": last.text + unit.text})
            continue
        start, end = unit.start_ms, max(unit.end_ms, unit.start_ms)
        # Rebuild the unit's exact text from the pieces (they drop only outer whitespace).
        texts = [piece.text for piece in pieces]
        leading = len(unit.text) - len(unit.text.lstrip())
        trailing = unit.text[len(unit.text.rstrip()) :]
        if leading:
            texts[0] = unit.text[:leading] + texts[0]
        if trailing and not texts[-1].endswith(trailing):
            texts[-1] += trailing
        share = (end - start) / len(texts)
        for index, text in enumerate(texts):
            token_start = round(start + index * share)
            token_end = round(start + (index + 1) * share) if index < len(texts) - 1 else end
            tokens.append(
                Token(
                    text=text,
                    start_ms=token_start,
                    end_ms=max(token_end, token_start),
                    confidence=1.0 if index == 0 else SPLIT_CONFIDENCE,
                    locked=index == 0,
                    source="import",
                )
            )
    return tokens


def lines_from_imported(imported: list[ImportedLine], *, default_singer: str = "m") -> list[Line]:
    """Build project lines from imported lines.

    Lines with word-level units become timed tokens; lines with only a line time become
    untimed tokens plus a ``time_hint`` for the aligner.  A gap of at least four seconds
    starts a new paragraph.
    """
    from karaforge.io.importers.lyrics_txt import tokens_from_text

    lines: list[Line] = []
    singer = default_singer
    paragraph = 0
    previous_end: int | None = None
    for item in imported:
        if item.singer:
            singer = item.singer
        tokens = tokens_from_units(item.units) if item.units else tokens_from_text(item.text)
        if not tokens:
            continue
        start = item.start_ms if item.start_ms is not None else None
        if start is not None and previous_end is not None and start - previous_end >= 4000:
            paragraph += 1
        hint: tuple[int, int | None] | None = None
        if not item.units and item.start_ms is not None:
            end = item.end_ms if item.end_ms is not None and item.end_ms >= item.start_ms else None
            hint = (item.start_ms, end)
        lines.append(
            Line(
                id=f"L{len(lines) + 1:03d}",
                singer=singer,
                paragraph=paragraph,
                tokens=tokens,
                time_hint=hint,
            )
        )
        if item.units:
            previous_end = item.units[-1].end_ms
        elif item.end_ms is not None:
            previous_end = item.end_ms
        elif item.start_ms is not None:
            previous_end = item.start_ms
    # A line without a known end is assumed to last until the next line starts.
    for line, following in pairwise(lines):
        if line.time_hint is not None and line.time_hint[1] is None and following.time_hint:
            line.time_hint = (line.time_hint[0], max(line.time_hint[0], following.time_hint[0]))
    return lines
