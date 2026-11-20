"""The stage interface of the processing pipeline.

A stage is a deterministic step: given the same input files, parameters and adapter version it
produces the same output.  The runner (:mod:`karaforge.pipeline.runner`) uses that to cache
results under ``cache/<stage>/<key>/``.

A stage has two halves:

``run``
    The expensive part.  It writes artifacts into a fresh output folder and returns a small
    JSON-serialisable result.  It must not touch ``project.json`` or ``media/``.

``publish``
    The cheap, idempotent part.  It makes the cached output visible to the rest of the system:
    links artifacts into ``media/`` and/or merges data into ``project.json``.  It runs on every
    pipeline run, cache hit or not.
"""

from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from karaforge.errors import PipelineError
from karaforge.pipeline.hashing import FileHashCache
from karaforge.pipeline.profiles import Profile
from karaforge.project.schema import Project
from karaforge.project.store import ProjectPaths, ProjectStore
from karaforge.runtime import CancelToken, ProgressFn, null_progress

JsonDict = dict[str, Any]


@dataclass
class StageInputs:
    """Everything that determines a stage's output; hashed into the cache key."""

    files: dict[str, Path] = field(default_factory=dict[str, Path])
    """Input files by logical name.  Their *content* is hashed, not their path."""
    params: JsonDict = field(default_factory=dict[str, Any])
    """Parameters that influence the output."""
    adapters: dict[str, str] = field(default_factory=dict[str, str])
    """Adapters used, as ``role -> "name@version"``."""
    data: JsonDict = field(default_factory=dict[str, Any])
    """Other inputs, e.g. the lyric text and locked anchors for alignment."""


@dataclass
class StageContext:
    """What a stage gets to work with."""

    store: ProjectStore
    profile: Profile
    progress: ProgressFn = null_progress
    cancel: CancelToken = field(default_factory=CancelToken)
    options: JsonDict = field(default_factory=dict[str, Any])
    """Per-run options that are not part of the profile (e.g. export settings)."""
    outputs: dict[str, Path] = field(default_factory=dict[str, Path])
    """Cache folders of the stages published so far in this run, by stage name."""
    results: dict[str, JsonDict] = field(default_factory=dict[str, JsonDict])
    """Result objects of the stages published so far in this run, by stage name."""
    _hashes: FileHashCache | None = None

    @property
    def paths(self) -> ProjectPaths:
        """Locations inside the project folder."""
        return self.store.paths

    @property
    def hashes(self) -> FileHashCache:
        """File-hash cache of this project."""
        if self._hashes is None:
            self._hashes = FileHashCache(self.paths.cache / "hashes.json")
        return self._hashes

    def with_progress(self, progress: ProgressFn) -> StageContext:
        """Return a copy of the context that reports progress elsewhere."""
        return StageContext(
            store=self.store,
            profile=self.profile,
            progress=progress,
            cancel=self.cancel,
            options=self.options,
            outputs=self.outputs,
            results=self.results,
            _hashes=self.hashes,
        )

    def output_of(self, stage: str) -> Path:
        """Cache folder of an upstream stage published earlier in this run.

        Raises:
            PipelineError: If that stage has not run (a missing ``requires`` declaration).
        """
        if stage not in self.outputs:
            raise PipelineError(
                f"階段「{stage}」還沒有輸出。",
                f"Stage '{stage}' has not produced output yet.",
                detail="a stage read an upstream output it does not declare in `requires`",
            )
        return self.outputs[stage]


class Stage(ABC):
    """Base class of pipeline stages."""

    name: ClassVar[str]
    """Unique stage name; also the cache sub-folder."""
    version: ClassVar[str] = "1"
    """Bump whenever the stage's output would change for the same inputs."""
    requires: ClassVar[tuple[str, ...]] = ()
    """Names of the stages that must be published before this one."""
    weight: ClassVar[float] = 1.0
    """Relative share of the overall progress bar."""
    cache_keep: ClassVar[int] = 4
    """How many cache entries of this stage to keep per project."""
    title_zh: ClassVar[str] = ""
    title_en: ClassVar[str] = ""

    def is_needed(self, ctx: StageContext) -> bool:
        """Whether the stage applies to this project at all (default: always)."""
        return True

    @abstractmethod
    def inputs(self, ctx: StageContext) -> StageInputs:
        """Declare the inputs that determine the output."""

    @abstractmethod
    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Do the work, write artifacts into ``out_dir`` and return a JSON-serialisable result."""

    @abstractmethod
    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Make a (possibly cached) output visible in ``media/`` and ``project.json``."""


def link_or_copy(source: Path, target: Path) -> None:
    """Make ``target`` a hard link to ``source`` (or a copy when linking is not possible).

    Does nothing when ``target`` already is the same file.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            if source.samefile(target):
                return
        except OSError:
            pass
        target.unlink()
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def update_project(ctx: StageContext, mutate: Callable[[Project], None]) -> Project:
    """Load the project, apply ``mutate`` and save it only if something changed.

    Stages call this from ``publish``.  Skipping the save when nothing changed keeps the
    revision stable on cache hits, so an open editor is not told to reload for no reason.
    """
    project = ctx.store.load()
    before = project.model_dump_json()
    mutate(project)
    if project.model_dump_json() != before:
        ctx.store.save(project)
    return project
