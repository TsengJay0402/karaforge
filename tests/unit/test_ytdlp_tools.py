"""yt-dlp: finding it, describing a link, downloading with progress — against a stand-in.

The stand-in (``tests/fixtures/fake_yt_dlp.py``) answers the way yt-dlp does for the options
KaraForge passes, so no test touches the network.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from karaforge.errors import JobCancelledError, ToolMissingError
from karaforge.runtime import CancelToken
from karaforge.tools import ytdlp
from support import install_fake_ytdlp

URL = "https://youtu.be/abc123"


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Use the stand-in; returns the file that collects its command lines."""
    media = tmp_path / "song.wav"
    media.write_bytes(b"RIFF-not-really-audio")
    variables = install_fake_ytdlp(tmp_path / "bin", media=media)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("FAKE_YTDLP_MODE", raising=False)
    return Path(variables["FAKE_YTDLP_LOG"])


def calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------------- finding it


def test_only_http_addresses_are_accepted() -> None:
    assert ytdlp.is_url("https://www.youtube.com/watch?v=abc")
    assert ytdlp.is_url("  http://example.com/v  ")
    for bad in ("", "youtube.com/watch?v=abc", "file:///etc/passwd", "--exec=rm", "https://"):
        assert not ytdlp.is_url(bad)
        with pytest.raises(ytdlp.YtDlpError, match="http"):
            ytdlp.require_url(bad)
    assert ytdlp.require_url(" https://a.b/c ") == "https://a.b/c"


def test_a_missing_ytdlp_says_how_to_install_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(ytdlp.ENV_YTDLP, raising=False)
    with pytest.raises(ToolMissingError) as caught:
        ytdlp.find_ytdlp()
    assert caught.value.hint_zh is not None and "brew install yt-dlp" in caught.value.hint_zh
    assert caught.value.hint_en is not None and "KARAFORGE_YTDLP" in caught.value.hint_en
    # It is found in $KARAFORGE_HOME/bin as well.
    home_bin = tmp_path / "home" / "bin"
    install_fake_ytdlp(home_bin)
    assert ytdlp.find_ytdlp() == str(home_bin / "yt-dlp")


def test_version_comes_from_the_executable(fake: Path) -> None:
    assert ytdlp.version() == "2099.01.01"
    assert calls(fake) == [["--version"]]


# ---------------------------------------------------------------------- describing a link


def test_describe_suggests_title_and_artist() -> None:
    plain = ytdlp.describe(
        {"id": "x", "title": " 歌名 MV ", "uploader": "某歌手 - Topic", "duration": 61.25,
         "webpage_url": "https://w/x", "extractor_key": "Youtube", "vcodec": "avc1"}
    )  # fmt: skip
    assert (plain.title, plain.artist, plain.uploader) == ("歌名 MV", "某歌手", "某歌手 - Topic")
    assert plain.duration_ms == 61_250 and plain.has_video and plain.size_bytes is None
    music = ytdlp.describe({"title": "x", "track": "晴天", "artist": "周杰倫", "uploader": "u"})
    assert (music.title, music.artist) == ("晴天", "周杰倫")
    audio = ytdlp.describe({"title": "x", "vcodec": "none", "acodec": "opus", "filesize": 7.0})
    assert not audio.has_video and audio.size_bytes == 7 and audio.duration_ms is None


def test_playlists_and_live_streams_are_refused() -> None:
    with pytest.raises(ytdlp.YtDlpError) as playlist:
        ytdlp.describe({"_type": "playlist", "entries": []})
    assert "播放清單" in playlist.value.message_zh
    with pytest.raises(ytdlp.YtDlpError) as live:
        ytdlp.describe({"title": "x", "live_status": "is_upcoming"})
    assert "直播" in live.value.message_zh


def test_probe_reads_the_video_without_downloading(fake: Path) -> None:
    media = ytdlp.probe(URL)
    assert media.url == "https://www.youtube.com/watch?v=abc123"
    assert (media.title, media.artist, media.duration_ms) == (
        "晴天 (Official MV)",
        "某歌手",
        269_500,
    )
    assert media.has_video and media.size_bytes == 3000 and media.extractor == "Youtube"
    assert media.to_dict()["thumbnail"] == "https://example.com/thumb.jpg"
    (command,) = calls(fake)
    # The link always comes last, after "--", so that it can never be read as an option.
    assert command[-2:] == ["--", URL]
    for option in ("--ignore-config", "--no-playlist", "--flat-playlist", "--skip-download"):
        assert option in command
    assert "res:1080,vcodec:h264,acodec:aac,channels:2" in command


def test_probe_explains_failures(fake: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_YTDLP_MODE", "error")
    with pytest.raises(ytdlp.YtDlpError) as caught:
        ytdlp.probe(URL)
    error = caught.value
    assert error.message_zh == "無法讀取這個網址的影片：Video unavailable"
    assert error.message_en == "Could not read the video at this link: Video unavailable"
    assert error.hint_zh is not None and "yt-dlp -U" in error.hint_zh
    assert error.detail is not None and "WARNING: something harmless" in error.detail
    assert error.code == "download_failed"

    monkeypatch.setenv("FAKE_YTDLP_MODE", "unsupported")
    with pytest.raises(ytdlp.YtDlpError, match="does not support this link"):
        ytdlp.probe(URL)
    monkeypatch.setenv("FAKE_YTDLP_MODE", "playlist")
    with pytest.raises(ytdlp.YtDlpError, match="playlist"):
        ytdlp.probe(URL)


# ------------------------------------------------------------------------------ download


def test_download_writes_media_and_reports_progress(fake: Path, tmp_path: Path) -> None:
    folder = tmp_path / "download"
    folder.mkdir()
    reports: list[tuple[float, str]] = []
    result = ytdlp.download(URL, folder, progress=lambda f, m: reports.append((f, m)))
    assert result.path == folder / "media.wav"
    assert result.path.read_bytes() == b"RIFF-not-really-audio"
    assert (result.title, result.artist) == ("晴天 (Official MV)", "某歌手")
    fractions = [fraction for fraction, _message in reports]
    assert fractions == sorted(fractions) and fractions[0] == 0.0 and fractions[-1] == 1.0
    # Video (2000 bytes) then audio (1000 bytes): halfway through the video is a third.
    assert pytest.approx(0.95 / 3) in fractions
    assert pytest.approx(0.95 * 5 / 6) in fractions
    assert any(m.startswith("下載中 / downloading") and m.endswith("MB") for _f, m in reports)
    assert any("合併影音" in message for _fraction, message in reports)
    (command,) = calls(fake)
    assert command[-2:] == ["--", URL]
    assert command[command.index("--paths") + 1] == str(folder)
    assert command[command.index("--output") + 1] == "media.%(ext)s"
    assert {"--ignore-config", "--no-playlist", "--newline", "--progress"} <= set(command)


def test_download_failures_and_cancellation(
    fake: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_YTDLP_MODE", "error")
    with pytest.raises(ytdlp.YtDlpError) as failed:
        ytdlp.download(URL, tmp_path)
    assert failed.value.message_zh == "無法下載這部影片：Video unavailable"

    monkeypatch.setenv("FAKE_YTDLP_MODE", "slow")
    cancel = CancelToken()
    threading.Timer(0.8, cancel.cancel).start()
    started = time.monotonic()
    with pytest.raises(JobCancelledError):
        ytdlp.download(URL, tmp_path, cancel=cancel)
    assert time.monotonic() - started < 5.0


def test_progress_without_sizes_weighs_the_parts_equally() -> None:
    reports: list[float] = []
    tracker_class = ytdlp._DownloadProgress  # pyright: ignore[reportPrivateUsage]
    tracker = tracker_class(lambda fraction, _message: reports.append(fraction))
    tracker.line('KFINFO {"format_id": "1+2"}')
    tracker.line("KFSIZES NA")
    tracker.line('KFPROG "1" "downloading" 50 NA NA')
    assert tracker.fraction() == 0.0  # no size known for either part yet
    tracker.line('KFPROG "1" "downloading" 50 100 NA')
    assert tracker.fraction() == pytest.approx(0.25)
    tracker.line('KFPROG "1" "finished" 100 100 NA')
    tracker.line('KFPROG "2" "downloading" 10 NA 40')
    assert tracker.fraction() == pytest.approx(110 / 140)
    tracker.line("garbage that is not a progress line")
    tracker.line('KFPROG "2"')
    assert reports[-1] == pytest.approx(0.95 * tracker.fraction())
