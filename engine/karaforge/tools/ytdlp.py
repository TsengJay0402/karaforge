"""Locate and run ``yt-dlp``: read what a video link points to, and download it.

yt-dlp is an optional external program, like ffmpeg: the user installs it (and keeps it up to
date, since video sites change often).  Lookup order: the ``KARAFORGE_YTDLP`` environment
variable, then ``PATH``, then ``$KARAFORGE_HOME/bin``.

Downloads ask for at most 1080p, preferring H.264 video and stereo AAC audio merged into an
MP4: that plays in every browser and decodes everywhere, and more is wasted on a background.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import IO, Any, cast
from urllib.parse import urlsplit

from karaforge import paths
from karaforge.errors import JobCancelledError, KaraForgeError, ToolMissingError
from karaforge.runtime import CancelToken, ProgressFn, null_progress

ENV_YTDLP = "KARAFORGE_YTDLP"
OUTPUT_STEM = "media"
"""Downloads are written as ``media.<ext>`` in the folder they are asked for."""
PROBE_TIMEOUT_S = 120.0
FORMAT_ARGS = (
    "--format",
    "bv*+ba/b",
    "--format-sort",
    "res:1080,vcodec:h264,acodec:aac,channels:2",
    "--merge-output-format",
    "mp4",
)
_COMMON_ARGS = ("--ignore-config", "--no-playlist", "--no-colors")
_DOWNLOAD_SHARE = 0.95
"""Share of the progress bar for the download itself; the rest is merging video and audio."""
_LEFTOVERS = (".part", ".ytdl", ".temp")

_INSTALL_HINT_ZH = (
    "請先安裝 yt-dlp（macOS：`brew install yt-dlp`；其他系統：`pipx install yt-dlp`），"
    "或用環境變數 KARAFORGE_YTDLP 指定執行檔位置。YouTube 另外需要 JavaScript 執行環境"
    "（例如 deno）。執行 `kf doctor` 可以檢查安裝狀態。"
)
_INSTALL_HINT_EN = (
    "Install yt-dlp (macOS: `brew install yt-dlp`; elsewhere: `pipx install yt-dlp`), or point "
    "the KARAFORGE_YTDLP environment variable at the executable. YouTube also needs a "
    "JavaScript runtime such as deno. Run `kf doctor` to check your setup."
)
_UPDATE_HINT_ZH = (
    "請確認網址在瀏覽器裡可以播放。影片網站常常改版，下載失敗時先把 yt-dlp 更新到最新版"
    "（`yt-dlp -U`、`brew upgrade yt-dlp` 或 `pipx upgrade yt-dlp`）再試一次。"
)
_UPDATE_HINT_EN = (
    "Check that the link plays in a browser. Video sites change often: when a download fails, "
    "update yt-dlp (`yt-dlp -U`, `brew upgrade yt-dlp` or `pipx upgrade yt-dlp`) and try again."
)


class YtDlpError(KaraForgeError):
    """yt-dlp could not read or download a link."""

    code = "download_failed"


@dataclass(frozen=True)
class RemoteMedia:
    """What a video link points to, as far as the project wizard needs to know."""

    url: str
    """The page address yt-dlp settled on (a short link becomes the full one)."""
    id: str
    title: str
    """Suggested song title: the track name when the site knows it, else the video title."""
    artist: str
    """Suggested artist: the artist when the site knows it, else the uploader."""
    uploader: str
    duration_ms: int | None
    thumbnail: str | None
    extractor: str
    has_video: bool
    size_bytes: int | None
    """Approximate size of what would be downloaded, when the site says."""

    def to_dict(self) -> dict[str, Any]:
        """The description as a JSON-serialisable mapping."""
        return asdict(self)


def is_url(text: str) -> bool:
    """Whether ``text`` is an http(s) address (the only kind handed to yt-dlp)."""
    parts = urlsplit(text.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def require_url(url: str) -> str:
    """``url`` without surrounding blanks.

    Raises:
        YtDlpError: If it is not an http(s) address.
    """
    cleaned = url.strip()
    if not is_url(cleaned):
        raise YtDlpError(
            "請貼上以 http:// 或 https:// 開頭的影片網址。",
            "Paste a video link that starts with http:// or https://.",
        )
    return cleaned


def find_ytdlp() -> str:
    """Locate the yt-dlp executable.

    Raises:
        ToolMissingError: If it cannot be found.
    """
    override = os.environ.get(ENV_YTDLP)
    found: str | None
    if override:
        found = shutil.which(override)
    else:
        found = shutil.which("yt-dlp")
        if found is None:
            for candidate in (paths.bin_dir() / "yt-dlp", paths.bin_dir() / "yt-dlp.exe"):
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    found = str(candidate)
                    break
    if found is None:
        raise ToolMissingError(
            "找不到 yt-dlp，無法從網址下載影片。",
            "yt-dlp was not found, so videos cannot be downloaded from a link.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
        )
    return found


def version(executable: str | None = None) -> str:
    """The version string of yt-dlp (e.g. ``2026.10.26``).

    Raises:
        ToolMissingError: If yt-dlp is missing or cannot be run.
    """
    command = [executable or find_ytdlp(), "--version"]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolMissingError(
            "無法執行 yt-dlp。",
            "Could not execute yt-dlp.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
            detail=str(exc),
        ) from exc
    if completed.returncode != 0:
        raise ToolMissingError(
            "無法執行 yt-dlp。",
            "Could not execute yt-dlp.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
            detail=completed.stderr.strip()[-2000:],
        )
    return completed.stdout.strip()


def _failure(lines: Sequence[str], *, reading: bool) -> YtDlpError:
    """An error that names what yt-dlp complained about."""
    errors = [line.strip() for line in lines if line.strip().startswith("ERROR:")]
    reason = errors[-1].removeprefix("ERROR:").strip() if errors else ""
    # "[youtube] abc123: Video unavailable" -> "Video unavailable"
    if reason.startswith("[") and ": " in reason:
        reason = reason.split(": ", 1)[1]
    if "Unsupported URL" in reason:
        message_zh, message_en = "yt-dlp 不支援這個網址。", "yt-dlp does not support this link."
    elif reading:
        message_zh, message_en = "無法讀取這個網址的影片", "Could not read the video at this link"
    else:
        message_zh, message_en = "無法下載這部影片", "Could not download the video"
    if not message_zh.endswith("。"):
        message_zh += f"：{reason}" if reason else "。"
        message_en += f": {reason}" if reason else "."
    return YtDlpError(
        message_zh,
        message_en,
        hint_zh=_UPDATE_HINT_ZH,
        hint_en=_UPDATE_HINT_EN,
        detail="\n".join(lines[-40:]),
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _suggest(info: dict[str, Any]) -> tuple[str, str]:
    """Song title and artist to suggest for the information yt-dlp gives about a video."""
    title = _text(info.get("track")) or _text(info.get("title"))
    artist = _text(info.get("artist")) or _text(info.get("creator"))
    if not artist:
        uploader = _text(info.get("uploader")) or _text(info.get("channel"))
        # YouTube's automatic music channels are called "<artist> - Topic".
        artist = uploader.removesuffix(" - Topic")
    return title, artist


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(value)


def describe(info: dict[str, Any]) -> RemoteMedia:
    """Turn yt-dlp's JSON about one video into a :class:`RemoteMedia`.

    Raises:
        YtDlpError: If the link is a playlist or a live stream rather than one video.
    """
    if info.get("_type") == "playlist":
        raise YtDlpError(
            "這是播放清單的網址，請貼上單一影片的網址。",
            "This links to a playlist; paste the link of a single video.",
        )
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise YtDlpError(
            "直播無法下載，請等直播結束、有了錄影之後再試。",
            "Live streams cannot be downloaded; try again once the recording is available.",
        )
    title, artist = _suggest(info)
    duration = info.get("duration")
    formats = cast(list[dict[str, Any]], info.get("requested_formats") or [info])
    has_video = any(_text(item.get("vcodec")) not in ("", "none") for item in formats)
    return RemoteMedia(
        url=_text(info.get("webpage_url")) or _text(info.get("original_url")),
        id=_text(info.get("id")),
        title=title,
        artist=artist,
        uploader=_text(info.get("uploader")) or _text(info.get("channel")),
        duration_ms=round(duration * 1000) if isinstance(duration, int | float) else None,
        thumbnail=_text(info.get("thumbnail")) or None,
        extractor=_text(info.get("extractor_key")) or _text(info.get("extractor")),
        has_video=has_video,
        size_bytes=_int(info.get("filesize_approx")) or _int(info.get("filesize")),
    )


def probe(url: str, *, executable: str | None = None) -> RemoteMedia:
    """Ask yt-dlp what ``url`` points to, without downloading it.

    Raises:
        YtDlpError: If the link is not an http(s) address, is not one video, or yt-dlp fails.
        ToolMissingError: If yt-dlp is missing.
    """
    address = require_url(url)
    command = [
        executable or find_ytdlp(),
        *_COMMON_ARGS,
        "--flat-playlist",
        "--skip-download",
        "--dump-single-json",
        *FORMAT_ARGS,
        "--",
        address,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PROBE_TIMEOUT_S, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise YtDlpError(
            "讀取影片資訊逾時。",
            "Reading the video information timed out.",
            hint_zh=_UPDATE_HINT_ZH,
            hint_en=_UPDATE_HINT_EN,
        ) from exc
    except OSError as exc:
        raise ToolMissingError(
            "無法執行 yt-dlp。",
            "Could not execute yt-dlp.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
            detail=str(exc),
        ) from exc
    if completed.returncode != 0:
        raise _failure(completed.stderr.splitlines(), reading=True)
    try:
        info = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        lines = [*completed.stderr.splitlines(), f"(invalid JSON: {exc})"]
        raise _failure(lines, reading=True) from exc
    if not isinstance(info, dict):
        raise _failure(["(yt-dlp did not describe a video)"], reading=True)
    media = describe(cast(dict[str, Any], info))
    return media if media.url else replace(media, url=address)


# ----------------------------------------------------------------------------- download


def _json_token(text: str) -> object:
    """One value of a progress line; yt-dlp writes ``NA`` for a value it does not know."""
    try:
        return cast(object, json.loads(text))
    except json.JSONDecodeError:
        return None


class _DownloadProgress:
    """Turns yt-dlp's machine-readable lines into one fraction for the whole download.

    A link usually downloads as two files (video, then audio) that are merged afterwards; each
    reports its own bytes.  The parts are weighted by their sizes when those are known.
    """

    def __init__(self, report: ProgressFn) -> None:
        self._report = report
        self.info: dict[str, Any] = {}
        self._parts: list[str] = []
        self._sizes: dict[str, float] = {}
        self._done: dict[str, float] = {}

    def line(self, text: str) -> None:
        kind, _, rest = text.strip().partition(" ")
        if kind == "KFINFO":
            value = _json_token(rest)
            if isinstance(value, dict):
                self.info = cast(dict[str, Any], value)
                self._parts = [
                    part for part in _text(self.info.get("format_id")).split("+") if part
                ]
        elif kind == "KFSIZES":
            sizes = _json_token(rest)
            if isinstance(sizes, list):
                for part, size in zip(self._parts, cast(list[object], sizes), strict=False):
                    if isinstance(size, int | float) and size > 0:
                        self._sizes[part] = float(size)
        elif kind == "KFPROG":
            self._progress(rest.split())
        elif kind == "KFPOST":
            status, _, processor = rest.partition(" ")
            if _json_token(status) == "started" and "Merger" in processor:
                self._report(_DOWNLOAD_SHARE + 0.01, "合併影音 / merging video and audio")

    def _progress(self, tokens: list[str]) -> None:
        if len(tokens) < 5:
            return
        part = str(_json_token(tokens[0]) or "")
        downloaded, total, estimate = (_json_token(token) for token in tokens[2:5])
        if part not in self._parts:
            self._parts.append(part)
        size = next((v for v in (total, estimate) if isinstance(v, int | float) and v > 0), None)
        if size is not None:
            self._sizes[part] = float(size)
        if isinstance(downloaded, int | float):
            self._done[part] = float(downloaded)
        self._report(_DOWNLOAD_SHARE * self.fraction(), self._message())

    def fraction(self) -> float:
        """How much of the download is done, from 0 to 1."""
        if not self._parts:
            return 0.0
        if all(part in self._sizes for part in self._parts):
            total = sum(self._sizes[part] for part in self._parts)
            done = sum(min(self._done.get(part, 0.0), self._sizes[part]) for part in self._parts)
            return min(1.0, done / total) if total > 0 else 0.0
        shares = [
            min(1.0, self._done.get(part, 0.0) / self._sizes[part]) if part in self._sizes else 0.0
            for part in self._parts
        ]
        return sum(shares) / len(shares)

    def _message(self) -> str:
        done = sum(self._done.values()) / 1e6
        if self._parts and all(part in self._sizes for part in self._parts):
            total = sum(self._sizes[part] for part in self._parts) / 1e6
            return f"下載中 / downloading {done:.1f} / {total:.1f} MB"
        return f"下載中 / downloading {done:.1f} MB"


def _drain(stream: IO[str] | None, sink: deque[str]) -> None:
    if stream is None:
        return
    for line in stream:
        sink.append(line.rstrip())


def _watch_cancel(process: subprocess.Popen[str], cancel: CancelToken) -> None:
    while process.poll() is None:
        if cancel.wait(0.2):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            return


def _ffmpeg_location() -> list[str]:
    """Point yt-dlp at KaraForge's ffmpeg when it would not find one by itself."""
    if shutil.which("ffmpeg"):
        return []
    from karaforge.tools import ffmpeg

    try:
        return ["--ffmpeg-location", ffmpeg.find_tools().ffmpeg]
    except KaraForgeError:
        return []


def _downloaded_file(folder: Path) -> Path | None:
    for candidate in sorted(folder.iterdir()):
        if (
            candidate.is_file()
            and candidate.stem == OUTPUT_STEM
            and candidate.suffix.lower() not in _LEFTOVERS
        ):
            return candidate
    return None


@dataclass(frozen=True)
class Download:
    """A finished download."""

    path: Path
    title: str
    """Suggested song title (see :class:`RemoteMedia`)."""
    artist: str


def download(
    url: str,
    folder: Path,
    *,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
    executable: str | None = None,
) -> Download:
    """Download the video at ``url`` into ``folder`` as ``media.<ext>``.

    Args:
        url: Page address of one video.
        folder: Existing folder to write into (best empty: it may receive temporary files).
        progress: Progress callback.
        cancel: Token that stops yt-dlp when cancelled.
        executable: Pre-resolved yt-dlp (looked up when omitted).

    Raises:
        YtDlpError: If the link is not an http(s) address or the download fails.
        ToolMissingError: If yt-dlp is missing.
        JobCancelledError: If ``cancel`` fired while downloading.
    """
    address = require_url(url)
    command = [
        executable or find_ytdlp(),
        *_COMMON_ARGS,
        "--newline",
        "--progress",
        *FORMAT_ARGS,
        "--print",
        "before_dl:KFINFO %(.{format_id,title,track,artist,creator,uploader,channel})j",
        "--print",
        "before_dl:KFSIZES %(requested_formats.:.filesize_approx)j",
        "--progress-template",
        "download:KFPROG %(info.format_id)j %(progress.status)j %(progress.downloaded_bytes)j "
        "%(progress.total_bytes)j %(progress.total_bytes_estimate)j",
        "--progress-template",
        "postprocess:KFPOST %(progress.status)j %(progress.postprocessor)j",
        *_ffmpeg_location(),
        "--paths",
        str(folder),
        "--output",
        f"{OUTPUT_STEM}.%(ext)s",
        "--",
        address,
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise ToolMissingError(
            "無法執行 yt-dlp。",
            "Could not execute yt-dlp.",
            hint_zh=_INSTALL_HINT_ZH,
            hint_en=_INSTALL_HINT_EN,
            detail=str(exc),
        ) from exc

    stderr_tail: deque[str] = deque(maxlen=60)
    stderr_thread = threading.Thread(target=_drain, args=(process.stderr, stderr_tail), daemon=True)
    stderr_thread.start()
    if cancel is not None:
        threading.Thread(target=_watch_cancel, args=(process, cancel), daemon=True).start()

    tracker = _DownloadProgress(progress)
    progress(0.0, "讀取影片資訊 / reading the video information")
    assert process.stdout is not None
    for line in process.stdout:
        tracker.line(line)
    return_code = process.wait()
    stderr_thread.join(timeout=5)

    if cancel is not None and cancel.cancelled:
        raise JobCancelledError
    if return_code != 0:
        raise _failure(list(stderr_tail), reading=False)
    path = _downloaded_file(folder)
    if path is None:
        raise _failure([*stderr_tail, "(yt-dlp finished but wrote no media file)"], reading=False)
    progress(1.0, "")
    title, artist = _suggest(tracker.info)
    return Download(path=path, title=title, artist=artist)
