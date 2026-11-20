"""The whole pipeline with real models (cpu-lite profile) on a synthetic song.

Needs ffmpeg and the cpu-lite model weights (``kf models download --profile cpu-lite``); it
is skipped with an explanatory message when they are missing.  The numeric bounds here are
loose sanity checks — alignment quality is measured by ``kf bench``, not by this test.
"""

from __future__ import annotations

import json
import shutil
import statistics
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karaforge import cli
from karaforge.layout.theme import load_theme
from karaforge.project import ProjectStore
from karaforge.stages.standard import run_pipeline
from karaforge.stages.subtitles import PLAN_FILE, load_plan
from karaforge.tools import ffmpeg
from support import color_mask, grab_frames

pytestmark = [pytest.mark.models, pytest.mark.ffmpeg, pytest.mark.slow]

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "songs" / "zh-2000"
runner = CliRunner()


@pytest.fixture(scope="module")
def auto_run(repo_root: Path) -> tuple[Path, Path, str]:
    """Run ``kf auto`` once for the module; returns (video, project folder, CLI output)."""
    work = repo_root / ".pytest_tmp" / "full_pipeline"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    video = work / "song.mp4"
    result = runner.invoke(
        cli.app,
        [
            "auto",
            str(FIXTURE / "mix_snr10.mp3"),
            str(FIXTURE / "lyrics.txt"),
            "-o",
            str(video),
            "--profile",
            "cpu-lite",
            "--res",
            "720p",
        ],
    )
    assert result.exit_code == 0, result.output
    return video, work / "song.kfproj", result.output


def test_auto_produces_a_playable_video(auto_run: tuple[Path, Path, str]) -> None:
    video, _project, _output = auto_run
    info = ffmpeg.probe(video)
    assert info.video is not None and info.audio is not None
    assert (info.video.codec, info.video.width, info.video.height) == ("h264", 1280, 720)
    assert info.audio.codec == "aac"
    assert info.duration_ms == pytest.approx(48_500, abs=300)


def test_every_token_is_timed_in_order_and_roughly_right(auto_run: tuple[Path, Path, str]) -> None:
    _video, project_dir, _output = auto_run
    project = ProjectStore(project_dir).load()
    truth = json.loads((FIXTURE / "truth.json").read_text(encoding="utf-8"))
    assert project.is_aligned
    assert project.media.vocals == "media/vocals.wav"
    assert len(project.analysis.vocal_regions) >= 3
    assert project.analysis.tempo_bpm is not None

    starts = [token.start_ms or 0 for line in project.lines for token in line.tokens]
    assert starts == sorted(starts)
    errors: list[int] = []
    for line, expected in zip(project.lines, truth["lines"], strict=True):
        assert line.text == expected["text"]
        for token, reference in zip(line.tokens, expected["tokens"], strict=True):
            assert token.start_ms is not None and token.end_ms is not None
            assert token.confidence is not None and 0.0 <= token.confidence <= 1.0
            assert token.source == "auto" and not token.locked
            errors.append(abs(token.start_ms - reference["start_ms"]))
    # Sanity bounds only (see module docstring).
    assert statistics.median(errors) < 250
    # Every line is at least found: its first token is within a second of the truth.
    for line, expected in zip(project.lines, truth["lines"], strict=True):
        assert abs((line.start_ms or 0) - expected["tokens"][0]["start_ms"]) < 1000


def test_video_shows_the_fill_progressing(auto_run: tuple[Path, Path, str], work_dir: Path) -> None:
    video, project_dir, _output = auto_run
    store = ProjectStore(project_dir)
    plan_dir = max(
        (store.paths.cache / "subtitles").iterdir(), key=lambda path: path.stat().st_mtime
    )
    plan = load_plan(plan_dir / PLAN_FILE)
    theme = load_theme(plan.style.theme)
    sung_fill = theme.slot("male").fill
    line = plan.lines[0]
    before = (line.sing_start_ms - 600) / 1000
    middle = (line.sing_start_ms + line.sing_end_ms) / 2000
    after = (line.sing_end_ms + 200) / 1000
    frames = grab_frames(video, [before, middle, after], work_dir, fps=30.0)
    counts: list[int] = []
    for frame in frames:
        region = frame[round(line.clip_top) : round(line.clip_bottom), : plan.width]
        counts.append(int(color_mask(region, sung_fill, 60).sum()))
    assert counts[0] == 0
    assert counts[1] > 300
    assert counts[2] > counts[1] * 1.3


def test_running_again_uses_the_cache_for_every_stage(auto_run: tuple[Path, Path, str]) -> None:
    video, project_dir, first_output = auto_run
    assert "✓" in first_output
    modified = video.stat().st_mtime_ns
    result = runner.invoke(
        cli.app,
        [
            "auto",
            str(FIXTURE / "mix_snr10.mp3"),
            str(FIXTURE / "lyrics.txt"),
            "-o",
            str(video),
            "--profile",
            "cpu-lite",
            "--res",
            "720p",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "✓" not in result.output
    assert result.output.count("↺") == 7
    assert video.stat().st_mtime_ns >= modified
    report = run_pipeline(ProjectStore(project_dir), profile=cli.get_profile("cpu-lite"))
    assert report.executed == []


def test_locked_tokens_survive_a_realignment(auto_run: tuple[Path, Path, str]) -> None:
    _video, project_dir, _output = auto_run
    store = ProjectStore(project_dir)
    project = store.load()
    truth = json.loads((FIXTURE / "truth.json").read_text(encoding="utf-8"))
    # "Correct" one token per line the way the editor would: exact time, locked, manual.
    for line, expected in zip(project.lines, truth["lines"], strict=True):
        index = len(line.tokens) // 2
        reference = expected["tokens"][index]
        line.tokens[index] = line.tokens[index].retimed(
            reference["start_ms"], reference["end_ms"], confidence=1.0, source="manual", locked=True
        )
    store.save(project)
    locked_before = [
        token.model_dump() for line in project.lines for token in line.tokens if token.locked
    ]

    report = run_pipeline(store, profile=cli.get_profile("cpu-lite"))
    assert report.executed == ["align"]
    assert report["align"].result["windows_from"]["anchor"] == len(project.lines)

    realigned = store.load()
    locked_after = [
        token.model_dump() for line in realigned.lines for token in line.tokens if token.locked
    ]
    assert locked_after == locked_before
    starts = [token.start_ms or 0 for line in realigned.lines for token in line.tokens]
    assert starts == sorted(starts)
