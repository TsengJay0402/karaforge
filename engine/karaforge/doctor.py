"""Environment checks behind ``kf doctor``.

Every check answers one question a user who cannot get KaraForge to work would ask — is
ffmpeg there, can it burn subtitles, is a GPU being used, are the models downloaded, is there
room for them — with a message in both languages and, where something is wrong, what to do.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from karaforge import __version__, paths
from karaforge.errors import KaraForgeError

Status = Literal["ok", "warn", "fail"]
HARDWARE_ENCODERS = ("h264_nvenc", "h264_videotoolbox", "h264_qsv", "h264_vaapi", "h264_amf")
_MIN_PYTHON = (3, 11)


@dataclass(frozen=True)
class Check:
    """Outcome of one check."""

    name: str
    status: Status
    message_zh: str
    message_en: str
    hint_zh: str | None = None
    hint_en: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """The check as a JSON-serialisable mapping."""
        return dict(self.__dict__)


def _size(count: int) -> str:
    return f"{count / 1e9:.1f} GB" if count >= 1e9 else f"{count / 1e6:.0f} MB"


def check_python() -> Check:
    """The interpreter version."""
    version = ".".join(str(part) for part in sys.version_info[:3])
    system = f"{platform.system()} {platform.machine()}"
    if sys.version_info[:2] < _MIN_PYTHON:
        return Check(
            "python",
            "fail",
            f"Python {version} 太舊，需要 3.11 以上。",
            f"Python {version} is too old; 3.11 or newer is required.",
        )
    return Check(
        "python",
        "ok",
        f"KaraForge {__version__}、Python {version}（{system}）",
        f"KaraForge {__version__}, Python {version} ({system})",
    )


def check_ffmpeg() -> list[Check]:
    """ffmpeg, its libass support and its encoders."""
    from karaforge.tools import ffmpeg

    try:
        tools = ffmpeg.find_tools()
        capabilities = ffmpeg.capabilities(tools)
    except KaraForgeError as error:
        return [
            Check(
                "ffmpeg", "fail", error.message_zh, error.message_en, error.hint_zh, error.hint_en
            )
        ]
    checks = [
        Check(
            "ffmpeg",
            "ok",
            f"ffmpeg {capabilities.version}（{tools.ffmpeg}）",
            f"ffmpeg {capabilities.version} ({tools.ffmpeg})",
        )
    ]
    if capabilities.has_libass:
        checks.append(
            Check("libass", "ok", "ffmpeg 內建 libass，可以燒錄字幕。", "ffmpeg has libass.")
        )
    else:
        checks.append(
            Check(
                "libass",
                "fail",
                "這個 ffmpeg 沒有 libass，無法把字幕燒進 MP4。",
                "This ffmpeg lacks libass; lyrics cannot be burned into an MP4.",
                "請安裝含 libass 的 ffmpeg（多數發行版的套件都有）；MKV 與字幕檔的匯出不受影響。",
                "Install an ffmpeg build with libass (most distribution packages have it); "
                "MKV and subtitle-file exports are not affected.",
            )
        )
    missing = [name for name in ("libx264", "aac") if name not in capabilities.encoders]
    if missing:
        checks.append(
            Check(
                "encoders",
                "fail",
                f"ffmpeg 缺少編碼器：{'、'.join(missing)}。",
                f"ffmpeg is missing encoders: {', '.join(missing)}.",
            )
        )
    hardware = [name for name in HARDWARE_ENCODERS if name in capabilities.encoders]
    # Being compiled in says nothing about the machine: the encoder still needs its hardware.
    checks.append(
        Check(
            "hardware-encoders",
            "ok",
            "ffmpeg 內含的硬體編碼器："
            + ("、".join(hardware) + "（能不能用取決於這台機器的硬體）" if hardware else "無"),
            "Hardware encoders built into ffmpeg: "
            + (
                ", ".join(hardware) + " (usable only with matching hardware)"
                if hardware
                else "none"
            ),
        )
    )
    return checks


def check_device() -> Check:
    """Which device the models will run on."""
    from karaforge.device import cpu_threads, resolve_device

    try:
        import torch

        build = str(torch.__version__)
    except ImportError:
        return Check(
            "device",
            "fail",
            "沒有安裝 PyTorch。",
            "PyTorch is not installed.",
            "請執行 uv sync --extra cpu（或 --extra cuda）。",
            "Run uv sync --extra cpu (or --extra cuda).",
        )
    device = resolve_device("auto")
    if device.kind == "cpu":
        if "+cu" in build:
            # The CUDA build is installed and still nothing was found: the card or its driver
            # is not visible (in a container: the runtime was not asked for the GPU).
            hint_zh = (
                "已經安裝 CUDA 版的 PyTorch，但找不到可用的顯示卡；請檢查驅動程式。"
                "在 Docker 裡需要 nvidia-container-toolkit，"
                "並以 --gpus all（或 compose 的 gpu profile）啟動。"
            )
            hint_en = (
                "The CUDA build of PyTorch is installed but no card was found; check the driver. "
                "In Docker this needs the nvidia-container-toolkit and --gpus all "
                "(or the gpu profile of the compose file)."
            )
        else:
            hint_zh = "CPU 可以完成所有工作，只是比較慢。有 NVIDIA 顯示卡時請安裝 --extra cuda。"
            hint_en = (
                "Everything works on a CPU, only slower. With an NVIDIA card install --extra cuda."
            )
        return Check(
            "device",
            "warn",
            f"使用 CPU（{cpu_threads()} 個執行緒，PyTorch {build}）；沒有偵測到可用的 GPU。",
            f"Using the CPU ({cpu_threads()} threads, PyTorch {build}); no usable GPU was found.",
            hint_zh,
            hint_en,
        )
    return Check(
        "device",
        "ok",
        f"使用 {device.kind.upper()}：{device.name}（PyTorch {build}）",
        f"Using {device.kind.upper()}: {device.name} (PyTorch {build})",
    )


def check_fonts_and_themes() -> list[Check]:
    """Bundled fonts and themes."""
    from karaforge.layout.fonts import FontLibrary
    from karaforge.layout.theme import list_themes, load_theme

    faces = FontLibrary().faces
    checks: list[Check] = []
    if faces:
        names = ", ".join(face.family for face in faces)
        checks.append(
            Check("fonts", "ok", f"字型 {len(faces)} 套:{names}", f"{len(faces)} fonts: {names}")
        )
    else:
        checks.append(
            Check(
                "fonts",
                "fail",
                "找不到任何字型。",
                "No fonts were found.",
                f"內建字型應該在 {paths.bundled_dir('fonts')}。",
                f"The bundled fonts should be in {paths.bundled_dir('fonts')}.",
            )
        )
    broken: list[str] = []
    for name in list_themes():
        try:
            theme = load_theme(name)
            FontLibrary().find(theme.font.family)
        except KaraForgeError:
            broken.append(name)
    if broken:
        checks.append(
            Check(
                "themes",
                "warn",
                f"這些主題無法使用：{'、'.join(broken)}。",
                f"These themes cannot be used: {', '.join(broken)}.",
            )
        )
    else:
        count = len(list_themes())
        checks.append(
            Check("themes", "ok", f"主題 {count} 套都可以使用。", f"All {count} themes load.")
        )
    return checks


def _existing_parent() -> Path:
    """The data directory, or the closest folder above it that exists already."""
    probe = paths.home_dir()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def _free_space() -> int:
    """Bytes free on the volume that holds the data directory."""
    return shutil.disk_usage(_existing_parent()).free


def check_home() -> Check:
    """The data directory and the space left in it."""
    home = paths.home_dir()
    writable = os.access(_existing_parent(), os.W_OK)
    free = _free_space()
    if not writable:
        return Check(
            "home",
            "fail",
            f"資料目錄無法寫入：{home}",
            f"The data directory is not writable: {home}",
            "請用 KARAFORGE_HOME 指定一個可以寫入的資料夾。",
            "Point KARAFORGE_HOME at a folder you can write to.",
        )
    return Check(
        "home",
        "ok",
        f"資料目錄 {home}（剩餘空間 {_size(free)}）",
        f"Data directory {home} ({_size(free)} free)",
    )


def check_models() -> list[Check]:
    """Which models each profile still needs."""
    from karaforge.adapters.registry import profile_model_ids, qwen_available, resolve_aligner
    from karaforge.models import get_model, is_installed
    from karaforge.pipeline.profiles import DEFAULT_PROFILE, get_profile, profile_names

    checks: list[Check] = []
    free = _free_space()
    for name in profile_names():
        profile = get_profile(name)
        specs = [get_model(model_id) for model_id in profile_model_ids(profile)]
        missing = [spec for spec in specs if not is_installed(spec)]
        aligner = resolve_aligner(profile.align.aligner)
        if not missing:
            checks.append(
                Check(
                    f"models:{name}",
                    "ok",
                    f"設定檔 {name}（對齊器 {aligner}）：{len(specs)} 個模型都已安裝。",
                    f"Profile {name} (aligner {aligner}): all {len(specs)} models are installed.",
                )
            )
            continue
        need = sum(spec.total_size for spec in missing)
        listed = ", ".join(spec.id for spec in missing)
        status: Status = "warn" if name != DEFAULT_PROFILE or need < free else "fail"
        checks.append(
            Check(
                f"models:{name}",
                status,
                f"設定檔 {name}（對齊器 {aligner}）：還缺 {len(missing)} 個模型"
                f"({_size(need)}):{listed}",
                f"Profile {name} (aligner {aligner}): {len(missing)} models missing "
                f"({_size(need)}): {listed}",
                f"第一次處理時會自動下載，也可以先執行 kf models download --profile {name}。"
                + ("" if need < free else "磁碟空間不足！"),
                f"They are downloaded on first use, or run kf models download --profile {name}."
                + ("" if need < free else " Not enough disk space!"),
            )
        )
    if qwen_available():
        checks.append(
            Check(
                "qwen",
                "ok",
                "已安裝 qwen-asr：可以使用 hybrid 對齊器（gpu-quality 的預設）。",
                "qwen-asr is installed: the hybrid aligner (default of gpu-quality) is available.",
            )
        )
    else:
        checks.append(
            Check(
                "qwen",
                "ok",
                "沒有安裝選用的 qwen-asr:gpu-quality 會改用 CTC 對齊器。",
                "The optional qwen-asr package is not installed: gpu-quality falls back to CTC.",
                "想要較好的英文與中英混雜對齊：uv sync --extra cpu --extra qwen",
                "For better English and mixed-language alignment: uv sync --extra cpu --extra qwen",
            )
        )
    return checks


def check_ytdlp() -> Check:
    """yt-dlp, which is optional: it is only needed to start a project from a video link."""
    from karaforge.tools import ytdlp

    try:
        executable = ytdlp.find_ytdlp()
        version = ytdlp.version(executable)
    except KaraForgeError as error:
        return Check(
            "yt-dlp",
            "ok",
            "沒有安裝選用的 yt-dlp：無法用影片網址建立專案（上傳檔案不受影響）。",
            "The optional yt-dlp is not installed: projects cannot start from a video link "
            "(uploading files is not affected).",
            error.hint_zh,
            error.hint_en,
        )
    return Check(
        "yt-dlp",
        "ok",
        f"yt-dlp {version}（{executable}）：可以用影片網址建立專案。",
        f"yt-dlp {version} ({executable}): projects can start from a video link.",
    )


def run_checks(*, models: bool = True) -> list[Check]:
    """Run every check.

    Args:
        models: Also look at which models are installed (reads the registry and file sizes).
    """
    checks = [
        check_python(),
        *check_ffmpeg(),
        check_ytdlp(),
        check_device(),
        *check_fonts_and_themes(),
        check_home(),
    ]
    if models:
        checks += check_models()
    return checks


def worst(checks: list[Check]) -> Status:
    """The most serious status among ``checks``."""
    if any(check.status == "fail" for check in checks):
        return "fail"
    return "warn" if any(check.status == "warn" for check in checks) else "ok"
