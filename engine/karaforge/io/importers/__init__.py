r"""Readers that turn lyric and subtitle files into project lines.

:func:`load_lyrics` picks the reader from the file extension:

=========== =====================================================================
``.txt``    KaraForge's own plain-text format (no timing)
``.lrc``    LRC; line times become hints, enhanced (word-timed) LRC keeps its timing
``.srt``    SubRip; cue times become line hints
``.ass``    ASS / SSA; ``\k`` karaoke timing is kept, otherwise line hints
=========== =====================================================================
"""

from __future__ import annotations

from pathlib import Path

from karaforge.errors import LyricsFormatError
from karaforge.io.importers.lyrics_txt import ParsedLyrics, parse_lyrics_file

LYRICS_EXTENSIONS = (".txt", ".lrc", ".srt", ".ass", ".ssa")


def load_lyrics(path: Path) -> ParsedLyrics:
    """Read lyrics from any supported format.

    Raises:
        LyricsFormatError: If the extension is not supported or the file cannot be parsed.
    """
    extension = path.suffix.lower()
    if extension == ".lrc":
        from karaforge.io.importers.lrc import parse_lrc_file

        return parse_lrc_file(path)
    if extension == ".srt":
        from karaforge.io.importers.srt import parse_srt_file

        return parse_srt_file(path)
    if extension in (".ass", ".ssa"):
        from karaforge.io.importers.ass import parse_ass_file

        return parse_ass_file(path)
    if extension in (".txt", ""):
        return parse_lyrics_file(path)
    raise LyricsFormatError(
        f"不支援的歌詞檔格式：{path.name}",
        f"Unsupported lyrics format: {path.name}",
        hint_zh="支援 " + "、".join(LYRICS_EXTENSIONS) + "。",
        hint_en="Supported: " + ", ".join(LYRICS_EXTENSIONS) + ".",
    )


__all__ = ["LYRICS_EXTENSIONS", "ParsedLyrics", "load_lyrics"]
