"""Exporting a project: one entry point for every output format.

Shared by the command line (``kf export``) and the web server.  Every format produces exactly
one file under the project's ``exports/`` folder.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from karaforge.errors import ExportError
from karaforge.pipeline.profiles import Profile, get_profile
from karaforge.pipeline.runner import EventFn, StageEvent
from karaforge.project.schema import Project
from karaforge.project.store import ProjectStore, slugify
from karaforge.runtime import CancelToken, ProgressFn, null_progress

if TYPE_CHECKING:
    from karaforge.io.exporters.video import VideoOptions

BACKGROUNDS = ("video", "image", "color", "blur")


@dataclass(frozen=True)
class ExportFormat:
    """One output format."""

    id: str
    suffix: str
    """Appended to the output name, e.g. ``.mp4`` or ``.enhanced.lrc``."""
    video: bool
    title_zh: str
    title_en: str


FORMATS: dict[str, ExportFormat] = {
    item.id: item
    for item in (
        ExportFormat("mp4", ".mp4", True, "MP4 影片(字幕燒進畫面)", "MP4 video, burned-in lyrics"),
        ExportFormat(
            "mkv",
            ".mkv",
            True,
            "MKV 影片(軟字幕、雙音軌)",
            "MKV video, soft subtitles, two audio tracks",
        ),
        ExportFormat("ass", ".ass", False, "ASS 字幕", "ASS subtitles"),
        ExportFormat("lrc", ".lrc", False, "LRC 歌詞(逐行)", "LRC lyrics (line timed)"),
        ExportFormat(
            "elrc", ".enhanced.lrc", False, "增強型 LRC(逐字)", "Enhanced LRC (word timed)"
        ),
        ExportFormat("srt", ".srt", False, "SRT 字幕", "SRT subtitles"),
        ExportFormat(
            "ultrastar", ".ultrastar.txt", False, "UltraStar 歌曲檔", "UltraStar song file"
        ),
        ExportFormat("kfproj", ".kfproj.zip", False, "專案壓縮檔", "Project archive"),
    )
}


@dataclass(frozen=True)
class ExportRequest:
    """What to export and how."""

    format: str = "mp4"
    audio: str = "instrumental"
    """``instrumental``, ``guide[:-12db]`` or ``original`` (video formats only)."""
    resolution: tuple[int, int] | None = None
    """Output size for this export; the project's own setting when omitted."""
    background: str | None = None
    name: str | None = None
    """Base name of the file under ``exports/``; the song title when omitted."""


def _ignore(event: StageEvent) -> None:
    """Default event sink."""


def get_format(name: str) -> ExportFormat:
    """Look up an export format.

    Raises:
        ExportError: If the format is unknown.
    """
    found = FORMATS.get(name.strip().lower())
    if found is None:
        raise ExportError(
            f"不支援的匯出格式:{name}",
            f"Unsupported export format: {name}",
            hint_zh="可用:" + "、".join(FORMATS) + "。",
            hint_en="Available: " + ", ".join(FORMATS) + ".",
        )
    return found


def output_name(project: Project, request: ExportRequest) -> str:
    """Base file name of an export."""
    return slugify(request.name or project.meta.title or "karaoke")


def export(
    store: ProjectStore,
    request: ExportRequest,
    *,
    profile: Profile | None = None,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
    on_event: EventFn = _ignore,
) -> Path:
    """Export a project and return the path of the file written under ``exports/``.

    An export never re-runs the processing stages: it renders the project as it is.

    Raises:
        ExportError: If the format or an option is not understood, or rendering fails.
        PipelineError: If the project has not been aligned yet.
    """
    from karaforge.stages.standard import run_pipeline
    from karaforge.stages.subtitles import ASS_FILE, RESOLUTION_KEY, require_aligned

    fmt = get_format(request.format)
    project = store.load()
    name = output_name(project, request)
    target = store.paths.exports / f"{name}{fmt.suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {}
    if request.resolution is not None:
        options[RESOLUTION_KEY] = list(request.resolution)
    used_profile = profile or get_profile()

    if fmt.video:
        from karaforge.stages.export import OPTION_KEY, OUTPUT_NAME_KEY
        from karaforge.stages.standard import EXPORT_TARGETS

        options |= {OPTION_KEY: _video_options(project, request, fmt), OUTPUT_NAME_KEY: name}
        run_pipeline(
            store,
            profile=used_profile,
            targets=EXPORT_TARGETS,
            options=options,
            progress=progress,
            cancel=cancel,
            on_event=on_event,
            include_dependencies=False,
        )
        return target

    if fmt.id == "kfproj":
        from karaforge.io.exporters.archive import export_project_zip

        export_project_zip(store, target)
        return target

    require_aligned(project)
    if fmt.id == "ass":
        report = run_pipeline(
            store,
            profile=used_profile,
            targets=("subtitles",),
            options=options,
            progress=progress,
            cancel=cancel,
            on_event=on_event,
            include_dependencies=False,
        )
        produced = store.paths.cache / "subtitles" / str(report["subtitles"].key) / ASS_FILE
        shutil.copyfile(produced, target)
        return target

    text = _text_export(store, project, fmt, name, used_profile, progress, cancel, on_event)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    return target


def _video_options(project: Project, request: ExportRequest, fmt: ExportFormat) -> VideoOptions:
    from karaforge.io.exporters.video import VideoOptions, parse_audio_option
    from karaforge.layout.theme import load_theme

    theme = load_theme(project.style.theme).with_overrides(project.style.overrides)
    mode, level = parse_audio_option(request.audio)
    kind = (request.background or project.render.background.type).lower()
    if kind not in BACKGROUNDS:
        raise ExportError(
            f"看不懂的背景選項:{kind}",
            f"Unrecognised background: {kind}",
            hint_zh="可用:" + "、".join(BACKGROUNDS) + "。",
            hint_en="Use one of: " + ", ".join(BACKGROUNDS) + ".",
        )
    return VideoOptions(
        container="mkv" if fmt.id == "mkv" else "mp4",
        audio=mode,
        guide_db=level,
        background=kind,
        color=project.render.background.color or theme.background.color,
        image=project.render.background.image,
        dim_bottom=theme.background.dim_bottom,
    )


def _text_export(
    store: ProjectStore,
    project: Project,
    fmt: ExportFormat,
    name: str,
    profile: Profile,
    progress: ProgressFn,
    cancel: CancelToken | None,
    on_event: EventFn,
) -> str:
    from karaforge.io.exporters.lrc import export_enhanced_lrc, export_lrc
    from karaforge.io.exporters.srt import export_srt

    several_singers = len({line.singer for line in project.lines if line.tokens}) > 1
    if fmt.id == "lrc":
        return export_lrc(project, singers=several_singers)
    if fmt.id == "elrc":
        return export_enhanced_lrc(project, singers=several_singers)
    if fmt.id == "srt":
        return export_srt(project)

    from karaforge.audio.pitch import load_f0, token_pitches
    from karaforge.io.exporters.ultrastar import export_ultrastar
    from karaforge.stages.pitch import F0_FILE
    from karaforge.stages.standard import run_pipeline

    pitches: dict[tuple[str, int], int] = {}
    if (store.paths.media / "vocals.wav").is_file():
        report = run_pipeline(
            store,
            profile=profile,
            targets=("pitch",),
            progress=progress,
            cancel=cancel,
            on_event=on_event,
            include_dependencies=False,
        )
        track = store.paths.cache / "pitch" / str(report["pitch"].key) / F0_FILE
        pitches = token_pitches(project, load_f0(track))
    source = Path(project.media.source or "audio.mp3")
    media_name = f"{name}{source.suffix or '.mp3'}"
    return export_ultrastar(
        project,
        pitches=pitches,
        audio_name=media_name,
        video_name=media_name if project.media.has_video else None,
    )
