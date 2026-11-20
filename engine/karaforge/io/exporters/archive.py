"""Packing a project folder into a zip archive."""

from __future__ import annotations

import zipfile
from pathlib import Path

from karaforge.project.store import ProjectStore


def export_project_zip(store: ProjectStore, output: Path, *, include_exports: bool = False) -> int:
    """Write the project as ``<name>.kfproj/…`` inside a zip file.

    ``project.json`` and everything under ``media/`` are included; the per-stage caches are
    not (they can be recomputed), and ``exports/`` only on request.

    Args:
        store: The project to pack.
        output: Zip file to write.
        include_exports: Also pack rendered files from ``exports/``.

    Returns:
        The number of files written.
    """
    root = store.root
    top = root.name if root.name.endswith(".kfproj") else f"{root.name}.kfproj"
    folders = [store.paths.media, *([store.paths.exports] if include_exports else [])]
    files = [store.paths.project_file]
    for folder in folders:
        if folder.is_dir():
            files += sorted(path for path in folder.rglob("*") if path.is_file())
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as archive:
        for path in files:
            name = f"{top}/{path.relative_to(root).as_posix()}"
            # Audio and video are already compressed (or huge): store them as they are.
            stored = path.suffix.lower() in {
                ".wav",
                ".mp3",
                ".mp4",
                ".mkv",
                ".flac",
                ".m4a",
                ".ogg",
            }
            archive.write(
                path, name, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            )
    temporary.replace(output)
    return len(files)
