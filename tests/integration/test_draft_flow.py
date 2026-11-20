"""The "no lyrics" flow with real models (cpu-lite profile) on a synthetic song.

Speech recognition drafts the lyrics, the draft is aligned and a video comes out.  This tests
that the flow works and that the draft has the right shape; it does **not** expect the words
to be right.  Whisper understands this synthetic singing poorly without a lyrics prompt —
the test prints the measured character error rate so that the documentation quotes a real
number (about four in five characters wrong with the cpu-lite model, about half with the
larger ones) instead of a hopeful one.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from rapidfuzz.distance import Levenshtein
from typer.testing import CliRunner

from karaforge import cli
from karaforge.project import ProjectStore
from karaforge.stages.standard import run_pipeline
from karaforge.text.tokenize import is_han
from karaforge.tools import ffmpeg

pytestmark = [pytest.mark.models, pytest.mark.ffmpeg, pytest.mark.slow]

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "songs" / "zh-2000"
runner = CliRunner()


def han(text: str) -> str:
    """Only the Chinese characters of ``text``: what the draft is compared on."""
    return "".join(char for char in text if is_han(char))


@pytest.fixture(scope="module")
def drafted(repo_root: Path) -> tuple[Path, Path, str]:
    """Run ``kf auto`` without lyrics once; returns (video, project folder, CLI output)."""
    work = repo_root / ".pytest_tmp" / "draft_flow"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    video = work / "song.mp4"
    arguments = ["auto", str(FIXTURE / "mix_snr10.mp3"), "-o", str(video)]
    result = runner.invoke(cli.app, [*arguments, "--profile", "cpu-lite", "--res", "720p"])
    assert result.exit_code == 0, result.output
    return video, work / "song.kfproj", result.output


def test_lyrics_are_drafted_in_traditional_script_and_aligned(
    drafted: tuple[Path, Path, str],
) -> None:
    _video, project_dir, output = drafted
    assert "產生歌詞草稿" in output or "Drafting lyrics" in output
    project = ProjectStore(project_dir).load()
    truth = json.loads((FIXTURE / "truth.json").read_text(encoding="utf-8"))
    assert project.meta.lyrics_source == "asr"
    assert project.has_lyrics and project.is_aligned
    # Roughly the line structure of the song (four sung lines), not one long line.
    assert 3 <= len(project.lines) <= 10
    starts = [token.start_ms or 0 for line in project.lines for token in line.tokens]
    assert starts == sorted(starts)

    reference = han("".join(line["text"] for line in truth["lines"]))
    recognised = han("".join(line.text for line in project.lines))
    errors = Levenshtein.distance(reference, recognised)
    rate = errors / len(reference)
    print(  # noqa: T201 - the measured figure, for the documentation
        "\ndraft character error rate (cpu-lite, whisper-base, synthetic zh-2000 at 10 dB): "
        f"{errors}/{len(reference)} = {rate:.1%}\n"
        f"  reference:  {reference}\n  recognised: {recognised}"
    )
    # The words are mostly wrong (see the module docstring), but the draft has the size of
    # the song: neither a few stray words nor a runaway repetition.
    assert 0.4 * len(reference) <= len(recognised) <= 1.6 * len(reference)
    # The second half of the song is in the draft *and* so is the first: without its "no
    # speech" gate Whisper no longer drops the first 30-second window.
    first_sung = truth["lines"][0]["tokens"][0]["start_ms"]
    last_sung = truth["lines"][-1]["tokens"][-1]["start_ms"]
    assert (project.lines[0].start_ms or 0) < 25_000
    assert (project.lines[-1].start_ms or 0) > (first_sung + last_sung) / 2
    # Every drafted line lies where somebody sings.
    regions = project.analysis.vocal_regions
    for line in project.lines:
        hint = line.time_hint
        assert hint is not None and hint[1] is not None
        assert any(hint[0] <= end + 500 and hint[1] >= start - 500 for start, end in regions)
    # The whole draft is in Traditional script although Whisper answers in Simplified.
    assert not set(recognised) & set(
        "车这来里个们说时会对过发后种经么学现当没动还进开从实无与长远传"
    )
    # Chinese drafts get readings like any other Chinese lyrics.
    assert any(token.ruby_source == "auto" for line in project.lines for token in line.tokens)


def test_the_video_of_a_drafted_song_is_playable(drafted: tuple[Path, Path, str]) -> None:
    video, _project, _output = drafted
    info = ffmpeg.probe(video)
    assert info.video is not None and info.audio is not None
    assert (info.video.width, info.video.height) == (1280, 720)
    assert info.duration_ms == pytest.approx(48_500, abs=300)


def test_correcting_the_draft_does_not_repeat_the_recognition(
    drafted: tuple[Path, Path, str],
) -> None:
    _video, project_dir, _output = drafted
    store = ProjectStore(project_dir)
    project = store.load()
    # Proofread one line: replace its text, keep everything else.
    from karaforge.project.edit import retokenize_line

    project.lines[0] = retokenize_line(
        project.lines[0], "車窗上的雨滴 排成一條線", language="zh-TW"
    )
    store.save(project)
    report = run_pipeline(store, profile=cli.get_profile("cpu-lite"))
    statuses = {stage.stage: stage.status for stage in report.stages}
    assert statuses["separate"] == "cached"
    assert statuses["asr"] == "cached"
    assert statuses["draft"] == "skipped"
    assert statuses["align"] == "finished"
    after = store.load()
    assert after.lines[0].text == "車窗上的雨滴 排成一條線"
    assert after.meta.lyrics_source == "asr"
    assert after.is_aligned
