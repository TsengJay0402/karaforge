"""SubRip (``.srt``) exporter: one cue per lyric line."""

from __future__ import annotations

from karaforge.io.timed import clock
from karaforge.project.schema import Project

_MIN_CUE_MS = 500


def export_srt(project: Project) -> str:
    """Write the lyrics as SubRip cues.

    A cue lasts from the line's first token to its last; very short lines are extended to
    half a second, and a cue never runs into the next line.
    """
    lines = [line for line in project.lines if line.tokens and line.start_ms is not None]
    blocks: list[str] = []
    for index, line in enumerate(lines):
        start = line.start_ms or 0
        end = max(line.end_ms or start, start + _MIN_CUE_MS)
        if index + 1 < len(lines):
            following = lines[index + 1].start_ms or end
            if following > start:
                end = min(end, following)
        blocks.append(
            f"{len(blocks) + 1}\n"
            f"{clock(start, digits=3, hours=True, separator=',')} --> "
            f"{clock(end, digits=3, hours=True, separator=',')}\n"
            f"{line.text.strip()}\n"
        )
    return "\n".join(blocks)
