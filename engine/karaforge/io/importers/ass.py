r"""ASS / SSA importer.

Three kinds of script are understood:

* scripts exported by KaraForge — the ``Comment`` events with effect ``karaoke`` carry the
  word timing (and the singer in the ``Name`` field);
* karaoke scripts from other tools — ``Dialogue`` events with ``\k`` / ``\kf`` / ``\ko`` /
  ``\K`` tags give word timing;
* ordinary subtitles — each ``Dialogue`` event becomes a line with a line-level time hint.
"""

from __future__ import annotations

import re
from pathlib import Path

from karaforge.errors import LyricsFormatError
from karaforge.io.importers.lyrics_txt import ParsedLyrics, read_text_file
from karaforge.io.timed import ImportedLine, ImportedUnit, lines_from_imported

_TIME = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[.:](\d{1,3})")
_BLOCK = re.compile(r"\{([^}]*)\}")
_K_TAG = re.compile(r"\\(?:kf|ko|k|K)\s*(\d+)")
_SINGERS = {
    "m": "m", "男": "m", "male": "m",
    "f": "f", "女": "f", "female": "f",
    "all": "all", "合": "all", "duet": "all",
}  # fmt: skip
_DEFAULT_FORMAT = [
    "layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text",
]  # fmt: skip


def _ms(text: str) -> int | None:
    match = _TIME.search(text)
    if match is None:
        return None
    hours, minutes, seconds, fraction = match.groups()
    part = round(int(fraction) * 10 ** (3 - len(fraction)))
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1000 + part


def _plain(text: str) -> str:
    """Remove override blocks and line-break codes (escaped braces are kept as text)."""
    guarded = text.replace("\\{", "\x00").replace("\\}", "\x01")
    return re.sub(r"\s+", " ", _restore(_BLOCK.sub("", guarded))).strip()


def _unescape(text: str) -> str:
    cleaned = text.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
    return cleaned.replace("\\{", "{").replace("\\}", "}").replace("＼", "\\")


def _karaoke_units(text: str, start_ms: int) -> list[ImportedUnit]:
    r"""Split text with ``\k`` tags into timed units (durations are centiseconds)."""
    units: list[ImportedUnit] = []
    cursor = start_ms
    position = 0
    pending: int | None = None
    # Escaped braces must not be mistaken for override blocks.
    guarded = text.replace("\\{", "\x00").replace("\\}", "\x01")
    for block in _BLOCK.finditer(guarded):
        chunk = guarded[position : block.start()]
        if chunk and pending is not None:
            units.append(ImportedUnit(_restore(chunk), cursor, cursor + pending))
            cursor += pending
            pending = None
        elif chunk and units:
            units[-1].text += _restore(chunk)
        durations = [int(value) * 10 for value in _K_TAG.findall(block.group(1))]
        for duration in durations:
            if pending is not None:
                cursor += pending  # a timed stretch without text: a pause
            pending = duration
        position = block.end()
    tail = guarded[position:]
    if tail and pending is not None:
        units.append(ImportedUnit(_restore(tail), cursor, cursor + pending))
    elif tail and units:
        units[-1].text += _restore(tail)
    return [unit for unit in units if unit.text]


def _restore(text: str) -> str:
    return _unescape(text.replace("\x00", "\\{").replace("\x01", "\\}"))


def parse_ass_text(text: str) -> tuple[dict[str, str], list[ImportedLine]]:
    """Parse an ASS/SSA script into metadata and lines sorted by start time."""
    meta: dict[str, str] = {}
    fields = list(_DEFAULT_FORMAT)
    section = ""
    rows: list[tuple[str, dict[str, str]]] = []
    for raw in text.lstrip("\ufeff").splitlines():
        row = raw.strip()
        if row.startswith("[") and row.endswith("]"):
            section = row.lower()
            continue
        if section == "[script info]" and row.lower().startswith("title:"):
            title = row.split(":", 1)[1].strip()
            if title and title.lower() != "default aegisub file":
                meta["title"] = title
        if section != "[events]":
            continue
        kind, separator, rest = row.partition(":")
        if not separator:
            continue
        kind = kind.strip().lower()
        if kind == "format":
            fields = [name.strip().lower() for name in rest.split(",")]
        elif kind in ("dialogue", "comment"):
            values = rest.strip().split(",", len(fields) - 1)
            if len(values) == len(fields):
                rows.append((kind, dict(zip(fields, values, strict=True))))

    karaoke = [
        values for kind, values in rows
        if kind == "comment" and values.get("effect", "").strip().lower() == "karaoke"
    ]  # fmt: skip
    chosen = karaoke or [values for kind, values in rows if kind == "dialogue"]

    lines: list[ImportedLine] = []
    seen: set[tuple[int, str]] = set()
    for values in chosen:
        start = _ms(values.get("start", ""))
        end = _ms(values.get("end", ""))
        body = values.get("text", "")
        if start is None or "\\p1" in body or "\\p2" in body or "\\p4" in body:
            continue
        singer = _SINGERS.get(values.get("name", "").strip().lower())
        if _K_TAG.search(body):
            units = _karaoke_units(body, start)
            plain = "".join(unit.text for unit in units).strip()
            line = ImportedLine(
                plain,
                units[0].start_ms if units else start,
                units[-1].end_ms if units else end,
                units,
                singer,
            )
        else:
            plain = _plain(body)
            line = ImportedLine(plain, start, end, singer=singer)
        key = (line.start_ms or 0, plain)
        if not plain or key in seen:
            continue
        seen.add(key)
        lines.append(line)
    lines.sort(key=lambda item: item.start_ms or 0)
    return meta, lines


def parse_ass_file(path: Path) -> ParsedLyrics:
    """Read an ``.ass`` / ``.ssa`` file.

    Raises:
        LyricsFormatError: If the script has no usable events.
    """
    meta, imported = parse_ass_text(read_text_file(path))
    if not imported:
        raise LyricsFormatError(
            f"「{path.name}」裡沒有可用的字幕事件。",
            f"'{path.name}' contains no usable subtitle events.",
        )
    result = ParsedLyrics(meta=meta)
    result.lines = lines_from_imported(imported)
    return result
