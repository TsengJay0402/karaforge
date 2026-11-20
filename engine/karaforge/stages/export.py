"""Stage ⑦ export: render the video file."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from karaforge.io.exporters.video import (
    VIDEO_EXPORT_VERSION,
    VideoOptions,
    effective_background,
    export_video,
    second_track,
)
from karaforge.layout.fonts import default_library
from karaforge.pipeline.stage import (
    JsonDict,
    Stage,
    StageContext,
    StageInputs,
    link_or_copy,
)
from karaforge.project.store import slugify
from karaforge.stages.subtitles import ASS_FILE, PLAN_FILE, load_plan

OPTION_KEY = "video"
"""Key in :attr:`StageContext.options` that holds the :class:`VideoOptions`."""
OUTPUT_NAME_KEY = "output_name"


def video_options(ctx: StageContext) -> VideoOptions:
    """The export options of this run (defaults when none were given)."""
    value: Any = ctx.options.get(OPTION_KEY)
    return value if isinstance(value, VideoOptions) else VideoOptions()


class ExportStage(Stage):
    """Render the video: MP4 with burned-in subtitles, or MKV with a subtitle track."""

    name: ClassVar[str] = "export"
    version: ClassVar[str] = VIDEO_EXPORT_VERSION
    requires: ClassVar[tuple[str, ...]] = ("subtitles",)
    weight: ClassVar[float] = 3.0
    cache_keep: ClassVar[int] = 2
    title_zh: ClassVar[str] = "輸出影片"
    title_en: ClassVar[str] = "Rendering video"

    def inputs(self, ctx: StageContext) -> StageInputs:
        """The script, the media that goes into the file, the fonts and the options."""
        project = ctx.store.load()
        options = video_options(ctx)
        subtitles = ctx.output_of("subtitles")
        plan = load_plan(subtitles / PLAN_FILE)
        files: dict[str, Path] = {"ass": subtitles / ASS_FILE}
        background = effective_background(project, ctx.paths, options)
        source = ctx.paths.resolve(project.media.source)
        tracks = {options.audio, second_track(project, ctx.paths, options)}
        if source is not None and (background == "video" or "original" in tracks):
            files["source"] = source
        if tracks & {"instrumental", "guide"}:
            files["instrumental"] = ctx.paths.media / "instrumental.wav"
        if "guide" in tracks:
            files["vocals"] = ctx.paths.media / "vocals.wav"
        image = ctx.paths.resolve(options.image)
        if background in ("image", "blur") and image is not None:
            files["image"] = image
        library = default_library()
        for font in plan.fonts:
            files[f"font:{font.family}"] = library.find(font.family).path
        return StageInputs(
            files=files,
            params=options.cache_params()
            | {
                "background_effective": background,
                "fps": project.render.fps,
                "duration_ms": project.meta.duration_ms,
            },
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Run ffmpeg."""
        project = ctx.store.load()
        subtitles = ctx.output_of("subtitles")
        plan = load_plan(subtitles / PLAN_FILE)
        options = video_options(ctx)
        output = out_dir / f"video.{options.container}"
        export_video(
            project,
            ctx.paths,
            plan,
            (subtitles / ASS_FILE).read_text(encoding="utf-8"),
            output,
            options,
            progress=ctx.progress,
            cancel=ctx.cancel,
        )
        extra = second_track(project, ctx.paths, options)
        return {
            "file": output.name,
            "container": options.container,
            "bytes": output.stat().st_size,
            "width": plan.width,
            "height": plan.height,
            "audio": options.audio,
            "audio_tracks": [options.audio, *([extra] if extra is not None else [])],
            "background": effective_background(project, ctx.paths, options),
        }

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Expose the video under ``exports/``."""
        project = ctx.store.load()
        name = str(ctx.options.get(OUTPUT_NAME_KEY) or slugify(project.meta.title or "karaoke"))
        produced = out_dir / str(result["file"])
        link_or_copy(produced, ctx.paths.exports / f"{name}{produced.suffix}")
