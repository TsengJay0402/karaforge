"""Round-trip and parsing tests of the lyric / subtitle formats."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from karaforge.ass import render_ass
from karaforge.errors import LyricsFormatError
from karaforge.io.exporters.archive import export_project_zip
from karaforge.io.exporters.lrc import export_enhanced_lrc, export_lrc
from karaforge.io.exporters.srt import export_srt
from karaforge.io.exporters.ultrastar import (
    beat_grid,
    export_ultrastar,
    parse_ultrastar,
    pitch_table,
)
from karaforge.io.importers import load_lyrics
from karaforge.io.importers.ass import parse_ass_text
from karaforge.io.importers.lrc import parse_lrc_text
from karaforge.io.importers.srt import parse_srt_text
from karaforge.io.timed import (
    ImportedLine,
    ImportedUnit,
    clock,
    lines_from_imported,
    tokens_from_units,
)
from karaforge.layout.engine import build_plan
from karaforge.project import Line, Project, ProjectStore, Token
from support import song_project, timed_line


def demo() -> Project:
    """Three singers, a pause inside a line, mixed scripts; every time is a multiple of 10 ms."""
    project = song_project(
        [
            timed_line("L001", "夜空裡的星星", 10_000, 400, singer="m"),
            timed_line("L002", "慢慢 so bright", 13_000, 350, singer="f", gap_ms=150),
            timed_line("L003", "we sing, 一起唱!", 30_000, 500, singer="all", paragraph=1),
        ],
        duration_ms=45_000,
    )
    project.meta.composer = "曲人"
    return project


def token_times(lines: list[Line]) -> list[list[tuple[str, int | None, int | None]]]:
    return [[(t.text, t.start_ms, t.end_ms) for t in line.tokens] for line in lines]


def test_clock_formats() -> None:
    assert clock(83_456) == "01:23.46"
    assert clock(83_456, digits=3) == "01:23.456"
    assert clock(3_723_456, digits=3, hours=True, separator=",") == "01:02:03,456"
    assert clock(59_999) == "01:00.00"  # rounding carries into the seconds
    assert clock(-5) == "00:00.00"


# ------------------------------------------------------------------------------------ LRC


def test_simple_lrc_round_trip_keeps_text_line_times_and_singers() -> None:
    project = demo()
    text = export_lrc(project, singers=True)
    assert "[ti:測試歌曲]" in text and "[ar:某歌手]" in text and "[au:曲人]" in text
    assert "[00:10.00]M: 夜空裡的星星" in text
    assert "[00:30.00]D: we sing, 一起唱!" in text
    meta, imported = parse_lrc_text(text)
    assert meta == {"title": "測試歌曲", "artist": "某歌手", "composer": "曲人"}
    lines = lines_from_imported(imported)
    assert [line.text for line in lines] == [line.text for line in project.lines]
    assert [line.singer for line in lines] == ["m", "f", "all"]
    assert [line.time_hint for line in lines] == [
        (10_000, 13_000),
        (13_000, 14_850),  # the empty row written before the long pause ends the line
        (30_000, 32_500),
    ]
    assert [line.paragraph for line in lines] == [0, 0, 1]
    assert all(not token.is_timed for line in lines for token in line.tokens)


def test_simple_lrc_without_singer_prefixes() -> None:
    text = export_lrc(demo())
    assert "[00:13.00]慢慢 so bright" in text
    assert "M:" not in text


def test_enhanced_lrc_round_trip_is_exact() -> None:
    project = demo()
    text = export_enhanced_lrc(project, singers=True)
    assert "[00:10.00]M: <00:10.00>夜<00:10.40>空" in text
    # 150 ms pause after each token of line 2: the end is written as its own tag.
    assert "<00:13.00>慢<00:13.35><00:13.50>慢 <00:13.85><00:14.00>so " in text
    _meta, imported = parse_lrc_text(text)
    lines = lines_from_imported(imported)
    assert token_times(lines) == token_times(project.lines)
    assert [line.singer for line in lines] == ["m", "f", "all"]
    assert all(token.locked and token.source == "import" for line in lines for token in line.tokens)
    assert all(line.time_hint is None for line in lines)


def test_enhanced_lrc_with_millisecond_precision() -> None:
    project = song_project([timed_line("L001", "一二", 1_234, 567)])
    text = export_enhanced_lrc(project, digits=3)
    assert "<00:01.234>一<00:01.801>二<00:02.368>" in text
    lines = lines_from_imported(parse_lrc_text(text)[1])
    assert token_times(lines) == token_times(project.lines)


def test_lrc_details() -> None:
    text = (
        "﻿[ti: 歌名 ]\n[offset:500]\n[by:someone]\n"
        "[00:20.50][01:10.5]副歌重複兩次\n"
        "[00:05:00]冒號當小數點\n"
        "[00:30.000]\n"
        "沒有時間標記的行會被忽略\n"
        "[00:40.00]<00:40.00>word <00:40.50>without <00:41.00>end\n"
    )
    meta, imported = parse_lrc_text(text)
    assert meta == {"title": "歌名"}
    assert [(line.text, line.start_ms, line.end_ms) for line in imported] == [
        ("冒號當小數點", 4_500, 20_000),
        ("副歌重複兩次", 20_000, 29_500),
        ("word without end", 39_500, 40_900),
        ("副歌重複兩次", 70_000, None),
    ]
    units = imported[2].units
    assert [(unit.text, unit.start_ms, unit.end_ms) for unit in units] == [
        ("word ", 39_500, 40_000),
        ("without ", 40_000, 40_500),
        ("end", 40_500, 40_900),  # no closing tag: a short default length
    ]


def test_lrc_text_before_the_first_word_tag_starts_with_the_line() -> None:
    _meta, imported = parse_lrc_text("[00:10.00]Oh <00:10.60>yeah<00:11.00>\n")
    assert [(u.text, u.start_ms, u.end_ms) for u in imported[0].units] == [
        ("Oh ", 10_000, 10_600),
        ("yeah", 10_600, 11_000),
    ]


# ------------------------------------------------------------------------------------ SRT


def test_srt_round_trip() -> None:
    project = demo()
    text = export_srt(project)
    assert text.startswith("1\n00:00:10,000 --> 00:00:12,400\n夜空裡的星星\n")
    assert "3\n00:00:30,000 --> 00:00:32,500\nwe sing, 一起唱!\n" in text
    imported = parse_srt_text(text)
    assert [(line.text, line.start_ms, line.end_ms) for line in imported] == [
        ("夜空裡的星星", 10_000, 12_400),
        ("慢慢 so bright", 13_000, 14_850),
        ("we sing, 一起唱!", 30_000, 32_500),
    ]
    lines = lines_from_imported(imported)
    assert [line.time_hint for line in lines] == [
        (10_000, 12_400),
        (13_000, 14_850),
        (30_000, 32_500),
    ]


def test_srt_cues_do_not_overlap_and_have_a_minimum_length() -> None:
    project = song_project(
        [timed_line("L001", "啊", 1_000, 100), timed_line("L002", "喔", 1_200, 100)]
    )
    imported = parse_srt_text(export_srt(project))
    assert [(line.start_ms, line.end_ms) for line in imported] == [(1_000, 1_200), (1_200, 1_700)]


def test_srt_markup_and_multi_row_cues() -> None:
    text = (
        "7\r\n00:00:01.5 --> 00:00:03,500\r\n<i>第一行</i>\r\n{\\an8}second row\r\n"
        "\r\nnot a cue\r\n"
    )
    imported = parse_srt_text(text)
    assert [(line.text, line.start_ms, line.end_ms) for line in imported] == [
        ("第一行", 1_500, 2_500),
        ("second row", 2_500, 3_500),
    ]


# ------------------------------------------------------------------------------------ ASS


def test_own_ass_export_round_trips_through_the_karaoke_comments() -> None:
    project = demo()
    script = render_ass(build_plan(project), title=project.meta.title)
    meta, imported = parse_ass_text(script)
    assert meta == {"title": "測試歌曲"}
    lines = lines_from_imported(imported)
    assert token_times(lines) == token_times(project.lines)
    assert [line.singer for line in lines] == ["m", "f", "all"]


def test_foreign_karaoke_ass_with_k_tags() -> None:
    karaoke = "{\\an8\\k50}Twin{\\kf30}kle {\\k20}{\\ko100}star"
    script = (
        "[Script Info]\nTitle: Default Aegisub file\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:05.00,0:00:08.00,Default,女,0,0,0,,{karaoke}\n"
        f"Dialogue: 1,0:00:05.00,0:00:08.00,Default,女,0,0,0,,{karaoke}\n"
        "Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\\i1}純文字\\N第二段 \\{大括號\\}\n"
        "Dialogue: 0,0:00:09.00,0:00:09.50,Default,,0,0,0,,{\\p1}m 0 0 l 10 0 10 10{\\p0}\n"
    )
    meta, imported = parse_ass_text(script)
    assert meta == {}
    assert [(line.text, line.start_ms, line.end_ms, line.singer) for line in imported] == [
        ("純文字 第二段 {大括號}", 1_000, 3_500, None),
        ("Twinkle star", 5_000, 7_000, "f"),
    ]
    assert [(unit.text, unit.start_ms, unit.end_ms) for unit in imported[1].units] == [
        ("Twin", 5_000, 5_500),
        ("kle ", 5_500, 5_800),
        ("star", 6_000, 7_000),  # the empty 20 cs tag is a pause
    ]
    lines = lines_from_imported(imported)
    assert lines[0].time_hint == (1_000, 3_500)
    assert [token.text for token in lines[1].tokens] == ["Twin", "kle ", "star"]


# ------------------------------------------------------------------------------ UltraStar


def test_ultrastar_round_trip_within_one_beat() -> None:
    project = demo()
    project.analysis.tempo_bpm = 96.0
    table = pitch_table(project, [[60, 62, 64, 65, 67, 69], [None, 57], [55]])
    text = export_ultrastar(project, pitches=table, audio_name="song.mp3", video_name="song.mp4")
    assert text.startswith(
        "#TITLE:測試歌曲\n#ARTIST:某歌手\n#MP3:song.mp3\n#AUDIO:song.mp3\n#VIDEO:song.mp4\n"
    )
    assert "#BPM:384\n" in text and "#GAP:10000\n" in text
    assert text.rstrip().endswith("E")
    assert ": 0 10 0 夜\n: 10 10 2 空\n" in text
    headers, imported, pitches = parse_ultrastar(text)
    assert headers["title"] == "測試歌曲" and headers["bpm"] == "384"
    assert [line.text for line in imported] == [line.text for line in project.lines]
    beat_ms = 15000 / 384
    for line, original in zip(lines_from_imported(imported), project.lines, strict=True):
        assert [token.text for token in line.tokens] == [token.text for token in original.tokens]
        for token, reference in zip(line.tokens, original.tokens, strict=True):
            assert abs((token.start_ms or 0) - (reference.start_ms or 0)) <= beat_ms
            assert abs((token.end_ms or 0) - (reference.end_ms or 0)) <= beat_ms + 1
    assert pitches[0] == [60, 62, 64, 65, 67, 69]
    assert pitches[1][:2] == [60, 57]  # unknown pitch is written as C4


def test_ultrastar_beat_grid_and_errors() -> None:
    assert beat_grid(None) == 300.0
    assert beat_grid(96.0) == 384.0  # 39 ms per beat
    assert beat_grid(150.0) == 300.0
    assert beat_grid(5.0) == 300.0
    with pytest.raises(LyricsFormatError):
        export_ultrastar(Project(lines=[Line(id="L001", tokens=[Token(text="一")])]))


def test_ultrastar_spaces_move_to_the_next_syllable() -> None:
    project = song_project([timed_line("L001", "so bright 星", 1_000, 300)])
    text = export_ultrastar(project)
    notes = [row for row in text.splitlines() if row.startswith(":")]
    assert [row.split(" ", 4)[4] for row in notes] == ["so", " bright", " 星"]
    _headers, imported, _pitches = parse_ultrastar(text)
    assert [unit.text for unit in imported[0].units] == ["so ", "bright ", "星"]


# ----------------------------------------------------------------------- shared helpers


def test_units_covering_several_tokens_are_split_and_only_the_first_is_locked() -> None:
    tokens = tokens_from_units(
        [
            ImportedUnit("你好", 1_000, 1_600),
            ImportedUnit(" ", 1_600, 1_600),
            ImportedUnit("hello world ", 2_000, 3_000),
            ImportedUnit("!", 3_000, 3_000),
        ]
    )
    assert [(t.text, t.start_ms, t.end_ms, t.locked) for t in tokens] == [
        ("你", 1_000, 1_300, True),
        ("好 ", 1_300, 1_600, False),
        ("hello ", 2_000, 2_500, True),
        ("world !", 2_500, 3_000, False),
    ]
    assert tokens[1].confidence == pytest.approx(0.3)
    assert all(token.source == "import" for token in tokens)


def test_lines_from_imported_infers_missing_ends_and_paragraphs() -> None:
    lines = lines_from_imported(
        [
            ImportedLine("第一句", 1_000),
            ImportedLine("第二句", 3_000, 4_000),
            ImportedLine("   ", 5_000),
            ImportedLine("第三句", 9_000),
        ]
    )
    assert [line.id for line in lines] == ["L001", "L002", "L003"]
    assert [line.time_hint for line in lines] == [(1_000, 3_000), (3_000, 4_000), (9_000, None)]
    assert [line.paragraph for line in lines] == [0, 0, 1]


def test_load_lyrics_dispatches_on_the_extension(tmp_path: Path) -> None:
    project = demo()
    files = {
        "a.lrc": export_enhanced_lrc(project),
        "b.srt": export_srt(project),
        "c.ass": render_ass(build_plan(project)),
        "d.txt": "[男] 夜空裡的星星\n",
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    assert load_lyrics(tmp_path / "a.lrc").lines[0].tokens[0].start_ms == 10_000
    assert load_lyrics(tmp_path / "b.srt").lines[0].time_hint == (10_000, 12_400)
    assert load_lyrics(tmp_path / "c.ass").lines[2].tokens[-1].end_ms == 32_500
    assert load_lyrics(tmp_path / "d.txt").lines[0].text == "夜空裡的星星"
    (tmp_path / "e.docx").write_bytes(b"x")
    with pytest.raises(LyricsFormatError) as info:
        load_lyrics(tmp_path / "e.docx")
    assert ".lrc" in (info.value.hint_en or "")
    for name in ("empty.lrc", "empty.srt", "empty.ass"):
        (tmp_path / name).write_text("nothing useful\n", encoding="utf-8")
        with pytest.raises(LyricsFormatError):
            load_lyrics(tmp_path / name)


def test_project_zip_contains_document_and_media_but_no_cache(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "我的歌.kfproj")
    store.create(demo())
    (store.paths.media / "audio.wav").write_bytes(b"RIFF" + b"\0" * 100)
    (store.paths.cache / "separate").mkdir()
    (store.paths.cache / "separate" / "big.bin").write_bytes(b"x" * 1000)
    (store.paths.exports / "video.mp4").write_bytes(b"mp4")
    target = tmp_path / "out" / "packed.zip"
    assert export_project_zip(store, target) == 2
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == [
            "我的歌.kfproj/media/audio.wav",
            "我的歌.kfproj/project.json",
        ]
        document = json.loads(archive.read("我的歌.kfproj/project.json"))
        assert document["meta"]["title"] == "測試歌曲"
    assert export_project_zip(store, target, include_exports=True) == 3
    with zipfile.ZipFile(target) as archive:
        assert "我的歌.kfproj/exports/video.mp4" in archive.namelist()
