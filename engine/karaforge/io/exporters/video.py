"""Video export with ffmpeg: MP4 with burned-in subtitles."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from karaforge.errors import ExportError
from karaforge.io.exporters.png import write_bottom_gradient
from karaforge.layout.fonts import default_library
from karaforge.layout.plan import RenderPlan
from karaforge.pipeline.stage import link_or_copy
from karaforge.project.schema import Project
from karaforge.project.store import ProjectPaths
from karaforge.runtime import CancelToken, ProgressFn, null_progress
from karaforge.tools import ffmpeg

AudioMode = Literal["instrumental", "guide", "original"]
BackgroundMode = Literal["video", "image", "color", "blur"]
VIDEO_EXPORT_VERSION = "1"


@dataclass(frozen=True)
class VideoOptions:
    """Settings of a video export."""

    audio: AudioMode = "instrumental"
    guide_db: float = -12.0
    """Level of the guide vocal relative to the original, for ``audio="guide"``."""
    background: BackgroundMode = "video"
    color: str = "#12141C"
    image: str | None = None
    """Project-relative path of the background image, for ``image`` and ``blur``."""
    dim_bottom: float = 0.45
    encoder: str = "libx264"
    crf: int = 20
    preset: str = "medium"
    audio_bitrate: str = "256k"

    def cache_params(self) -> dict[str, object]:
        """The options as a JSON-serialisable mapping (for cache keys)."""
        return dict(self.__dict__)


def parse_audio_option(value: str) -> tuple[AudioMode, float]:
    """Parse the CLI's ``--audio`` value: ``instrumental``, ``original`` or ``guide[:-12db]``.

    Raises:
        ExportError: If the value is not understood.
    """
    text = value.strip().lower()
    if text in ("instrumental", "karaoke", "伴奏"):
        return "instrumental", -12.0
    if text in ("original", "原曲", "原唱"):
        return "original", -12.0
    if text.startswith("guide"):
        _, _, level = text.partition(":")
        level = level.removesuffix("db").strip()
        if not level:
            return "guide", -12.0
        try:
            return "guide", -abs(float(level))
        except ValueError:
            pass
    raise ExportError(
        f"看不懂的音訊選項:{value}",
        f"Unrecognised audio option: {value}",
        hint_zh="可用:instrumental(純伴奏)、guide:-12db(伴奏加導唱)、original(原曲)。",
        hint_en="Use instrumental, guide:-12db or original.",
    )


def effective_background(
    project: Project, paths: ProjectPaths, options: VideoOptions
) -> BackgroundMode:
    """The background that can actually be produced for this project.

    ``video`` needs a source with a video stream and ``image``/``blur`` need an image; when
    the requirement is not met a plain colour is used instead.
    """
    if options.background == "video":
        return "video" if project.media.has_video else "color"
    if options.background in ("image", "blur"):
        image = paths.resolve(options.image)
        return options.background if image is not None and image.is_file() else "color"
    return "color"


def export_mp4(
    project: Project,
    paths: ProjectPaths,
    plan: RenderPlan,
    ass_text: str,
    output: Path,
    options: VideoOptions,
    *,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
) -> None:
    """Render an MP4 (H.264 + AAC) with the subtitles burned in.

    Args:
        project: The project being exported.
        paths: Locations inside the project folder.
        plan: Render plan the subtitles were generated from (gives size and fonts).
        ass_text: The ASS script.
        output: File to write.
        options: Audio, background and encoder settings.
        progress: Progress callback.
        cancel: Cancellation token.

    Raises:
        ExportError: If a needed input is missing or ffmpeg fails.
        ToolMissingError: If ffmpeg lacks libass.
    """
    ffmpeg.require_libass()
    width, height = plan.width, plan.height
    fps = project.render.fps
    duration_ms = project.meta.duration_ms
    if duration_ms <= 0:
        raise ExportError(
            "專案還沒有處理過(不知道歌曲長度),無法匯出。",
            "The project has not been processed yet; nothing to export.",
            hint_zh="請先執行 `kf run <專案>`。",
            hint_en="Run `kf run <project>` first.",
        )

    work = paths.tmp / f"export-{uuid.uuid4().hex[:10]}"
    (work / "fonts").mkdir(parents=True)
    try:
        (work / "subs.ass").write_text(ass_text, encoding="utf-8")
        library = default_library()
        for font in plan.fonts:
            face = library.find(font.family)
            link_or_copy(face.path, work / "fonts" / face.path.name)

        inputs: list[str] = []
        filters: list[str] = []
        seconds = f"{duration_ms / 1000:.3f}"
        fit = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps:g}"
        )
        cover = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps:g}"
        )
        background = effective_background(project, paths, options)
        source = paths.resolve(project.media.source)
        source_index: int | None = None

        if background == "video":
            assert source is not None
            link_or_copy(source, work / f"source{source.suffix}")
            inputs += ["-i", f"source{source.suffix}"]
            source_index = 0
            filters.append(f"[0:v:0]{fit}[bg]")
        elif background in ("image", "blur"):
            image = paths.resolve(options.image)
            assert image is not None
            link_or_copy(image, work / f"image{image.suffix}")
            inputs += [
                "-loop",
                "1",
                "-framerate",
                f"{fps:g}",
                "-t",
                seconds,
                "-i",
                f"image{image.suffix}",
            ]
            if background == "image":
                filters.append(f"[0:v]{cover}[bg]")
            else:
                inner = round(height * 0.62)
                filters.append(
                    f"[0:v]split[bg_a][bg_b];"
                    f"[bg_a]{cover},gblur=sigma=36,eq=brightness=-0.12[blurred];"
                    f"[bg_b]scale=-2:{inner},setsar=1,fps={fps:g}[sharp];"
                    f"[blurred][sharp]overlay=(W-w)/2:(H-h)*0.36[bg]"
                )
        else:
            color = options.color.lstrip("#")[:6]
            inputs += [
                "-f",
                "lavfi",
                "-t",
                seconds,
                "-i",
                f"color=c=0x{color}:s={width}x{height}:r={fps:g}",
            ]
            filters.append("[0:v]setsar=1[bg]")
        next_index = 1

        video_label = "bg"
        if options.dim_bottom > 0.0:
            write_bottom_gradient(work / "gradient.png", width, height, options.dim_bottom)
            inputs += ["-i", "gradient.png"]
            filters.append(f"[bg][{next_index}:v]overlay=0:0:eof_action=repeat[dimmed]")
            video_label = "dimmed"
            next_index += 1
        filters.append(f"[{video_label}]ass=subs.ass:fontsdir=fonts,format=yuv420p[v]")

        # ---- audio
        instrumental = paths.resolve(project.media.instrumental)
        vocals = paths.resolve(project.media.vocals)
        audio_map: str
        if options.audio == "original":
            if source is None or not source.is_file():
                raise ExportError("找不到原始媒體檔。", "The source media file is missing.")
            if source_index is None:
                link_or_copy(source, work / f"source{source.suffix}")
                inputs += ["-i", f"source{source.suffix}"]
                source_index = next_index
                next_index += 1
            audio_map = f"{source_index}:a:0"
        else:
            if instrumental is None or not instrumental.is_file():
                raise ExportError(
                    "還沒有伴奏軌,無法以伴唱模式匯出。",
                    "There is no accompaniment stem yet.",
                    hint_zh="請先執行 `kf run <專案>` 做人聲分離,或改用 --audio original。",
                    hint_en="Run `kf run <project>` first, or export with --audio original.",
                )
            link_or_copy(instrumental, work / "instrumental.wav")
            inputs += ["-i", "instrumental.wav"]
            instrumental_index = next_index
            next_index += 1
            if options.audio == "guide":
                if vocals is None or not vocals.is_file():
                    raise ExportError("找不到人聲軌。", "The vocal stem is missing.")
                link_or_copy(vocals, work / "vocals.wav")
                inputs += ["-i", "vocals.wav"]
                filters.append(
                    f"[{next_index}:a]volume={options.guide_db:g}dB[guide];"
                    f"[{instrumental_index}:a][guide]amix=inputs=2:normalize=0[a]"
                )
                next_index += 1
                audio_map = "[a]"
            else:
                audio_map = f"{instrumental_index}:a:0"

        arguments = [
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            audio_map,
            "-t",
            seconds,
            "-c:v",
            options.encoder,
        ]
        if options.encoder == "libx264":
            arguments += ["-preset", options.preset, "-crf", str(options.crf)]
        arguments += [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            options.audio_bitrate,
            "-movflags",
            "+faststart",
            "out.mp4",
        ]
        try:
            ffmpeg.run_ffmpeg(
                arguments,
                cwd=work,
                duration_ms=duration_ms,
                progress=progress,
                message="輸出影片 / rendering video",
                cancel=cancel,
            )
        except ffmpeg.FFmpegError as exc:
            raise ExportError(
                "影片輸出失敗。",
                "Video export failed.",
                hint_zh="加上 --verbose 可以看到 ffmpeg 的錯誤訊息。",
                hint_en="Re-run with --verbose to see ffmpeg's error output.",
                detail=exc.detail,
            ) from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(work / "out.mp4"), output)
    finally:
        shutil.rmtree(work, ignore_errors=True)


__all__ = [
    "VIDEO_EXPORT_VERSION",
    "AudioMode",
    "BackgroundMode",
    "VideoOptions",
    "effective_background",
    "export_mp4",
    "parse_audio_option",
]
