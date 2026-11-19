"""Locate and run ``ffmpeg`` / ``ffprobe``.

Lookup order for each tool: the ``KARAFORGE_FFMPEG`` / ``KARAFORGE_FFPROBE`` environment
variable, then ``PATH``, then ``$KARAFORGE_HOME/bin``.  The last location lets users without
root access drop in a static build (or the Docker wrapper from ``docker/ffmpeg-wrapper``).
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import threading
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import IO

from pydantic import BaseModel, ConfigDict, Field

from karaforge import paths
from karaforge.errors import JobCancelledError, KaraForgeError, MediaError, ToolMissingError
from karaforge.runtime import CancelToken, ProgressFn, null_progress

ENV_FFMPEG = "KARAFORGE_FFMPEG"
ENV_FFPROBE = "KARAFORGE_FFPROBE"

_INSTALL_HINT_ZH = (
    "請安裝含 libass 的 ffmpeg(Ubuntu/Debian:`sudo apt install ffmpeg`;"
    "macOS:`brew install ffmpeg`;Windows:`winget install ffmpeg`),"
    "或用環境變數 KARAFORGE_FFMPEG / KARAFORGE_FFPROBE 指定執行檔位置。"
    "執行 `kf doctor` 可以檢查安裝狀態。"
)
_INSTALL_HINT_EN = (
    "Install an ffmpeg build that includes libass (Ubuntu/Debian: `sudo apt install ffmpeg`; "
    "macOS: `brew install ffmpeg`; Windows: `winget install ffmpeg`), or point the "
    "KARAFORGE_FFMPEG / KARAFORGE_FFPROBE environment variables at the executables. "
    "Run `kf doctor` to check your setup."
)


class FFmpegError(KaraForgeError):
    """ffmpeg or ffprobe exited with an error."""

    code = "ffmpeg_failed"


@dataclass(frozen=True)
class FFmpegTools:
    """Resolved executables."""

    ffmpeg: str
    ffprobe: str


@dataclass(frozen=True)
class FFmpegCapabilities:
    """What the located ffmpeg build can do."""

    version: str
    filters: frozenset[str]
    encoders: frozenset[str]

    @property
    def has_libass(self) -> bool:
        """Whether the ``ass`` filter (libass) is available — required for burning subtitles."""
        return "ass" in self.filters


def _locate(name: str, env_var: str) -> str | None:
    override = os.environ.get(env_var)
    if override:
        resolved = shutil.which(override)
        return resolved if resolved else None
    found = shutil.which(name)
    if found:
        return found
    for candidate in (paths.bin_dir() / name, paths.bin_dir() / f"{name}.exe"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_tools() -> FFmpegTools:
    """Locate ffmpeg and ffprobe.

    Raises:
        ToolMissingError: If either executable cannot be found.
    """
    ffmpeg = _locate("ffmpeg", ENV_FFMPEG)
    ffprobe = _locate("ffprobe", ENV_FFPROBE)
    if ffmpeg is None or ffprobe is None:
        missing = "ffmpeg" if ffmpeg is None else "ffprobe"
        raise ToolMissingError(
            f"找不到 {missing}。",
            f"Could not find {missing}.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
        )
    return FFmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe)


def _run_text(command: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise ToolMissingError(
            f"無法執行 {command[0]}。",
            f"Could not execute {command[0]}.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
            detail=str(exc),
        ) from exc
    if completed.returncode != 0:
        raise FFmpegError(
            f"{Path(command[0]).name} 執行失敗。",
            f"{Path(command[0]).name} failed.",
            detail=f"command: {' '.join(command)}\n{completed.stderr.strip()[-2000:]}",
        )
    return completed.stdout


def _parse_listing(text: str) -> frozenset[str]:
    """Parse the name column out of ``ffmpeg -filters`` / ``-encoders`` output."""
    names: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        # Rows look like " V....D libx264   description" or " T.C ass   V->V  description".
        if len(parts) >= 2 and line.startswith(" ") and not parts[0].startswith("-"):
            flags, name = parts[0], parts[1]
            if "=" not in flags and name != "=":
                names.add(name)
    return frozenset(names)


@functools.lru_cache(maxsize=4)
def _capabilities_for(ffmpeg: str) -> FFmpegCapabilities:
    version_line = _run_text([ffmpeg, "-hide_banner", "-version"]).splitlines()[0]
    parts = version_line.split()
    version = parts[2] if len(parts) >= 3 else version_line
    filters = _parse_listing(_run_text([ffmpeg, "-hide_banner", "-filters"]))
    encoders = _parse_listing(_run_text([ffmpeg, "-hide_banner", "-encoders"]))
    return FFmpegCapabilities(version=version, filters=filters, encoders=encoders)


def capabilities(tools: FFmpegTools | None = None) -> FFmpegCapabilities:
    """Return (cached) capabilities of the located ffmpeg build."""
    resolved = tools or find_tools()
    return _capabilities_for(resolved.ffmpeg)


def require_libass(tools: FFmpegTools | None = None) -> None:
    """Raise :class:`ToolMissingError` when ffmpeg was built without libass."""
    if not capabilities(tools).has_libass:
        raise ToolMissingError(
            "這個 ffmpeg 沒有內建 libass,無法燒錄 KTV 字幕。",
            "This ffmpeg build lacks libass, which is required to burn in karaoke subtitles.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
        )


# ----------------------------------------------------------------------------- probing


class _ProbeDisposition(BaseModel):
    model_config = ConfigDict(extra="ignore")
    attached_pic: int = 0


class _ProbeStream(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int = 0
    codec_type: str = ""
    codec_name: str = ""
    width: int | None = None
    height: int | None = None
    sample_rate: str | None = None
    channels: int | None = None
    duration: str | None = None
    bit_rate: str | None = None
    r_frame_rate: str | None = None
    avg_frame_rate: str | None = None
    disposition: _ProbeDisposition = Field(default_factory=_ProbeDisposition)


class _ProbeFormat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    format_name: str = ""
    duration: str | None = None
    bit_rate: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class _ProbeOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    streams: list[_ProbeStream] = Field(default_factory=list[_ProbeStream])
    format: _ProbeFormat = Field(default_factory=_ProbeFormat)


@dataclass(frozen=True)
class StreamInfo:
    """One audio or video stream of a media file."""

    index: int
    kind: str
    codec: str
    width: int | None = None
    height: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    frame_rate: float | None = None
    duration_ms: int | None = None
    bit_rate: int | None = None
    is_cover_art: bool = False


@dataclass(frozen=True)
class MediaInfo:
    """Summary of a media file as reported by ffprobe."""

    format_name: str
    duration_ms: int
    streams: tuple[StreamInfo, ...]
    tags: dict[str, str]

    @property
    def audio(self) -> StreamInfo | None:
        """The first audio stream, if any."""
        return next((s for s in self.streams if s.kind == "audio"), None)

    @property
    def video(self) -> StreamInfo | None:
        """The first real video stream (embedded cover art does not count)."""
        return next((s for s in self.streams if s.kind == "video" and not s.is_cover_art), None)

    @property
    def cover_art(self) -> StreamInfo | None:
        """An embedded cover image, if any."""
        return next((s for s in self.streams if s.kind == "video" and s.is_cover_art), None)


def _to_ms(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return round(float(value) * 1000)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _to_rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        rate = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def probe(path: Path, tools: FFmpegTools | None = None) -> MediaInfo:
    """Inspect a media file with ffprobe.

    Args:
        path: File to inspect.
        tools: Pre-resolved executables (looked up when omitted).

    Raises:
        MediaError: If the file does not exist or ffprobe cannot read it.
    """
    resolved = tools or find_tools()
    if not path.is_file():
        raise MediaError(
            f"找不到媒體檔:{path}",
            f"Media file not found: {path}",
        )
    command = [
        resolved.ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        raw = _run_text(command)
    except FFmpegError as exc:
        raise MediaError(
            f"無法讀取媒體檔:{path.name}。檔案可能損毀,或不是支援的影音格式。",
            f"Cannot read media file: {path.name}. It may be corrupt or not an audio/video file.",
            detail=exc.detail,
        ) from exc
    parsed = _ProbeOutput.model_validate_json(raw)
    streams: list[StreamInfo] = []
    for stream in parsed.streams:
        if stream.codec_type not in {"audio", "video"}:
            continue
        streams.append(
            StreamInfo(
                index=stream.index,
                kind=stream.codec_type,
                codec=stream.codec_name,
                width=stream.width,
                height=stream.height,
                sample_rate=_to_int(stream.sample_rate),
                channels=stream.channels,
                frame_rate=_to_rate(stream.avg_frame_rate) or _to_rate(stream.r_frame_rate),
                duration_ms=_to_ms(stream.duration),
                bit_rate=_to_int(stream.bit_rate),
                is_cover_art=bool(stream.disposition.attached_pic),
            )
        )
    duration_ms = _to_ms(parsed.format.duration)
    if duration_ms is None:
        duration_ms = max((s.duration_ms or 0 for s in streams), default=0)
    tags = {key.lower(): value for key, value in parsed.format.tags.items()}
    return MediaInfo(
        format_name=parsed.format.format_name,
        duration_ms=duration_ms,
        streams=tuple(streams),
        tags=tags,
    )


# ----------------------------------------------------------------------------- running


def _watch_cancel(process: subprocess.Popen[str], cancel: CancelToken) -> None:
    while process.poll() is None:
        if cancel.wait(0.2):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            return


def _drain(stream: IO[str] | None, sink: deque[str]) -> None:
    if stream is None:
        return
    for line in stream:
        sink.append(line.rstrip())


def run_ffmpeg(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    duration_ms: int | None = None,
    progress: ProgressFn = null_progress,
    message: str = "",
    cancel: CancelToken | None = None,
    tools: FFmpegTools | None = None,
) -> None:
    """Run ffmpeg to completion, reporting progress and honouring cancellation.

    ``-hide_banner -nostdin -y -loglevel error -progress pipe:1 -nostats`` are prepended, so
    ``args`` should contain only inputs, filters and outputs.

    Args:
        args: ffmpeg arguments after the global options.
        cwd: Working directory.  Filter graphs should reference files relative to it so that
            no path escaping is needed.
        duration_ms: Expected output duration, used to turn ffmpeg's timestamps into a
            fraction.  Without it only the final ``1.0`` is reported.
        progress: Progress callback.
        message: Message passed along with each progress report.
        cancel: Token that terminates the process when cancelled.
        tools: Pre-resolved executables (looked up when omitted).

    Raises:
        JobCancelledError: If ``cancel`` fired while ffmpeg was running.
        FFmpegError: If ffmpeg exits with a non-zero status.
    """
    resolved = tools or find_tools()
    command = [
        resolved.ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        *args,
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise ToolMissingError(
            "無法執行 ffmpeg。",
            "Could not execute ffmpeg.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
            detail=str(exc),
        ) from exc

    stderr_tail: deque[str] = deque(maxlen=40)
    stderr_thread = threading.Thread(target=_drain, args=(process.stderr, stderr_tail), daemon=True)
    stderr_thread.start()
    if cancel is not None:
        threading.Thread(target=_watch_cancel, args=(process, cancel), daemon=True).start()

    assert process.stdout is not None
    for line in process.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and duration_ms:
            try:
                done_ms = int(value) / 1000
            except ValueError:
                continue
            progress(min(0.999, max(0.0, done_ms / duration_ms)), message)
    return_code = process.wait()
    stderr_thread.join(timeout=5)

    if cancel is not None and cancel.cancelled:
        raise JobCancelledError
    if return_code != 0:
        raise FFmpegError(
            "ffmpeg 執行失敗。",
            "ffmpeg failed.",
            detail=f"exit code {return_code}\ncommand: {' '.join(command)}\n"
            + "\n".join(stderr_tail),
        )
    progress(1.0, message)
