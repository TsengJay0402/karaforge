"""SubRip (``.srt``) importer: each cue becomes a lyric line with a line-level time hint."""

from __future__ import annotations

import re
from pathlib import Path

from karaforge.errors import LyricsFormatError
from karaforge.io.importers.lyrics_txt import ParsedLyrics, read_text_file
from karaforge.io.timed import ImportedLine, lines_from_imported

_TIMING = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)
_MARKUP = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def _ms(hours: str, minutes: str, seconds: str, fraction: str) -> int:
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1000
        + round(int(fraction) * 10 ** (3 - len(fraction)))
    )


def parse_srt_text(text: str) -> list[ImportedLine]:
    """Parse SubRip content.  A cue with several text rows gives one line per row."""
    lines: list[ImportedLine] = []
    blocks = re.split(r"\n\s*\n", text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        rows = [row for row in block.split("\n") if row.strip()]
        timing_index = next((i for i, row in enumerate(rows) if _TIMING.search(row)), None)
        if timing_index is None:
            continue
        match = _TIMING.search(rows[timing_index])
        assert match is not None
        start = _ms(*match.groups()[:4])
        end = _ms(*match.groups()[4:])
        bodies = [_MARKUP.sub("", row).strip() for row in rows[timing_index + 1 :]]
        bodies = [body for body in bodies if body]
        if not bodies:
            continue
        share = (end - start) / len(bodies)
        for index, body in enumerate(bodies):
            lines.append(
                ImportedLine(
                    text=body,
                    start_ms=round(start + index * share),
                    end_ms=round(start + (index + 1) * share),
                )
            )
    return lines


def parse_srt_file(path: Path) -> ParsedLyrics:
    """Read an ``.srt`` file.

    Raises:
        LyricsFormatError: If the file contains no cues.
    """
    imported = parse_srt_text(read_text_file(path))
    if not imported:
        raise LyricsFormatError(
            f"「{path.name}」裡沒有字幕。",
            f"'{path.name}' contains no subtitle cues.",
        )
    result = ParsedLyrics()
    result.lines = lines_from_imported(imported)
    return result
