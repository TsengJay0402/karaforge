"""Reading and writing ``.kfproj`` folders."""

from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from karaforge.errors import ProjectError, RevisionConflictError
from karaforge.project.migrations import JsonObject, migrate
from karaforge.project.schema import Project

PROJECT_FILE = "project.json"
PROJECT_SUFFIX = ".kfproj"

_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def slugify(name: str) -> str:
    """Turn a title or file name into a safe folder name (keeps CJK characters)."""
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", name).strip().strip(".")
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned[:80] or "project"


@dataclass(frozen=True)
class ProjectPaths:
    """Well-known locations inside a project folder."""

    root: Path

    @property
    def project_file(self) -> Path:
        """``project.json``."""
        return self.root / PROJECT_FILE

    @property
    def media(self) -> Path:
        """Folder for the source file and derived audio."""
        return self.root / "media"

    @property
    def cache(self) -> Path:
        """Folder for per-stage caches."""
        return self.root / "cache"

    @property
    def exports(self) -> Path:
        """Folder for rendered output."""
        return self.root / "exports"

    @property
    def tmp(self) -> Path:
        """Scratch folder for in-flight work (safe to delete when nothing is running)."""
        return self.root / "cache" / "tmp"

    def resolve(self, relative: str | None) -> Path | None:
        """Turn a project-relative media path into an absolute one (``None`` stays ``None``)."""
        if relative is None:
            return None
        return self.root / Path(*relative.split("/"))

    def relative(self, path: Path) -> str:
        """Turn an absolute path inside the project into a POSIX-style relative one."""
        return path.resolve().relative_to(self.root.resolve()).as_posix()


class ProjectStore:
    """Loads and saves the ``project.json`` of one project folder.

    Saving is atomic (write to a temporary file, then rename) and bumps ``revision``.
    Callers that hold an older copy pass ``expected_revision`` to detect that someone else
    saved in between.
    """

    def __init__(self, root: Path) -> None:
        # Always absolute: stages run tools with a different working directory.
        self.paths = ProjectPaths(Path(root).expanduser().resolve())
        self._lock = _lock_for(self.paths.root)

    @property
    def root(self) -> Path:
        """The project folder."""
        return self.paths.root

    def exists(self) -> bool:
        """Whether the folder contains a ``project.json``."""
        return self.paths.project_file.is_file()

    def create(self, project: Project, *, overwrite: bool = False) -> Project:
        """Create the folder structure and write the first revision.

        Raises:
            ProjectError: If the project already exists and ``overwrite`` is false.
        """
        with self._lock:
            if self.exists() and not overwrite:
                raise ProjectError(
                    f"專案已經存在：{self.root}",
                    f"Project already exists: {self.root}",
                    hint_zh="換一個輸出路徑，或加上 --force 覆寫。",
                    hint_en="Choose another output path or pass --force to overwrite.",
                )
            if overwrite and self.root.exists():
                shutil.rmtree(self.root)
            for folder in (self.paths.root, self.paths.media, self.paths.cache, self.paths.exports):
                folder.mkdir(parents=True, exist_ok=True)
            project.revision = 0
            self._write(project)
            return project

    def read_raw(self) -> JsonObject:
        """Read ``project.json`` without validating or migrating it."""
        path = self.paths.project_file
        if not path.is_file():
            raise ProjectError(
                f"找不到專案：{self.root}（缺少 {PROJECT_FILE}）",
                f"Not a KaraForge project: {self.root} ({PROJECT_FILE} is missing)",
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError(
                f"無法讀取專案檔：{path}",
                f"Cannot read the project file: {path}",
                hint_zh=f"同一個資料夾裡的 {PROJECT_FILE}.bak 是上一次儲存的備份。",
                hint_en=f"{PROJECT_FILE}.bak in the same folder is a backup of the previous save.",
                detail=str(exc),
            ) from exc
        if not isinstance(data, dict):
            raise ProjectError(
                f"專案檔格式錯誤：{path}",
                f"Malformed project file: {path}",
                detail="top-level JSON value is not an object",
            )
        return data  # pyright: ignore[reportUnknownVariableType]

    def load(self) -> Project:
        """Load, migrate (in memory) and validate the project.

        A project in an older schema version is upgraded in memory; it is written back in the
        new format the next time it is saved.
        """
        with self._lock:
            migrated, _applied = migrate(self.read_raw())
            try:
                return Project.model_validate(migrated)
            except ValidationError as exc:
                raise ProjectError(
                    f"專案檔內容不符合格式：{self.paths.project_file}",
                    f"The project file is invalid: {self.paths.project_file}",
                    detail=str(exc),
                ) from exc

    def current_revision(self) -> int:
        """Revision currently stored on disk."""
        value = self.read_raw().get("revision", 0)
        return value if isinstance(value, int) else 0

    def save(self, project: Project, *, expected_revision: int | None = None) -> Project:
        """Validate and write the project, bumping its revision.

        Args:
            project: The document to store.  Its ``revision`` field is updated in place.
            expected_revision: Revision the caller based its changes on.  When given and the
                revision on disk differs, nothing is written.

        Raises:
            RevisionConflictError: If the project changed on disk since ``expected_revision``.
        """
        with self._lock:
            on_disk = self.current_revision() if self.exists() else 0
            if expected_revision is not None and on_disk != expected_revision:
                raise RevisionConflictError(
                    "專案已經被其他視窗或背景工作修改過，為了避免覆蓋，這次沒有儲存。",
                    "The project was changed elsewhere (another window or a background job); "
                    "nothing was saved to avoid overwriting it.",
                    hint_zh="請重新載入專案後再試一次。",
                    hint_en="Reload the project and try again.",
                    detail=f"expected revision {expected_revision}, found {on_disk}",
                )
            validated = Project.model_validate(project.model_dump())
            validated.revision = on_disk + 1
            self._write(validated)
            project.revision = validated.revision
            return project

    def _write(self, project: Project) -> None:
        path = self.paths.project_file
        payload = json.dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        if path.is_file():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        temporary.replace(path)
