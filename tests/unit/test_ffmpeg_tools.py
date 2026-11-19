from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from karaforge.errors import JobCancelledError, MediaError, ToolMissingError
from karaforge.runtime import CancelToken
from karaforge.tools import ffmpeg


def test_parse_listing_extracts_names() -> None:
    text = (
        "Filters:\n"
        "  T.. = Timeline support\n"
        " ... ass               V->V       Render ASS subtitles.\n"
        " TSC overlay           VV->V      Overlay a video source.\n"
        " ------\n"
        " V....D libx264              libx264 H.264\n"
    )
    assert ffmpeg._parse_listing(text) == {"ass", "overlay", "libx264"}  # pyright: ignore[reportPrivateUsage]


def test_find_tools_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(ffmpeg.ENV_FFMPEG, raising=False)
    monkeypatch.delenv(ffmpeg.ENV_FFPROBE, raising=False)
    with pytest.raises(ToolMissingError) as info:
        ffmpeg.find_tools()
    assert "ffmpeg" in info.value.message_en
    assert info.value.hint_zh is not None


def test_find_tools_in_home_bin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "home" / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("ffmpeg", "ffprobe"):
        tool = bin_dir / name
        tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(ffmpeg.ENV_FFMPEG, raising=False)
    monkeypatch.delenv(ffmpeg.ENV_FFPROBE, raising=False)
    tools = ffmpeg.find_tools()
    assert tools.ffmpeg == str(bin_dir / "ffmpeg")
    assert tools.ffprobe == str(bin_dir / "ffprobe")


def test_env_override_must_exist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ffmpeg.ENV_FFMPEG, str(tmp_path / "nope"))
    with pytest.raises(ToolMissingError):
        ffmpeg.find_tools()


def test_probe_missing_file(tmp_path: Path) -> None:
    tools = ffmpeg.FFmpegTools(ffmpeg="ffmpeg", ffprobe="ffprobe")
    with pytest.raises(MediaError):
        ffmpeg.probe(tmp_path / "missing.mp3", tools)


@pytest.mark.ffmpeg
def test_capabilities_report_libass() -> None:
    caps = ffmpeg.capabilities()
    assert caps.has_libass
    assert "aac" in caps.encoders
    assert caps.version
    ffmpeg.require_libass()


@pytest.mark.ffmpeg
def test_run_and_probe_roundtrip(work_dir: Path) -> None:
    seen: list[float] = []
    ffmpeg.run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3:sample_rate=48000",
            "-ac",
            "2",
            "tone.wav",
        ],
        cwd=work_dir,
        duration_ms=3000,
        progress=lambda fraction, _message: seen.append(fraction),
    )
    assert seen[-1] == 1.0
    assert all(0.0 <= value <= 1.0 for value in seen)
    info = ffmpeg.probe(work_dir / "tone.wav")
    assert info.audio is not None
    assert info.audio.sample_rate == 48000
    assert info.audio.channels == 2
    assert info.video is None
    assert abs(info.duration_ms - 3000) <= 20


@pytest.mark.ffmpeg
def test_probe_rejects_garbage(work_dir: Path) -> None:
    bogus = work_dir / "bogus.mp3"
    bogus.write_bytes(b"this is not audio" * 10)
    with pytest.raises(MediaError) as info:
        ffmpeg.probe(bogus)
    assert "bogus.mp3" in info.value.message_zh


@pytest.mark.ffmpeg
def test_run_failure_carries_detail(work_dir: Path) -> None:
    with pytest.raises(ffmpeg.FFmpegError) as info:
        ffmpeg.run_ffmpeg(["-i", "does-not-exist.wav", "out.wav"], cwd=work_dir)
    assert info.value.detail is not None
    assert "does-not-exist.wav" in info.value.detail


@pytest.mark.ffmpeg
@pytest.mark.slow
def test_cancel_terminates_process(work_dir: Path) -> None:
    token = CancelToken()
    threading.Timer(1.5, token.cancel).start()
    started = time.monotonic()
    with pytest.raises(JobCancelledError):
        # ``-re`` reads the 60 s source in real time, so without cancellation this takes a minute.
        ffmpeg.run_ffmpeg(
            ["-re", "-f", "lavfi", "-i", "sine=frequency=440:duration=60", "slow.wav"],
            cwd=work_dir,
            cancel=token,
        )
    assert time.monotonic() - started < 20
