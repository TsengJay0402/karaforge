"""UltraStar (``.txt``) exporter and importer.

UltraStar measures time in *beats*: a note line is ``: start length pitch text``, and one
beat lasts ``15 / BPM`` seconds for the ``#BPM`` value written in the file (which is four
times finer than a musical beat).  ``#GAP`` is the time of beat zero in milliseconds.  The
exporter uses the song's tempo, doubled until a beat is at most 50 ms, so that note starts
stay close to the token times.

Pitches are semitones relative to C4.  When no pitch is known for a token the note is written
on C4, which sings fine but scores nothing — run the pitch analysis for real note heights.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from karaforge.errors import LyricsFormatError
from karaforge.io.timed import ImportedLine, ImportedUnit
from karaforge.project.schema import Project

_FALLBACK_BPM = 300.0
_MAX_BEAT_MS = 50.0
_C4 = 60


def beat_grid(tempo_bpm: float | None) -> float:
    """The ``#BPM`` value to write: the song tempo scaled to a beat of at most 50 ms."""
    if tempo_bpm is None or not 30.0 <= tempo_bpm <= 400.0:
        return _FALLBACK_BPM
    value = tempo_bpm
    while 15000.0 / value > _MAX_BEAT_MS:
        value *= 2.0
    return round(value, 2)


def export_ultrastar(
    project: Project,
    *,
    pitches: dict[tuple[str, int], int] | None = None,
    audio_name: str = "audio.mp3",
    video_name: str | None = None,
) -> str:
    """Write the project as an UltraStar song file.

    Args:
        project: The project; untimed lines are left out.
        pitches: MIDI note per ``(line id, token index)``; missing entries use C4.
        audio_name: File name for the ``#MP3`` / ``#AUDIO`` headers.
        video_name: File name for ``#VIDEO``, if there is a video.

    Raises:
        LyricsFormatError: If no line of the project has timing.
    """
    lines = [line for line in project.lines if line.tokens and line.start_ms is not None]
    if not lines:
        raise LyricsFormatError(
            "沒有已對齊的歌詞可以輸出成 UltraStar。",
            "There are no aligned lyrics to export as UltraStar.",
        )
    bpm = beat_grid(project.analysis.tempo_bpm)
    beat_ms = 15000.0 / bpm
    gap = lines[0].start_ms or 0
    notes = pitches or {}

    def beat(time_ms: int) -> int:
        return max(0, round((time_ms - gap) / beat_ms))

    meta = project.meta
    rows = [
        f"#TITLE:{meta.title or 'Untitled'}",
        f"#ARTIST:{meta.artist or 'Unknown'}",
        f"#MP3:{audio_name}",
        f"#AUDIO:{audio_name}",
    ]
    if video_name:
        rows.append(f"#VIDEO:{video_name}")
    if meta.language:
        rows.append(f"#LANGUAGE:{meta.language}")
    rows += [f"#BPM:{bpm:g}".replace(".", ","), f"#GAP:{gap}"]

    previous_end_beat = 0
    for line_index, line in enumerate(lines):
        if line_index:
            line_start = beat(line.start_ms or 0)
            rows.append(f"- {min(max(previous_end_beat, line_start - 1), line_start)}")
        carry_space = False
        for index, token in enumerate(line.tokens):
            if token.start_ms is None or token.end_ms is None:
                continue
            start = max(beat(token.start_ms), previous_end_beat if index else 0)
            length = max(1, beat(token.end_ms) - start)
            pitch = notes.get((line.id, index), _C4) - _C4
            # UltraStar puts the space *before* a syllable that starts a new word.
            text = (" " if carry_space else "") + token.text.rstrip(" ")
            carry_space = token.text.endswith(" ")
            rows.append(f": {start} {length} {pitch} {text}")
            previous_end_beat = start + length
    rows.append("E")
    return "\n".join(rows) + "\n"


_NOTE = re.compile(r"^([:*FRG])\s+(-?\d+)\s+(\d+)\s+(-?\d+)\s(.*)$")


def parse_ultrastar(text: str) -> tuple[dict[str, str], list[ImportedLine], list[list[int]]]:
    """Read an UltraStar song file.

    Returns:
        Header tags (lower-cased keys), the lines with word timing, and the MIDI pitch of
        every syllable (same shape as the lines' units).
    """
    headers: dict[str, str] = {}
    lines: list[ImportedLine] = []
    pitch_rows: list[list[int]] = []
    units: list[ImportedUnit] = []
    pitches: list[int] = []
    bpm = _FALLBACK_BPM
    gap = 0.0

    def flush() -> None:
        if units:
            lines.append(
                ImportedLine(
                    text="".join(unit.text for unit in units).strip(),
                    start_ms=units[0].start_ms,
                    end_ms=units[-1].end_ms,
                    units=list(units),
                )
            )
            pitch_rows.append(list(pitches))
            units.clear()
            pitches.clear()

    for raw in text.lstrip("﻿").splitlines():
        row = raw.rstrip("\r\n")
        if row.startswith("#"):
            key, _, value = row[1:].partition(":")
            headers[key.strip().lower()] = value.strip()
            if key.strip().upper() == "BPM":
                bpm = float(value.strip().replace(",", ".") or _FALLBACK_BPM)
            elif key.strip().upper() == "GAP":
                gap = float(value.strip().replace(",", ".") or 0.0)
            continue
        if row.startswith("-"):
            flush()
            continue
        if row.strip() == "E":
            break
        match = _NOTE.match(row)
        if match is None:
            continue
        beat_ms = 15000.0 / bpm
        start = round(gap + int(match.group(2)) * beat_ms)
        end = round(gap + (int(match.group(2)) + int(match.group(3))) * beat_ms)
        syllable = match.group(5)
        if syllable.startswith(" ") and units:
            # The leading space belongs to the end of the previous syllable in our model.
            units[-1].text += " "
            syllable = syllable[1:]
        units.append(ImportedUnit(syllable, start, end))
        pitches.append(int(match.group(4)) + _C4)
    flush()
    return headers, lines, pitch_rows


def pitch_table(
    project: Project, values: Sequence[Sequence[int | None]]
) -> dict[tuple[str, int], int]:
    """Build the ``pitches`` argument of :func:`export_ultrastar` from per-line pitch lists."""
    table: dict[tuple[str, int], int] = {}
    timed = [line for line in project.lines if line.tokens and line.start_ms is not None]
    for line, row in zip(timed, values, strict=False):
        for index, value in enumerate(row):
            if value is not None:
                table[(line.id, index)] = value
    return table
