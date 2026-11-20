"""Batch processing: pair the songs in a folder with their lyrics (``kf batch``).

A media file and a lyrics file belong together when they have the same name apart from the
extension (``夜空.mp3`` + ``夜空.txt``).  Pairing is pure and has no side effects, so the
command can show what it is going to do before it starts hours of work.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

from karaforge.errors import MediaError
from karaforge.io.importers import LYRICS_EXTENSIONS
from karaforge.project.create import MEDIA_EXTENSIONS
from karaforge.project.store import PROJECT_SUFFIX


@dataclass(frozen=True)
class BatchItem:
    """One song of a batch."""

    media: Path
    lyrics: Path | None

    @property
    def name(self) -> str:
        """Name of the song: the media file name without its extension."""
        return self.media.stem


@dataclass(frozen=True)
class BatchPlan:
    """What a folder contains."""

    items: tuple[BatchItem, ...]
    """Songs to process, in name order."""
    unmatched_lyrics: tuple[Path, ...]
    """Lyrics files that no media file goes with."""
    duplicates: tuple[Path, ...]
    """Media files left out because another file with the same name was taken."""


def _key(path: Path) -> str:
    """Name used for pairing: without extension, Unicode-normalised, case-insensitive."""
    return unicodedata.normalize("NFC", path.stem).casefold()


def plan_batch(folder: Path) -> BatchPlan:
    """Pair the media files directly inside ``folder`` with their lyrics.

    When several media files share a name (``song.mp4`` and ``song.mp3``) the first one in
    the order of :data:`~karaforge.project.create.MEDIA_EXTENSIONS` is used — video before
    audio — and the others are reported as duplicates.  The same rule picks between several
    lyrics files (``.txt`` before the timed formats).

    Raises:
        MediaError: If ``folder`` is not a directory.
    """
    if not folder.is_dir():
        raise MediaError(
            f"找不到資料夾:{folder}",
            f"Not a folder: {folder}",
            hint_zh="kf batch 需要一個放著歌曲與歌詞檔的資料夾。",
            hint_en="kf batch needs a folder that holds the songs and their lyrics files.",
        )
    media: dict[str, list[Path]] = {}
    lyrics: dict[str, list[Path]] = {}
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        extension = path.suffix.lower()
        if extension in MEDIA_EXTENSIONS:
            media.setdefault(_key(path), []).append(path)
        elif extension in LYRICS_EXTENSIONS:
            lyrics.setdefault(_key(path), []).append(path)

    def rank(order: tuple[str, ...]) -> dict[str, int]:
        return {extension: index for index, extension in enumerate(order)}

    media_rank = rank(MEDIA_EXTENSIONS)
    lyrics_rank = rank(LYRICS_EXTENSIONS)
    items: list[BatchItem] = []
    duplicates: list[Path] = []
    for key in sorted(media):
        candidates = sorted(media[key], key=lambda path: media_rank[path.suffix.lower()])
        texts = sorted(lyrics.get(key, []), key=lambda path: lyrics_rank[path.suffix.lower()])
        items.append(BatchItem(candidates[0], texts[0] if texts else None))
        duplicates += candidates[1:]
    unmatched = [path for key in sorted(lyrics) if key not in media for path in lyrics[key]]
    return BatchPlan(tuple(items), tuple(unmatched), tuple(duplicates))


def project_dir_for(item: BatchItem, out: Path) -> Path:
    """Where the project of a song is kept: next to its exported file."""
    return out / f"{item.name}{PROJECT_SUFFIX}"
