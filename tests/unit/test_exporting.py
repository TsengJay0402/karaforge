"""Unit tests of the export entry point: format table, names and the text formats."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from karaforge.errors import ExportError, PipelineError
from karaforge.exporting import FORMATS, ExportRequest, export, get_format, output_name
from karaforge.project import Line, Project, ProjectStore, Token
from support import song_project, timed_line

FORMAT_IDS = ["mp4", "mkv", "ass", "lrc", "elrc", "srt", "ultrastar", "kfproj"]


def make_store(tmp_path: Path, project: Project) -> ProjectStore:
    """A project called ``x.kfproj`` in ``tmp_path``, created with ``project``."""
    store = ProjectStore(tmp_path / "x.kfproj")
    store.create(project)
    return store


# ------------------------------------------------------------------------------ format table


def test_formats_table() -> None:
    assert list(FORMATS) == FORMAT_IDS
    assert [fmt.video for fmt in FORMATS.values()] == [
        fmt.id in ("mp4", "mkv") for fmt in FORMATS.values()
    ]
    assert all(fmt.suffix.startswith(".") for fmt in FORMATS.values())
    assert len({fmt.suffix for fmt in FORMATS.values()}) == len(FORMATS)


def test_get_format_is_case_insensitive_and_strips_whitespace() -> None:
    assert get_format(" MKV ") is FORMATS["mkv"]
    assert get_format("srt") is FORMATS["srt"]


def test_get_format_unknown_lists_the_available_ids() -> None:
    with pytest.raises(ExportError) as info:
        get_format("nope")
    # The hint lists the ids of FORMATS in insertion order.
    assert info.value.hint_en == "Available: " + ", ".join(FORMAT_IDS) + "."


# ------------------------------------------------------------------------------- output names


def test_output_name_prefers_request_name_then_title_then_karaoke() -> None:
    project = song_project([], title="測試歌曲")
    assert output_name(project, ExportRequest(format="lrc", name="我的 版本")) == "我的-版本"
    assert output_name(project, ExportRequest(format="lrc")) == "測試歌曲"
    assert output_name(song_project([], title=""), ExportRequest(format="lrc")) == "karaoke"


def test_output_name_slugifies_punctuation_but_keeps_cjk() -> None:
    # slugify replaces \/:*?"<>| with spaces, then collapses whitespace to "-",
    # so "A/B: C" -> "A B C" -> "A-B-C"; CJK characters survive.
    project = song_project([], title="測試/歌:曲")
    assert output_name(project, ExportRequest(format="lrc")) == "測試-歌-曲"


# ----------------------------------------------------------------------------- text exports


def test_export_lrc_writes_the_timed_lyrics(tmp_path: Path) -> None:
    project = song_project([timed_line("L001", "夜空", 10_000, 400)], duration_ms=45_000)
    store = make_store(tmp_path, project)
    target = export(store, ExportRequest(format="lrc"))
    # One singer ("m"): no singer prefixes in the output.
    assert target == store.paths.exports / "測試歌曲.lrc"
    text = target.read_text(encoding="utf-8")
    assert "[ti:測試歌曲]" in text
    # The line starts at 10_000 ms -> [00:10.00].
    assert "[00:10.00]夜空\n" in text
    assert "M:" not in text


def test_export_enhanced_lrc_uses_the_enhanced_suffix(tmp_path: Path) -> None:
    project = song_project([timed_line("L001", "夜空", 10_000, 400)], duration_ms=45_000)
    store = make_store(tmp_path, project)
    target = export(store, ExportRequest(format="elrc"))
    assert target == store.paths.exports / "測試歌曲.enhanced.lrc"
    # Tokens 夜 (10_000-10_400) and 空 (10_400-10_800); the last token gets a closing tag.
    assert "[00:10.00]<00:10.00>夜<00:10.40>空<00:10.80>" in target.read_text(encoding="utf-8")


def test_export_srt_starts_with_the_first_cue(tmp_path: Path) -> None:
    project = song_project([timed_line("L001", "夜空", 10_000, 400)], duration_ms=45_000)
    store = make_store(tmp_path, project)
    target = export(store, ExportRequest(format="srt"))
    assert target == store.paths.exports / "測試歌曲.srt"
    # Cue 1: 10_000 -> max(10_800, 10_000 + 500) = 10_800.
    assert target.read_text(encoding="utf-8").startswith("1\n00:00:10,000 --> 00:00:10,800\n夜空\n")


def test_export_kfproj_writes_a_zip_with_the_project_document(tmp_path: Path) -> None:
    project = song_project([timed_line("L001", "夜空", 10_000, 400)], duration_ms=45_000)
    store = make_store(tmp_path, project)
    target = export(store, ExportRequest(format="kfproj"))
    assert target == store.paths.exports / "測試歌曲.kfproj.zip"
    with zipfile.ZipFile(target) as archive:
        # The store root is "x.kfproj", so that is the archive's top-level folder.
        assert "x.kfproj/project.json" in archive.namelist()
        document = json.loads(archive.read("x.kfproj/project.json"))
        assert document["meta"]["title"] == "測試歌曲"


def test_export_lrc_without_token_times_raises_pipeline_error(tmp_path: Path) -> None:
    project = song_project([Line(id="L001", tokens=[Token(text="一")])])
    store = make_store(tmp_path, project)
    with pytest.raises(PipelineError):
        export(store, ExportRequest(format="lrc"))
