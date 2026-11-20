"""Stage ① ingest: probe the source, decode analysis audio and compute waveform peaks."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import numpy as np

from karaforge.audio.io import read_wav
from karaforge.audio.peaks import PEAKS_VERSION, write_peaks
from karaforge.errors import MediaError, PipelineError
from karaforge.pipeline.stage import (
    JsonDict,
    Stage,
    StageContext,
    StageInputs,
    link_or_copy,
    update_project,
)
from karaforge.project.schema import Project
from karaforge.tools import ffmpeg

ANALYSIS_RATE = 48000
SUPPORTED_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".ogg",
)


def source_path(ctx: StageContext) -> Path:
    """Absolute path of the project's source media.

    Raises:
        PipelineError: If the project has no source file.
    """
    project = ctx.store.load()
    source = ctx.paths.resolve(project.media.source)
    if source is None or not source.is_file():
        raise PipelineError(
            "這個專案沒有來源媒體檔。",
            "This project has no source media file.",
            hint_zh="請用 `kf new <媒體檔> --lyrics <歌詞檔>` 建立專案。",
            hint_en="Create the project with `kf new <media> --lyrics <lyrics>`.",
        )
    return source


class IngestStage(Stage):
    """Decode the source to 48 kHz stereo ``audio.wav`` and build ``peaks.json``."""

    name: ClassVar[str] = "ingest"
    version: ClassVar[str] = "1"
    weight: ClassVar[float] = 0.5
    title_zh: ClassVar[str] = "讀取媒體"
    title_en: ClassVar[str] = "Reading media"

    def inputs(self, ctx: StageContext) -> StageInputs:
        """The source file, the analysis sample rate and the peaks format version."""
        return StageInputs(
            files={"source": source_path(ctx)},
            params={"rate": ANALYSIS_RATE, "channels": 2, "peaks": PEAKS_VERSION},
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Probe and decode the source."""
        source = source_path(ctx)
        info = ffmpeg.probe(source)
        if info.audio is None:
            raise MediaError(
                f"「{source.name}」裡沒有音訊。",
                f"'{source.name}' contains no audio stream.",
                hint_zh="請確認檔案是含有聲音的影片或音檔。",
                hint_en="Make sure the file is a video or audio file with sound.",
            )
        ctx.progress(0.05, "解碼音訊 / decoding audio")
        try:
            ffmpeg.run_ffmpeg(
                [
                    "-i",
                    str(source),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-ac",
                    "2",
                    "-ar",
                    str(ANALYSIS_RATE),
                    "-c:a",
                    "pcm_s16le",
                    "audio.wav",
                ],
                cwd=out_dir,
                duration_ms=info.duration_ms or None,
                progress=lambda fraction, message: ctx.progress(0.05 + 0.8 * fraction, message),
                message="解碼音訊 / decoding audio",
                cancel=ctx.cancel,
            )
        except ffmpeg.FFmpegError as exc:
            raise MediaError(
                f"無法解碼「{source.name}」的音訊。",
                f"Could not decode the audio of '{source.name}'.",
                detail=exc.detail,
            ) from exc

        audio, rate = read_wav(out_dir / "audio.wav")
        if audio.shape[0] < rate // 2:
            raise MediaError(
                f"「{source.name}」的音訊太短(不到半秒)。",
                f"The audio of '{source.name}' is shorter than half a second.",
            )
        ctx.progress(0.9, "計算波形 / computing waveform")
        write_peaks(out_dir / "peaks.json", np.asarray(audio.mean(axis=1), dtype=np.float32), rate)
        video = info.video
        return {
            "duration_ms": round(audio.shape[0] * 1000 / rate),
            "sample_rate": rate,
            "format": info.format_name,
            "has_video": video is not None,
            "video": (
                {"width": video.width, "height": video.height, "fps": video.frame_rate}
                if video is not None
                else None
            ),
            "has_cover": info.cover_art is not None,
            "source_audio_codec": info.audio.codec,
            "tags": {key: info.tags[key] for key in ("title", "artist") if info.tags.get(key)},
        }

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Expose ``audio.wav`` / ``peaks.json`` and record duration and video presence."""
        link_or_copy(out_dir / "audio.wav", ctx.paths.media / "audio.wav")
        link_or_copy(out_dir / "peaks.json", ctx.paths.media / "peaks.json")
        tags: dict[str, str] = dict(result.get("tags") or {})

        def mutate(project: Project) -> None:
            project.media.audio = "media/audio.wav"
            project.media.has_video = bool(result["has_video"])
            project.meta.duration_ms = int(result["duration_ms"])
            if not project.meta.title and tags.get("title"):
                project.meta.title = tags["title"]
            if not project.meta.artist and tags.get("artist"):
                project.meta.artist = tags["artist"]

        update_project(ctx, mutate)
