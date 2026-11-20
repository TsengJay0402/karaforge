"""LRC exporters: simple (one time per line) and enhanced (one time per token)."""

from __future__ import annotations

from karaforge.io.timed import PREFIX_OF_SINGER, clock
from karaforge.project.schema import Line, Project

_CLEAR_GAP_MS = 3000


def _header(project: Project) -> list[str]:
    meta = project.meta
    rows: list[str] = []
    if meta.title:
        rows.append(f"[ti:{meta.title}]")
    if meta.artist:
        rows.append(f"[ar:{meta.artist}]")
    if meta.composer:
        rows.append(f"[au:{meta.composer}]")
    if meta.duration_ms:
        rows.append(f"[length:{clock(meta.duration_ms, digits=2)}]")
    rows.append("[re:KaraForge]")
    return rows


def _timed_lines(project: Project) -> list[Line]:
    return [line for line in project.lines if line.tokens and line.start_ms is not None]


def _prefix(line: Line, singers: bool) -> str:
    return (
        f"{PREFIX_OF_SINGER[line.singer]}: " if singers and line.singer in PREFIX_OF_SINGER else ""
    )


def export_lrc(project: Project, *, singers: bool = False, digits: int = 2) -> str:
    """Write simple LRC: ``[mm:ss.xx]text`` per line.

    An empty timed row is added after a line that is followed by a long pause (or by
    nothing), so that players clear the display instead of showing the line through the
    interlude.

    Args:
        project: The project; lines without timing are left out.
        singers: Prefix lines with ``M:`` / ``F:`` / ``D:`` (the "walaoke" extension).
        digits: Fraction digits of the timestamps (2 is standard, 3 for milliseconds).
    """
    rows = _header(project)
    lines = _timed_lines(project)
    for index, line in enumerate(lines):
        start, end = line.start_ms or 0, line.end_ms or 0
        rows.append(f"[{clock(start, digits=digits)}]{_prefix(line, singers)}{line.text.strip()}")
        following = lines[index + 1].start_ms if index + 1 < len(lines) else None
        if following is None or following - end >= _CLEAR_GAP_MS:
            rows.append(f"[{clock(end, digits=digits)}]")
    return "\n".join(rows) + "\n"


def export_enhanced_lrc(project: Project, *, singers: bool = False, digits: int = 2) -> str:
    """Write enhanced LRC with a time tag before every token.

    ``[line start]<t0>tok0<t1>tok1…<line end>``.  When a token ends before the next one
    starts, its end is written as an extra tag directly before the next token's tag.
    """
    rows = _header(project)
    for line in _timed_lines(project):
        parts: list[str] = []
        tokens = [token for token in line.tokens if token.start_ms is not None]
        for index, token in enumerate(tokens):
            start, end = token.start_ms or 0, token.end_ms or 0
            parts.append(f"<{clock(start, digits=digits)}>{token.text}")
            following = tokens[index + 1].start_ms if index + 1 < len(tokens) else None
            if following is None or clock(following, digits=digits) != clock(end, digits=digits):
                parts.append(f"<{clock(end, digits=digits)}>")
        start = line.start_ms or 0
        rows.append(f"[{clock(start, digits=digits)}]{_prefix(line, singers)}{''.join(parts)}")
    return "\n".join(rows) + "\n"
