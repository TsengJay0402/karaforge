from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from karaforge import __version__, cli
from karaforge.audio.io import write_wav
from karaforge.errors import ExportError, MediaError, PipelineError, ProjectError
from karaforge.project import ProjectStore
from karaforge.project.create import (
    create_or_update_project,
    create_project,
    default_project_dir,
)

runner = CliRunner()
LYRICS = "# title: 測試\n# artist: 某人\n\n[男] 第一句歌詞\n[女] second line\n"


@pytest.fixture
def media(tmp_path: Path) -> Path:
    path = tmp_path / "我的歌.wav"
    tone = (0.1 * np.sin(np.arange(4800) / 10.0)).astype(np.float32)
    write_wav(path, np.stack([tone, tone], axis=1), 48000)
    return path


@pytest.fixture
def lyrics(tmp_path: Path) -> Path:
    path = tmp_path / "lyrics.txt"
    path.write_text(LYRICS, encoding="utf-8")
    return path


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_new_creates_a_project_next_to_the_media(media: Path, lyrics: Path) -> None:
    result = runner.invoke(cli.app, ["new", str(media), "--lyrics", str(lyrics)])
    assert result.exit_code == 0, result.output
    root = media.parent / "我的歌.kfproj"
    assert default_project_dir(media) == root
    project = ProjectStore(root).load()
    assert project.meta.title == "測試"
    assert project.meta.artist == "某人"
    assert [line.text for line in project.lines] == ["第一句歌詞", "second line"]
    assert [line.singer for line in project.lines] == ["m", "f"]
    assert project.media.source == "media/source.wav"
    assert (root / "media" / "source.wav").read_bytes() == media.read_bytes()
    assert "kf run" in result.output


def test_new_with_explicit_output_language_and_title(media: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / "demo.kfproj"
    result = runner.invoke(
        cli.app,
        ["new", str(media), "-o", str(target), "--language", "en", "--title", "My Song"],
    )
    assert result.exit_code == 0, result.output
    project = ProjectStore(target).load()
    assert (project.meta.language, project.meta.title) == ("en", "My Song")
    assert project.lines == []


def test_new_without_title_uses_the_file_name(media: Path, tmp_path: Path) -> None:
    store = create_project(media, tmp_path / "p.kfproj")
    assert store.load().meta.title == "我的歌"


def test_new_refuses_to_overwrite_unless_forced(media: Path, lyrics: Path, tmp_path: Path) -> None:
    target = tmp_path / "p.kfproj"
    create_project(media, target, lyrics=lyrics)
    with pytest.raises(ProjectError):
        create_project(media, target, lyrics=lyrics)
    (target / "media" / "leftover.bin").write_bytes(b"x")
    create_project(media, target, overwrite=True)
    assert not (target / "media" / "leftover.bin").exists()


def test_new_rejects_missing_and_unsupported_media(tmp_path: Path) -> None:
    with pytest.raises(MediaError):
        create_project(tmp_path / "nope.mp3", tmp_path / "a.kfproj")
    document = tmp_path / "notes.pdf"
    document.write_bytes(b"%PDF")
    with pytest.raises(MediaError) as info:
        create_project(document, tmp_path / "b.kfproj")
    assert "mp4" in (info.value.hint_en or "")


def test_create_or_update_reuses_and_refreshes_the_lyrics(
    media: Path, lyrics: Path, tmp_path: Path
) -> None:
    target = tmp_path / "p.kfproj"
    store, created = create_or_update_project(media, target, lyrics=lyrics)
    assert created
    revision = store.load().revision

    same, created = create_or_update_project(media, target, lyrics=lyrics)
    assert not created
    assert same.load().revision == revision  # nothing changed, nothing saved

    lyrics.write_text(LYRICS + "[合] 第三句\n", encoding="utf-8")
    updated, created = create_or_update_project(media, target, lyrics=lyrics, language="en")
    assert not created
    project = updated.load()
    assert [line.text for line in project.lines] == ["第一句歌詞", "second line", "第三句"]
    assert project.meta.language == "en"
    assert project.revision == revision + 1


def test_create_or_update_rejects_a_project_of_another_file(media: Path, tmp_path: Path) -> None:
    target = tmp_path / "p.kfproj"
    create_or_update_project(media, target)
    other = tmp_path / "other.wav"
    write_wav(other, np.zeros((4800, 2), dtype=np.float32), 48000)
    with pytest.raises(ProjectError):
        create_or_update_project(other, target)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("720p", (1280, 720)),
        ("1080P", (1920, 1080)),
        ("4k", (3840, 2160)),
        ("1024x576", (1024, 576)),
    ],
)
def test_parse_resolution(value: str, expected: tuple[int, int]) -> None:
    assert cli.parse_resolution(value) == expected


@pytest.mark.parametrize("value", ["", "big", "1921x1080", "100x50", "1920x", "x1080"])
def test_parse_resolution_rejects_nonsense(value: str) -> None:
    with pytest.raises(ExportError):
        cli.parse_resolution(value)


def test_resolve_profile_applies_overrides() -> None:
    profile = cli.resolve_profile("cpu-lite", ["align.onset_snap_ms=90", "align.long_note=false"])
    assert profile.name == "cpu-lite"
    assert profile.align.onset_snap_ms == 90
    assert profile.align.long_note is False
    with pytest.raises(PipelineError):
        cli.resolve_profile("cpu-lite", ["align.nope=1"])
    with pytest.raises(PipelineError):
        cli.resolve_profile("turbo-max", None)


def test_open_project_requires_a_project_folder(tmp_path: Path) -> None:
    with pytest.raises(ProjectError) as info:
        cli.open_project(tmp_path)
    assert "kf new" in (info.value.hint_en or "")


def test_new_with_lrc_lyrics_keeps_line_and_word_times(media: Path, tmp_path: Path) -> None:
    lrc = tmp_path / "song.lrc"
    lrc.write_text(
        "[ti:匯入的歌]\n[ar:某人]\n"
        "[00:01.00]第一句\n"
        "[00:03.50]F: <00:03.50>逐<00:03.90>字<00:04.30>\n",
        encoding="utf-8",
    )
    target = tmp_path / "p.kfproj"
    result = runner.invoke(cli.app, ["new", str(media), "--lyrics", str(lrc), "-o", str(target)])
    assert result.exit_code == 0, result.output
    store = ProjectStore(target)
    project = store.load()
    assert (project.meta.title, project.meta.artist) == ("匯入的歌", "某人")
    first, second = project.lines
    assert first.time_hint == (1000, 3500)
    assert all(not token.is_timed for token in first.tokens)
    assert second.singer == "f" and second.time_hint is None
    assert [(t.text, t.start_ms, t.end_ms, t.locked) for t in second.tokens] == [
        ("逐", 3500, 3900, True),
        ("字", 3900, 4300, True),
    ]
    # Word-timed lyrics can be exported again straight away, without any processing.
    exported = cli.export_project(store, fmt="elrc").read_text(encoding="utf-8")
    assert "[00:03.50]F: <00:03.50>逐<00:03.90>字<00:04.30>" in exported
    assert "第一句" not in exported  # that line has no word times yet


def test_export_rejects_unknown_format_and_background(media: Path, tmp_path: Path) -> None:
    store = create_project(media, tmp_path / "p.kfproj")
    with pytest.raises(ExportError):
        cli.export_project(store, fmt="avi")
    with pytest.raises(ExportError):
        cli.export_project(store, background="sparkles")


def run_main(arguments: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["kf", *arguments])
    with pytest.raises(SystemExit) as info:
        cli.main()
    return int(info.value.code or 0)


def test_main_prints_errors_in_the_chosen_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KARAFORGE_LANG", "zh")
    assert run_main(["run", str(tmp_path / "missing.kfproj")], monkeypatch) == 1
    captured = capsys.readouterr().err
    assert "錯誤" in captured and "找不到專案" in captured and "kf new" in captured

    monkeypatch.setenv("KARAFORGE_LANG", "en")
    assert run_main(["run", str(tmp_path / "missing.kfproj")], monkeypatch) == 1
    captured = capsys.readouterr().err
    assert "Error" in captured and "Not a KaraForge project" in captured


def test_main_shows_details_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KARAFORGE_LANG", "en")
    broken = tmp_path / "broken.kfproj"
    broken.mkdir()
    (broken / "project.json").write_text("{not json", encoding="utf-8")
    assert run_main(["run", str(broken)], monkeypatch) == 1
    quiet = capsys.readouterr().err
    assert "--verbose" in quiet and "Expecting" not in quiet
    assert run_main(["run", str(broken), "--verbose"], monkeypatch) == 1
    assert "Expecting" in capsys.readouterr().err


def test_models_list_shows_registry_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    monkeypatch.setenv("KARAFORGE_LANG", "en")
    monkeypatch.setenv("COLUMNS", "200")
    result = runner.invoke(cli.app, ["models", "list"])
    assert result.exit_code == 0, result.output
    assert "whisper-small" in result.output and "uvr-mdxnet-kara-2" in result.output
    assert "installed" not in result.output.replace("--accept-license", "")


def test_models_verify_reports_missing_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    result = runner.invoke(cli.app, ["models", "verify", "uvr-metadata"])
    assert result.exit_code == 1
    assert "missing" in result.output
    # Without names only models that exist on disk are checked: nothing to complain about.
    assert runner.invoke(cli.app, ["models", "verify"]).exit_code == 0


def test_profile_model_ids_include_required_companions() -> None:
    ids = cli.profile_model_ids(cli.get_profile("cpu-lite"))
    assert ids.index("uvr-metadata") < ids.index("uvr-mdxnet-kara-2")
    assert "whisper-base" in ids
    assert len(ids) == len(set(ids))
    assert json.dumps(ids)  # plain strings
