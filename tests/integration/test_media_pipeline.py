"""Integration tests that need ffmpeg but no model weights: ingest and video export."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pytest

from karaforge import cli
from karaforge.audio.io import read_wav, write_wav
from karaforge.errors import ExportError, MediaError, PipelineError
from karaforge.io.exporters.png import write_rgba_png
from karaforge.io.exporters.video import parse_audio_option
from karaforge.pipeline import get_profile
from karaforge.project import ProjectStore
from karaforge.project.create import create_project
from karaforge.stages.standard import run_pipeline
from karaforge.tools import ffmpeg
from support import grab_frames, timed_line

pytestmark = pytest.mark.ffmpeg


def make_video(path: Path, seconds: int = 4) -> None:
    """A small test-pattern video with a stereo tone (H.264 + AAC)."""
    ffmpeg.run_ffmpeg(
        [
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ac", "2", "-shortest", path.name,
        ],
        cwd=path.parent,
    )  # fmt: skip


def make_tone(path: Path, seconds: float = 4.0, rate: int = 22050) -> None:
    samples = np.arange(round(seconds * rate)) / rate
    write_wav(path, (0.3 * np.sin(2 * np.pi * 330 * samples)).astype(np.float32), rate)


def ingest(store: ProjectStore) -> dict[str, object]:
    report = run_pipeline(store, profile=get_profile("cpu-lite"), targets=("ingest",))
    return report["ingest"].result


def streams(path: Path) -> dict[str, ffmpeg.StreamInfo]:
    info = ffmpeg.probe(path)
    return {stream.kind: stream for stream in info.streams}


def test_ingest_decodes_video_source_to_analysis_audio(work_dir: Path) -> None:
    video = work_dir / "clip.mp4"
    make_video(video)
    store = create_project(video, work_dir / "clip.kfproj")
    result = ingest(store)

    audio, rate = read_wav(store.paths.media / "audio.wav")
    assert rate == 48000 and audio.shape[1] == 2
    assert audio.shape[0] == pytest.approx(4 * 48000, rel=0.02)
    assert result["has_video"] is True
    assert result["video"] == {"width": 320, "height": 240, "fps": 25.0}
    project = store.load()
    assert project.media.audio == "media/audio.wav"
    assert project.media.has_video is True
    assert project.meta.duration_ms == pytest.approx(4000, abs=80)
    peaks = json.loads((store.paths.media / "peaks.json").read_text())
    assert peaks["sample_rate"] == 48000
    assert [level["samples_per_bucket"] for level in peaks["levels"]] == [256, 1024, 4096, 16384]
    # ffmpeg's ``sine`` source has an amplitude of 1/8, i.e. about 16 on the ±127 scale.
    assert 8 <= max(peaks["levels"][0]["max"]) <= 20


def test_ingest_is_cached_and_keeps_the_revision_stable(work_dir: Path) -> None:
    tone = work_dir / "tone.wav"
    make_tone(tone)
    store = create_project(tone, work_dir / "tone.kfproj")
    first = run_pipeline(store, profile=get_profile("cpu-lite"), targets=("ingest",))
    revision = store.load().revision
    second = run_pipeline(store, profile=get_profile("cpu-lite"), targets=("ingest",))
    assert first.executed == ["ingest"] and second.cached == ["ingest"]
    assert store.load().revision == revision
    project = store.load()
    assert project.media.has_video is False
    # Mono 22 kHz input is brought to the 48 kHz stereo analysis format.
    audio, rate = read_wav(store.paths.media / "audio.wav")
    assert (rate, audio.shape[1]) == (48000, 2)
    assert np.allclose(audio[:, 0], audio[:, 1])


def test_ingest_rejects_files_without_usable_audio(work_dir: Path) -> None:
    silent = work_dir / "silent.mp4"
    ffmpeg.run_ffmpeg(
        ["-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", silent.name],
        cwd=work_dir,
    )  # fmt: skip
    with pytest.raises(MediaError) as info:
        ingest(create_project(silent, work_dir / "silent.kfproj"))
    assert "沒有音訊" in info.value.message_zh

    garbage = work_dir / "garbage.mp3"
    garbage.write_bytes(b"definitely not an mp3 file" * 50)
    with pytest.raises(MediaError):
        ingest(create_project(garbage, work_dir / "garbage.kfproj"))

    blip = work_dir / "blip.wav"
    make_tone(blip, seconds=0.2)
    with pytest.raises(MediaError) as info:
        ingest(create_project(blip, work_dir / "blip.kfproj"))
    assert "太短" in info.value.message_zh


def prepared_project(work_dir: Path, *, video: bool) -> ProjectStore:
    """An ingested project with hand-made timing and stand-in stems (no models involved)."""
    source = work_dir / ("clip.mp4" if video else "tone.wav")
    make_video(source) if video else make_tone(source)
    store = create_project(source, work_dir / "song.kfproj")
    ingest(store)
    # Stand-ins for the separation output: any audio of the right length will do here.
    for name in ("vocals.wav", "instrumental.wav"):
        shutil.copyfile(store.paths.media / "audio.wav", store.paths.media / name)
    project = store.load()
    project.media.vocals = "media/vocals.wav"
    project.media.instrumental = "media/instrumental.wav"
    project.lines = [
        timed_line("L001", "一二三四", 1_000, 400),
        timed_line("L002", "五六七", 2_600, 300),
    ]
    project.render.resolution = (640, 360)
    store.save(project)
    return store


@pytest.mark.parametrize("audio", ["instrumental", "guide:-9db", "original"])
def test_export_mp4_with_each_audio_mode(work_dir: Path, audio: str) -> None:
    store = prepared_project(work_dir, video=True)
    output = cli.export_project(store, audio=audio, output=work_dir / "out.mp4")
    found = streams(output)
    assert found["video"].codec == "h264"
    assert (found["video"].width, found["video"].height) == (640, 360)
    assert found["audio"].codec == "aac"
    assert ffmpeg.probe(output).duration_ms == pytest.approx(4000, abs=150)
    assert (store.paths.exports / "out.mp4").is_file()


def test_export_uses_a_colour_background_for_audio_only_sources(work_dir: Path) -> None:
    store = prepared_project(work_dir, video=False)
    revision = store.load().revision
    output = cli.export_project(store, res="480p")
    assert output == store.paths.exports / "tone.mp4"
    found = streams(output)
    assert (found["video"].width, found["video"].height) == (854, 480)
    # The size given for one export is not written into the project.
    assert store.load().render.resolution == (640, 360)
    assert store.load().revision == revision


def test_export_mkv_has_soft_subtitles_fonts_and_two_audio_tracks(work_dir: Path) -> None:
    store = prepared_project(work_dir, video=True)
    project = store.load()
    project.meta.title = "測試歌"
    store.save(project)
    output = cli.export_project(store, fmt="mkv")
    assert output == store.paths.exports / "測試歌.mkv"
    info = ffmpeg.probe(output)
    assert "matroska" in info.format_name
    assert info.tags.get("title") == "測試歌"
    video = info.video
    assert video is not None and (video.codec, video.width, video.height) == ("h264", 640, 360)
    audio = [stream for stream in info.streams if stream.kind == "audio"]
    assert [stream.codec for stream in audio] == ["aac", "aac"]
    assert [stream.title for stream in audio] == ["伴唱 / Karaoke", "原唱 / Original"]
    assert [stream.is_default for stream in audio] == [True, False]
    assert [(stream.codec, stream.title) for stream in info.subtitles] == [("ass", "KTV")]
    fonts = info.attachments
    assert [font.filename for font in fonts] == ["GenSenRounded2TW-B.otf"]
    assert fonts[0].mimetype == "application/vnd.ms-opentype"
    assert info.duration_ms == pytest.approx(4000, abs=200)

    # The subtitle track is the same script that would be burned into an MP4.
    extracted = output.with_name("extracted.ass")
    ffmpeg.run_ffmpeg(
        ["-i", output.name, "-map", "0:s:0", "-c:s", "copy", extracted.name], cwd=output.parent
    )
    script = cli.export_project(store, fmt="ass").read_text(encoding="utf-8")
    dialogue = [row for row in script.splitlines() if row.startswith("Dialogue:")]
    kept = extracted.read_text(encoding="utf-8")
    assert len([row for row in kept.splitlines() if row.startswith("Dialogue:")]) == len(dialogue)
    assert "Style: " in kept and "GenSenRounded2 TW B" in kept


def test_export_mkv_with_original_audio_first_and_without_a_source_video(work_dir: Path) -> None:
    store = prepared_project(work_dir, video=False)
    output = cli.export_project(store, fmt="mkv", audio="original", output=work_dir / "o.mkv")
    info = ffmpeg.probe(output)
    audio = [stream for stream in info.streams if stream.kind == "audio"]
    assert [stream.title for stream in audio] == ["原唱 / Original", "伴唱 / Karaoke"]
    assert info.video is not None and len(info.subtitles) == 1


def test_text_exports_through_the_cli(work_dir: Path) -> None:
    store = prepared_project(work_dir, video=True)
    lrc = cli.export_project(store, fmt="lrc")
    assert lrc == store.paths.exports / "clip.lrc"
    assert "[00:01.00]一二三四" in lrc.read_text(encoding="utf-8")
    enhanced = cli.export_project(store, fmt="elrc")
    assert enhanced.name == "clip.enhanced.lrc"
    assert "<00:01.00>一<00:01.40>二" in enhanced.read_text(encoding="utf-8")
    srt = cli.export_project(store, fmt="srt", output=work_dir / "named.srt")
    assert srt.read_text(encoding="utf-8").startswith("1\n00:00:01,000 --> 00:00:02,600\n一二三四")
    assert (store.paths.exports / "named.srt").is_file()
    ass = cli.export_project(store, fmt="ass")
    assert "[V4+ Styles]" in ass.read_text(encoding="utf-8")
    archive = cli.export_project(store, fmt="kfproj")
    assert archive.name == "clip.kfproj.zip"
    with zipfile.ZipFile(archive) as packed:
        assert "song.kfproj/project.json" in packed.namelist()
        assert "song.kfproj/media/audio.wav" in packed.namelist()
        assert not any("cache/" in name or "exports/" in name for name in packed.namelist())
    with pytest.raises(ExportError) as info:
        cli.export_project(store, fmt="avi")
    assert "ultrastar" in (info.value.hint_en or "")


def test_ultrastar_export_takes_note_pitches_from_the_vocal_stem(work_dir: Path) -> None:
    store = prepared_project(work_dir, video=True)
    # A vocal stem that "sings" A3 (220 Hz) and then E4 (329.63 Hz).
    rate = 16000
    time = np.arange(4 * rate) / rate
    wave = np.where(time < 2.5, np.sin(2 * np.pi * 220.0 * time), np.sin(2 * np.pi * 329.63 * time))
    write_wav(store.paths.media / "vocals.wav", (0.4 * wave).astype(np.float32), rate)
    output = cli.export_project(store, fmt="ultrastar")
    assert output.name == "clip.ultrastar.txt"
    text = output.read_text(encoding="utf-8")
    assert "#MP3:clip.mp4" in text and "#VIDEO:clip.mp4" in text
    notes = [row.split(" ") for row in text.splitlines() if row.startswith(":")]
    assert [row[4] for row in notes] == list("一二三四五六七")
    # A3 is 3 semitones below C4, E4 is 4 above; line 2 starts at 2.6 s.
    assert [int(row[3]) for row in notes] == [-3, -3, -3, -3, 4, 4, 4]
    # The pitch track is cached.
    from karaforge.stages.standard import run_pipeline as run

    again = run(
        store, profile=get_profile("cpu-lite"), targets=("pitch",), include_dependencies=False
    )
    assert again.cached == ["pitch"]


@pytest.mark.parametrize("mode", ["image", "blur"])
def test_export_with_a_picture_as_background(work_dir: Path, mode: str) -> None:
    store = prepared_project(work_dir, video=False)
    # A picture whose left half is red and whose right half is blue.
    row = bytes([200, 30, 30, 255]) * 32 + bytes([30, 30, 200, 255]) * 32
    write_rgba_png(store.paths.media / "cover.png", 64, 36, [row] * 36)
    project = store.load()
    project.render.background.type = mode  # pyright: ignore[reportAttributeAccessIssue]
    project.render.background.image = "media/cover.png"
    store.save(project)
    output = cli.export_project(store)
    (work_dir / "grab").mkdir()
    frame = grab_frames(output, [0.2], work_dir / "grab", fps=project.render.fps)[0]
    assert frame.shape == (360, 640, 3)
    left, right = frame[20, 30].astype(int), frame[20, 610].astype(int)
    assert left[0] > left[2] + 60 and right[2] > right[0] + 60
    if mode == "blur":
        # The sharp copy in the middle is brighter than the darkened, blurred surroundings.
        inside = frame[150, 200].astype(int)
        assert inside[0] > left[0] + 10


def test_export_is_cached_and_never_reruns_alignment(work_dir: Path) -> None:
    from karaforge.io.exporters.video import VideoOptions
    from karaforge.stages.export import OPTION_KEY
    from karaforge.stages.standard import EXPORT_TARGETS

    store = prepared_project(work_dir, video=False)
    options = {OPTION_KEY: VideoOptions(audio="original", background="color")}
    profile = get_profile("cpu-lite")
    first = run_pipeline(
        store, profile=profile, targets=EXPORT_TARGETS, options=options, include_dependencies=False
    )
    assert first.executed == ["subtitles", "export"]
    second = run_pipeline(
        store, profile=profile, targets=EXPORT_TARGETS, options=options, include_dependencies=False
    )
    assert second.cached == ["subtitles", "export"]

    # Editing a token changes the subtitles and therefore the video, but nothing upstream.
    project = store.load()
    token = project.lines[0].tokens[0]
    project.lines[0].tokens[0] = token.retimed(1_100, 1_400, source="manual", locked=True)
    store.save(project)
    third = run_pipeline(
        store, profile=profile, targets=EXPORT_TARGETS, options=options, include_dependencies=False
    )
    assert third.executed == ["subtitles", "export"]
    assert [stage.stage for stage in third.stages] == ["subtitles", "export"]
    assert store.load().lines[0].tokens[0].start_ms == 1_100


def test_export_needs_processed_and_aligned_lyrics(work_dir: Path) -> None:
    tone = work_dir / "tone.wav"
    make_tone(tone)
    store = create_project(tone, work_dir / "raw.kfproj")
    with pytest.raises(PipelineError) as info:
        cli.export_project(store)
    assert "歌詞" in info.value.message_zh
    ingest(store)
    project = store.load()
    project.lines = [timed_line("L001", "一二", 500)]
    project.lines[0].tokens = [token.retimed(None, None) for token in project.lines[0].tokens]
    store.save(project)
    with pytest.raises(PipelineError) as info:
        cli.export_project(store)
    assert "對齊" in info.value.message_zh


def test_export_without_stems_explains_what_to_do(work_dir: Path) -> None:
    tone = work_dir / "tone.wav"
    make_tone(tone)
    store = create_project(tone, work_dir / "nostems.kfproj")
    ingest(store)
    project = store.load()
    project.lines = [timed_line("L001", "一二", 500)]
    store.save(project)
    with pytest.raises(PipelineError):
        cli.export_project(store, audio="instrumental")
    # The original audio needs no separation.
    assert cli.export_project(store, audio="original").is_file()


def test_parse_audio_option() -> None:
    assert parse_audio_option("instrumental") == ("instrumental", -12.0)
    assert parse_audio_option("Guide") == ("guide", -12.0)
    assert parse_audio_option("guide:-6dB") == ("guide", -6.0)
    assert parse_audio_option("guide:9") == ("guide", -9.0)
    assert parse_audio_option("原曲") == ("original", -12.0)
    with pytest.raises(ExportError):
        parse_audio_option("loud")
    with pytest.raises(ExportError):
        parse_audio_option("guide:quiet")
