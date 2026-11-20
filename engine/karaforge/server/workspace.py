"""The workspace: a folder whose ``*.kfproj`` sub-folders are the projects the server shows."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from karaforge.errors import KaraForgeError, ProjectError
from karaforge.project.schema import Project
from karaforge.project.store import PROJECT_SUFFIX, ProjectStore, slugify

_UNSAFE = re.compile(r"[\\/\x00]|^\.")
LOW_CONFIDENCE = 0.5


class ProjectNotFoundError(ProjectError):
    """There is no project with that id in the workspace."""

    code = "project_not_found"


@dataclass(frozen=True)
class ProjectStats:
    """Numbers about a project's lyrics shown in the project list."""

    lines: int
    tokens: int
    timed_tokens: int
    locked_tokens: int
    low_confidence: int


def project_stats(project: Project) -> ProjectStats:
    """Count lines, tokens and how many of them are timed, locked or doubtful."""
    tokens = [token for line in project.lines for token in line.tokens]
    return ProjectStats(
        lines=sum(1 for line in project.lines if line.tokens),
        tokens=len(tokens),
        timed_tokens=sum(1 for token in tokens if token.is_timed),
        locked_tokens=sum(1 for token in tokens if token.locked),
        low_confidence=sum(
            1
            for token in tokens
            if token.is_timed
            and not token.locked
            and token.confidence is not None
            and token.confidence < LOW_CONFIDENCE
        ),
    )


class Workspace:
    """Finds, creates and removes project folders under one root directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def uploads(self) -> Path:
        """Scratch folder for files that are being uploaded."""
        return self.root / ".uploads"

    def project_ids(self) -> list[str]:
        """Ids of all projects, most recently modified first."""
        found: list[tuple[float, str]] = []
        for folder in self.root.iterdir():
            document = folder / "project.json"
            if folder.name.endswith(PROJECT_SUFFIX) and document.is_file():
                found.append((document.stat().st_mtime, folder.name.removesuffix(PROJECT_SUFFIX)))
        return [name for _mtime, name in sorted(found, reverse=True)]

    def folder(self, project_id: str) -> Path:
        """Folder of a project id (which need not exist).

        Raises:
            ProjectNotFoundError: If the id could point outside the workspace.
        """
        if not project_id or _UNSAFE.search(project_id) or project_id in (".", ".."):
            raise ProjectNotFoundError(
                f"找不到專案:{project_id}", f"Project not found: {project_id}"
            )
        return self.root / f"{project_id}{PROJECT_SUFFIX}"

    def store(self, project_id: str) -> ProjectStore:
        """Open an existing project.

        Raises:
            ProjectNotFoundError: If there is no such project.
        """
        store = ProjectStore(self.folder(project_id))
        if not store.exists():
            raise ProjectNotFoundError(
                f"找不到專案:{project_id}", f"Project not found: {project_id}"
            )
        return store

    def new_id(self, title: str) -> str:
        """An unused project id derived from ``title``."""
        base = slugify(title).lstrip(".") or "project"
        candidate, counter = base, 2
        while self.folder(candidate).exists():
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def delete(self, project_id: str) -> None:
        """Remove a project folder and everything in it."""
        store = self.store(project_id)
        shutil.rmtree(store.root)

    def summary(self, project_id: str) -> dict[str, Any]:
        """What the project list shows about one project.

        A project whose file cannot be read is still listed (with ``broken`` set), so that
        the user can see and delete it.
        """
        store = ProjectStore(self.folder(project_id))
        modified = store.paths.project_file.stat().st_mtime
        try:
            project = store.load()
        except KaraForgeError as error:
            return {
                "id": project_id,
                "title": project_id,
                "artist": "",
                "language": "",
                "duration_ms": 0,
                "has_video": False,
                "processed": False,
                "stats": project_stats(Project()).__dict__,
                "revision": 0,
                "modified_at": modified,
                "broken": error.to_dict(),
            }
        return {
            "id": project_id,
            "title": project.meta.title or project_id,
            "artist": project.meta.artist,
            "language": project.meta.language,
            "duration_ms": project.meta.duration_ms,
            "has_video": project.media.has_video,
            "processed": project.media.vocals is not None,
            "stats": project_stats(project).__dict__,
            "revision": project.revision,
            "modified_at": modified,
            "broken": None,
        }
