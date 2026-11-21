"""LRC importer: simple (line-timed) and enhanced (word-timed) lyrics.

Supported:

* ID tags ``[ti:]``, ``[ar:]``, ``[au:]`` (composer), ``[offset:±ms]``;
* one or several time tags per line (``[00:12.30][01:40.10]text`` repeats the line);
* enhanced LRC word tags ``<00:12.30>word``; a tag directly followed by another tag marks the
  end of the previous word, and a final tag marks the end of the line;
* the ``M:`` / ``F:`` / ``D:`` singer prefixes of the "walaoke" extension.
"""

from __future__ import annotations

import re
from pathlib import Path

from karaforge.errors import LyricsFormatError
from karaforge.io.importers.lyrics_txt import ParsedLyrics, read_text_file
from karaforge.io.timed import SINGER_PREFIXES, ImportedLine, ImportedUnit, lines_from_imported

_TIME = r"(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?"
_LINE_TAG = re.compile(r"\[" + _TIME + r"\]")
_WORD_TAG = re.compile(r"<" + _TIME + r">")
_ID_TAG = re.compile(r"^\[([a-zA-Z#]+)\s*:(.*)\]\s*$")
_PREFIX = re.compile(r"^\s*([MFD])\s*:\s*")
_META = {"ti": "title", "ar": "artist", "au": "composer"}


def _ms(minutes: str, seconds: str, fraction: str | None) -> int:
    part = round(int(fraction) * 10 ** (3 - len(fraction))) if fraction else 0
    return int(minutes) * 60_000 + int(seconds) * 1000 + part


def parse_lrc_text(text: str) -> tuple[dict[str, str], list[ImportedLine]]:
    """Parse LRC content into metadata and lines sorted by time."""
    meta: dict[str, str] = {}
    offset = 0
    entries: list[tuple[int, int, ImportedLine]] = []
    for order, raw in enumerate(text.lstrip("﻿").splitlines()):
        row = raw.strip()
        if not row:
            continue
        id_tag = _ID_TAG.match(row)
        if id_tag and not _LINE_TAG.match(row):
            key, value = id_tag.group(1).lower(), id_tag.group(2).strip()
            if key in _META and value:
                meta[_META[key]] = value
            elif key == "offset":
                try:
                    offset = int(value)
                except ValueError:
                    offset = 0
            continue
        times: list[int] = []
        position = 0
        while True:
            match = _LINE_TAG.match(row, position)
            if not match:
                break
            times.append(_ms(*match.groups()))
            position = match.end()
        if not times:
            continue
        body = row[position:]
        singer: str | None = None
        prefix = _PREFIX.match(body)
        if prefix:
            singer = SINGER_PREFIXES[prefix.group(1)]
            body = body[prefix.end() :]
        entries.extend((time, order, _parse_body(body, time, singer)) for time in times)

    entries.sort(key=lambda entry: (entry[0], entry[1]))
    lines: list[ImportedLine] = []
    for index, (time, _order, line) in enumerate(entries):
        following = entries[index + 1][0] if index + 1 < len(entries) else None
        if not line.text.strip():
            continue  # an empty timed row only marks the end of the previous line
        if line.end_ms is None and following is not None:
            line.end_ms = following
        if line.start_ms is None:
            line.start_ms = time
        lines.append(line)
    # ``offset`` > 0 means the lyrics should appear earlier.
    if offset:
        for line in lines:
            line.start_ms = max(0, (line.start_ms or 0) - offset)
            line.end_ms = None if line.end_ms is None else max(0, line.end_ms - offset)
            for unit in line.units:
                unit.start_ms = max(0, unit.start_ms - offset)
                unit.end_ms = max(0, unit.end_ms - offset)
    return meta, lines


def _parse_body(body: str, line_time: int, singer: str | None) -> ImportedLine:
    """Split the text of a row into word-timed units if it carries word tags."""
    tags = list(_WORD_TAG.finditer(body))
    if not tags:
        return ImportedLine(text=body.strip(), start_ms=line_time, singer=singer)
    units: list[ImportedUnit] = []
    head = body[: tags[0].start()]
    if head.strip():
        # Text before the first word tag starts with the line itself.
        units.append(ImportedUnit(head, line_time, _ms(*tags[0].groups())))
    end_of_line: int | None = None
    for index, tag in enumerate(tags):
        start = _ms(*tag.groups())
        stop = tags[index + 1].start() if index + 1 < len(tags) else len(body)
        chunk = body[tag.end() : stop]
        following = _ms(*tags[index + 1].groups()) if index + 1 < len(tags) else None
        if not chunk.strip():
            # A tag with no text after it closes the previous word (or the line).
            if units:
                units[-1].end_ms = max(units[-1].start_ms, start)
                if chunk and following is not None:
                    units[-1].text += chunk
            if following is None:
                end_of_line = start
            continue
        units.append(ImportedUnit(chunk, start, following if following is not None else start))
    if units and end_of_line is None and units[-1].end_ms <= units[-1].start_ms:
        units[-1].end_ms = units[-1].start_ms + 400  # no closing tag: assume a short word
    text = "".join(unit.text for unit in units).strip()
    start_ms = units[0].start_ms if units else line_time
    end_ms = units[-1].end_ms if units else None
    return ImportedLine(text=text, start_ms=start_ms, end_ms=end_ms, units=units, singer=singer)


def parse_lrc_file(path: Path) -> ParsedLyrics:
    """Read an ``.lrc`` file.

    Raises:
        LyricsFormatError: If the file contains no timed lines.
    """
    meta, imported = parse_lrc_text(read_text_file(path))
    if not imported:
        raise LyricsFormatError(
            f"「{path.name}」裡沒有帶時間標記的歌詞。",
            f"'{path.name}' contains no timed lyric lines.",
            hint_zh="LRC 的每一行應該以 [分:秒.百分秒] 開頭；純文字歌詞請改用 .txt。",
            hint_en="Each LRC line should start with [mm:ss.xx]; use .txt for plain lyrics.",
        )
    result = ParsedLyrics(meta=meta)
    result.lines = lines_from_imported(imported)
    return result
