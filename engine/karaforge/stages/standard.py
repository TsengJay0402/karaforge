"""The standard pipeline: every stage wired together, plus helpers to run it."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from karaforge.pipeline.profiles import Profile, get_profile
from karaforge.pipeline.runner import EventFn, PipelineRunner, RunReport, StageEvent
from karaforge.pipeline.stage import Stage, StageContext
from karaforge.project.store import ProjectStore
from karaforge.runtime import CancelToken, ProgressFn, null_progress
from karaforge.stages.align import AlignStage
from karaforge.stages.analyze import AnalyzeStage
from karaforge.stages.asr import AsrStage
from karaforge.stages.export import ExportStage
from karaforge.stages.ingest import IngestStage
from karaforge.stages.separate import SeparateStage
from karaforge.stages.subtitles import SubtitlesStage

PROCESS_TARGETS: tuple[str, ...] = ("align",)
"""What ``kf run`` brings up to date: everything needed for an aligned project."""


def all_stages() -> list[Stage]:
    """Fresh instances of every stage, in a valid execution order."""
    return [
        IngestStage(),
        SeparateStage(),
        AnalyzeStage(),
        AsrStage(),
        AlignStage(),
        SubtitlesStage(),
        ExportStage(),
    ]


def build_pipeline() -> PipelineRunner:
    """The runner over the standard stages."""
    return PipelineRunner(all_stages())


def _ignore(event: StageEvent) -> None:
    """Default event sink."""


def run_pipeline(
    store: ProjectStore,
    *,
    profile: Profile | None = None,
    targets: Sequence[str] | None = PROCESS_TARGETS,
    force_from: str | None = None,
    options: dict[str, Any] | None = None,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
    on_event: EventFn = _ignore,
    include_dependencies: bool = True,
) -> RunReport:
    """Run the standard pipeline on a project.

    Args:
        store: The project.
        profile: Processing profile; the default profile when omitted.
        targets: Stages to bring up to date.  ``None`` runs everything including the export.
        force_from: Re-run this stage and everything after it even if cached.
        options: Per-run options for stages (export settings, lines to re-align, …).
        progress: Overall progress callback.
        cancel: Cancellation token.
        on_event: Receives stage start/finish events.
        include_dependencies: When false, run exactly ``targets`` (see
            :meth:`PipelineRunner.run`).

    Returns:
        A report of what ran and what came from the cache.
    """
    context = StageContext(
        store=store,
        profile=profile or get_profile(),
        progress=progress,
        cancel=cancel or CancelToken(),
        options=dict(options or {}),
    )
    return build_pipeline().run(
        context,
        targets=targets,
        force_from=force_from,
        on_event=on_event,
        include_dependencies=include_dependencies,
    )


EXPORT_TARGETS: tuple[str, ...] = ("subtitles", "export")
"""What an export runs: layout and rendering of the project *as it is*."""
