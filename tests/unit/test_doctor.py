"""Unit tests for karaforge.doctor (kf doctor checks, all external dependencies patched)."""

from __future__ import annotations

import platform
import types
from pathlib import Path

import pytest

from karaforge import doctor
from karaforge.doctor import Check, check_ffmpeg, check_home, check_python, run_checks, worst
from karaforge.tools.ffmpeg import FFmpegCapabilities, FFmpegError, FFmpegTools
from support import install_fake_ytdlp

FAKE_TOOLS = FFmpegTools(ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe")
GOOD_CAPABILITIES = FFmpegCapabilities(
    version="7.1",
    filters=frozenset({"ass"}),
    encoders=frozenset({"libx264", "aac", "h264_nvenc"}),
)


def fake_find_tools() -> FFmpegTools:
    return FAKE_TOOLS


def fake_capabilities(tools: FFmpegTools | None = None) -> FFmpegCapabilities:
    assert tools == FAKE_TOOLS
    return GOOD_CAPABILITIES


@pytest.fixture
def good_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point check_ffmpeg at a libass-capable fake ffmpeg build."""
    monkeypatch.setattr("karaforge.tools.ffmpeg.find_tools", fake_find_tools)
    monkeypatch.setattr("karaforge.tools.ffmpeg.capabilities", fake_capabilities)


def test_check_to_dict_has_all_six_keys() -> None:
    check = Check("python", "ok", "中文訊息", "English message", "中文提示", "English hint")
    result = check.to_dict()
    assert result == {
        "name": "python",
        "status": "ok",
        "message_zh": "中文訊息",
        "message_en": "English message",
        "hint_zh": "中文提示",
        "hint_en": "English hint",
    }


def test_check_to_dict_hints_default_to_none() -> None:
    result = Check("ffmpeg", "ok", "中文", "English").to_dict()
    assert result["hint_zh"] is None
    assert result["hint_en"] is None


def test_worst_fail_beats_warn_and_ok() -> None:
    checks = [
        Check("a", "ok", "中", "en"),
        Check("b", "warn", "中", "en"),
        Check("c", "fail", "中", "en"),
    ]
    assert worst(checks) == "fail"


def test_worst_warn_without_fail() -> None:
    checks = [Check("a", "ok", "中", "en"), Check("b", "warn", "中", "en")]
    assert worst(checks) == "warn"


def test_worst_all_ok() -> None:
    assert worst([Check("a", "ok", "中", "en"), Check("b", "ok", "中", "en")]) == "ok"


def test_worst_empty_list_is_ok() -> None:
    assert worst([]) == "ok"


def test_check_python_ok_on_current_interpreter() -> None:
    check = check_python()
    assert check.name == "python"
    assert check.status == "ok"
    version = platform.python_version()
    assert version in check.message_zh
    assert version in check.message_en


def test_check_python_fails_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "sys", types.SimpleNamespace(version_info=(3, 10, 0)), raising=True)
    check = check_python()
    assert check.status == "fail"
    assert "3.10.0" in check.message_en
    assert "3.11" in check.message_en  # the minimum version is named in the message


def test_check_ffmpeg_all_ok_with_full_capabilities(good_ffmpeg: None) -> None:
    checks = check_ffmpeg()
    by_name = {check.name: check for check in checks}
    # No "encoders" entry: that one only appears when libx264 or aac is missing.
    assert set(by_name) == {"ffmpeg", "libass", "hardware-encoders"}
    assert all(check.status == "ok" for check in checks)
    assert "7.1" in by_name["ffmpeg"].message_en
    assert "/usr/bin/ffmpeg" in by_name["ffmpeg"].message_en
    assert "h264_nvenc" in by_name["hardware-encoders"].message_en


def test_check_ffmpeg_fails_without_libass(
    monkeypatch: pytest.MonkeyPatch, good_ffmpeg: None
) -> None:
    no_ass = FFmpegCapabilities(
        version="7.1",
        filters=frozenset({"subtitles"}),
        encoders=frozenset({"libx264", "aac"}),
    )

    def fake_no_ass(tools: FFmpegTools | None = None) -> FFmpegCapabilities:
        return no_ass

    monkeypatch.setattr("karaforge.tools.ffmpeg.capabilities", fake_no_ass)
    libass = next(check for check in check_ffmpeg() if check.name == "libass")
    assert libass.status == "fail"
    assert libass.hint_zh is not None
    assert libass.hint_en is not None


def test_check_ffmpeg_fails_without_libx264(
    monkeypatch: pytest.MonkeyPatch, good_ffmpeg: None
) -> None:
    no_x264 = FFmpegCapabilities(
        version="7.1",
        filters=frozenset({"ass"}),
        encoders=frozenset({"aac"}),
    )

    def fake_no_x264(tools: FFmpegTools | None = None) -> FFmpegCapabilities:
        return no_x264

    monkeypatch.setattr("karaforge.tools.ffmpeg.capabilities", fake_no_x264)
    encoders = [check for check in check_ffmpeg() if check.name == "encoders"]
    assert len(encoders) == 1
    assert encoders[0].status == "fail"
    assert "libx264" in encoders[0].message_en
    # aac is present, so it is not listed as missing
    assert "aac" not in encoders[0].message_zh


def test_check_ffmpeg_reports_find_tools_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_missing() -> FFmpegTools:
        raise FFmpegError("找不到", "not found", hint_zh="裝", hint_en="install")

    monkeypatch.setattr("karaforge.tools.ffmpeg.find_tools", raise_missing)
    checks = check_ffmpeg()
    assert len(checks) == 1
    assert checks[0].name == "ffmpeg"
    assert checks[0].status == "fail"
    assert checks[0].message_zh == "找不到"
    assert checks[0].message_en == "not found"
    assert checks[0].hint_zh == "裝"
    assert checks[0].hint_en == "install"


def test_check_home_reports_env_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "還不存在" / "home"
    monkeypatch.setenv("KARAFORGE_HOME", str(home))
    check = check_home()
    assert check.name == "home"
    assert check.status == "ok"
    assert str(home) in check.message_zh
    assert str(home) in check.message_en


def test_run_checks_without_models_has_no_model_checks(
    good_ffmpeg: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_device = Check("device", "ok", "中文裝置", "device")

    def fake_device() -> Check:
        return fixed_device

    monkeypatch.setattr(doctor, "check_device", fake_device, raising=True)
    checks = run_checks(models=False)
    assert checks
    assert not [check for check in checks if check.name.startswith("models:")]
    names = {check.name for check in checks}
    assert {"python", "ffmpeg", "device", "fonts", "themes", "home"} <= names


def test_hardware_encoders_are_not_claimed_to_work(good_ffmpeg: None) -> None:
    check = next(item for item in check_ffmpeg() if item.name == "hardware-encoders")
    # Being built into ffmpeg does not make an encoder usable on this machine.
    assert "matching hardware" in check.message_en
    assert "取決於" in check.message_zh


def test_check_models_lists_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from karaforge import models
    from karaforge.models.registry import ModelSpec

    def nothing_installed(spec: ModelSpec) -> bool:
        return False

    monkeypatch.setattr(models, "is_installed", nothing_installed)
    by_name = {check.name: check for check in doctor.check_models()}
    for profile in ("cpu-lite", "balanced", "gpu-quality"):
        check = by_name[f"models:{profile}"]
        assert check.status in ("warn", "fail")
        assert f"kf models download --profile {profile}" in (check.hint_en or "")
    assert "whisper-base" in by_name["models:cpu-lite"].message_en
    assert "wav2vec2-zh" in by_name["models:balanced"].message_en

    def everything_installed(spec: ModelSpec) -> bool:
        return True

    monkeypatch.setattr(models, "is_installed", everything_installed)
    checks = doctor.check_models()
    assert all(check.status == "ok" for check in checks)
    assert "qwen" in {check.name for check in checks}


def test_check_device_reports_the_cpu_as_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    from karaforge import device
    from karaforge.device import DeviceChoice

    def cpu_only(preference: str = "auto") -> DeviceChoice:
        return DeviceChoice("cpu", "CPU")

    monkeypatch.setattr(device, "resolve_device", cpu_only)
    check = doctor.check_device()
    assert check.status == "warn"
    assert "CPU" in check.message_en
    assert "--extra cuda" in (check.hint_en or "")

    # A CUDA build that finds no card points at the driver / container runtime instead.
    import torch

    monkeypatch.setattr(torch, "__version__", "2.14.1+cu126")
    check = doctor.check_device()
    assert check.status == "warn"
    assert "nvidia-container-toolkit" in (check.hint_en or "")
    assert "--extra cuda" not in (check.hint_en or "")
    monkeypatch.undo()
    monkeypatch.setattr(device, "resolve_device", cpu_only)

    def with_gpu(preference: str = "auto") -> DeviceChoice:
        return DeviceChoice("cuda", "Test GPU")

    monkeypatch.setattr(device, "resolve_device", with_gpu)
    check = doctor.check_device()
    assert check.status == "ok"
    assert "Test GPU" in check.message_en


def test_check_ytdlp_is_optional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("KARAFORGE_YTDLP", raising=False)
    missing = doctor.check_ytdlp()
    assert missing.status == "ok"  # uploading files works without it
    assert missing.hint_zh is not None and "brew install yt-dlp" in missing.hint_zh
    for name, value in install_fake_ytdlp(tmp_path / "bin").items():
        monkeypatch.setenv(name, value)
    found = doctor.check_ytdlp()
    assert found.status == "ok" and found.hint_en is None
    assert "yt-dlp 2099.01.01" in found.message_en
