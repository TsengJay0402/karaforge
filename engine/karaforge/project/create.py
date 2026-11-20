"""Creating a new project from a media file and (optionally) lyrics."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from karaforge.errors import MediaError, ProjectError
from karaforge.io.importers.lyrics_txt import ParsedLyrics, parse_lyrics_file
from karaforge.pipeline.hashing import sha256_file
from karaforge.project.schema import Project
from karaforge.project.store import PROJECT_SUFFIX, ProjectStore, slugify

MEDIA_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".ogg",
    ".opus",
    ".aac",
    ".avi",
)


def default_project_dir(media: Path, parent: Path | None = None) -> Path:
    """Folder name used when the user does not choose one: ``<media stem>.kfproj``."""
    return (parent or media.parent) / f"{slugify(media.stem)}{PROJECT_SUFFIX}"


def _place_source(media: Path, target: Path) -> None:
    """Put the source file into the project: a hard link when possible, otherwise a copy."""
    if target.exists():
        target.unlink()
    try:
        os.link(media, target)
    except OSError:
        shutil.copy2(media, target)


def create_project(
    media: Path,
    project_dir: Path,
    *,
    lyrics: Path | None = None,
    language: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    overwrite: bool = False,
) -> ProjectStore:
    """Create a ``.kfproj`` folder for ``media``.

    Args:
        media: Source video or audio file.
        project_dir: Folder to create.
        lyrics: Lyrics file (``.txt``); omit to draft the lyrics by speech recognition.
        language: Language of the song, e.g. ``zh-TW`` or ``en``; overrides the lyrics file.
        title: Song title; overrides the lyrics file.
        artist: Artist; overrides the lyrics file.
        overwrite: Replace an existing project in ``project_dir``.

    Returns:
        The store of the new project.

    Raises:
        MediaError: If the media file is missing or of an unsupported type.
        LyricsFormatError: If the lyrics cannot be parsed.
        ProjectError: If the project exists and ``overwrite`` is false.
    """
    if not media.is_file():
        raise MediaError(f"找不到媒體檔:{media}", f"Media file not found: {media}")
    extension = media.suffix.lower()
    if extension not in MEDIA_EXTENSIONS:
        raise MediaError(
            f"不支援的檔案類型:{media.name}",
            f"Unsupported file type: {media.name}",
            hint_zh="支援的格式:" + "、".join(ext.lstrip(".") for ext in MEDIA_EXTENSIONS),
            hint_en="Supported: " + ", ".join(ext.lstrip(".") for ext in MEDIA_EXTENSIONS),
        )
    parsed: ParsedLyrics | None = parse_lyrics_file(lyrics) if lyrics is not None else None

    project = Project()
    if parsed is not None:
        parsed.apply_meta(project.meta)
        project.singers = parsed.singers
        project.lines = parsed.lines
    if language:
        project.meta.language = language
    if title:
        project.meta.title = title
    if artist:
        project.meta.artist = artist
    if not project.meta.title:
        project.meta.title = media.stem
    project.media.source = f"media/source{extension}"

    store = ProjectStore(project_dir)
    store.create(project, overwrite=overwrite)
    _place_source(media, store.paths.media / f"source{extension}")
    return store


def _same_content(first: Path, second: Path) -> bool:
    """Whether two files have identical content (cheap checks first)."""
    try:
        if first.samefile(second):
            return True
    except OSError:
        return False
    if first.stat().st_size != second.stat().st_size:
        return False
    return sha256_file(first) == sha256_file(second)


def create_or_update_project(
    media: Path,
    project_dir: Path,
    *,
    lyrics: Path | None = None,
    language: str | None = None,
) -> tuple[ProjectStore, bool]:
    """Create the project, or reuse an existing one made from the same media file.

    Reusing keeps the per-stage caches, so running the same command again only redoes what
    changed.  When the lyrics file differs from what the project holds, the lines are
    replaced (and will be aligned again).

    Returns:
        The store and whether the project was newly created.

    Raises:
        ProjectError: If ``project_dir`` holds a project for a different media file.
    """
    store = ProjectStore(project_dir)
    if not store.exists():
        return create_project(media, project_dir, lyrics=lyrics, language=language), True
    if not media.is_file():
        raise MediaError(f"找不到媒體檔:{media}", f"Media file not found: {media}")
    project = store.load()
    source = store.paths.resolve(project.media.source)
    if source is None or not source.is_file() or not _same_content(source, media):
        raise ProjectError(
            f"{project_dir} 已經是另一個媒體檔的專案。",
            f"{project_dir} already holds a project for a different media file.",
            hint_zh="請換一個輸出檔名,或先刪除那個專案資料夾。",
            hint_en="Choose another output name or delete that project folder first.",
        )
    changed = False
    if lyrics is not None:
        parsed = parse_lyrics_file(lyrics)
        current = [(line.singer, line.paragraph, line.text) for line in project.lines]
        wanted = [(line.singer, line.paragraph, line.text) for line in parsed.lines]
        if current != wanted:
            project.singers = parsed.singers
            project.lines = parsed.lines
            changed = True
        before = project.meta.model_dump()
        parsed.apply_meta(project.meta)
        changed = changed or project.meta.model_dump() != before
    if language and project.meta.language != language:
        project.meta.language = language
        changed = True
    if changed:
        store.save(project)
    return store, False
