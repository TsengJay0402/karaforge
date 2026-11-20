from __future__ import annotations

from pathlib import Path

import pytest

from karaforge.errors import LyricsFormatError
from karaforge.io.importers.lyrics_txt import (
    parse_lyrics_file,
    parse_lyrics_text,
    read_text_file,
    tokens_from_text,
)


def test_metadata_with_half_and_full_width_colon() -> None:
    text = "# title: My Song\n# 歌名:中文歌\n# artist:歌手\n# 作詞:詞人\n# composer:曲人\n[男] 你好"
    parsed = parse_lyrics_text(text)
    assert parsed.meta == {
        "title": "中文歌",
        "artist": "歌手",
        "lyricist": "詞人",
        "composer": "曲人",
    }


def test_unknown_metadata_keys_are_ignored() -> None:
    parsed = parse_lyrics_text("# unknown: value\n# source: x\n[男] 你好")
    assert parsed.meta == {}


def test_standard_singer_tags() -> None:
    parsed = parse_lyrics_text(
        "[男] 第一句\n[女] 第二句\n[合] together\n[m] 第四句\n[f] 第五句\n[all] 第六句"
    )
    assert [line.singer for line in parsed.lines] == ["m", "f", "all", "m", "f", "all"]
    assert [singer.id for singer in parsed.singers] == ["m", "f", "all"]


def test_custom_singer_gets_slug_id_and_fresh_theme_slot() -> None:
    parsed = parse_lyrics_text("[Amy] 一\n[Beth] 二\n[Cara] 三")
    custom = parsed.singers[3:]
    assert [(singer.id, singer.label, singer.theme_slot) for singer in custom] == [
        ("amy", "Amy", "male"),
        ("beth", "Beth", "female"),
        ("cara", "Cara", "duet"),
    ]
    assert [line.singer for line in parsed.lines] == ["amy", "beth", "cara"]


def test_repeated_custom_tag_reuses_singer() -> None:
    parsed = parse_lyrics_text("[Amy] 一\n[Amy] 二")
    assert [line.singer for line in parsed.lines] == ["amy", "amy"]
    assert [singer.id for singer in parsed.singers[3:]] == ["amy"]


def test_unmarked_line_inherits_previous_singer() -> None:
    parsed = parse_lyrics_text("[女] 第一句\n第二句\n第三句")
    assert [line.singer for line in parsed.lines] == ["f", "f", "f"]


def test_blank_lines_open_one_paragraph() -> None:
    parsed = parse_lyrics_text("[男] 一\n\n\n\n[男] 二\n\n[男] 三")
    assert [line.paragraph for line in parsed.lines] == [0, 1, 2]


def test_leading_blank_lines_do_not_open_a_paragraph() -> None:
    parsed = parse_lyrics_text("\n\n[男] 一")
    assert [line.paragraph for line in parsed.lines] == [0]


def test_tag_only_line_switches_singer_without_a_lyric_line() -> None:
    parsed = parse_lyrics_text("[男] 一\n[女]\n二")
    assert len(parsed.lines) == 2
    assert [line.singer for line in parsed.lines] == ["m", "f"]
    assert [line.text for line in parsed.lines] == ["一", "二"]


def test_manual_ruby_becomes_token_ruby() -> None:
    parsed = parse_lyrics_text("[男] 他還是重{ㄔㄨㄥˊ}複了一次")
    tokens = parsed.lines[0].tokens
    assert len(tokens) == 8
    assert tokens[3].text == "重"
    assert tokens[3].ruby == "ㄔㄨㄥˊ"
    assert tokens[3].ruby_source == "manual"
    assert tokens[2].ruby is None
    assert tokens[2].ruby_source is None


def test_line_ids_are_sequentially_numbered() -> None:
    parsed = parse_lyrics_text("[男] 一\n[男] 二\n[男] 三")
    assert [line.id for line in parsed.lines] == ["L001", "L002", "L003"]


def test_file_without_lyrics_raises() -> None:
    with pytest.raises(LyricsFormatError):
        parse_lyrics_text("# title: 只有 metadata\n\n")


def test_utf8_bom_is_stripped() -> None:
    parsed = parse_lyrics_text("﻿[男] 你好")
    assert [line.text for line in parsed.lines] == ["你好"]


def test_lrc_time_tags_are_dropped_not_treated_as_singers(tmp_path: Path) -> None:
    path = tmp_path / "lyrics.txt"
    path.write_text(
        "[ti:貼上的 LRC]\n[ar:某人]\n[offset:120]\n"
        "[00:01.00] 前奏\n[01:23.45][02:10.00] 歌<01:23.90>詞開始\n[00:05.00]\n",
        encoding="utf-8",
    )
    parsed = parse_lyrics_file(path)
    assert parsed.meta == {"title": "貼上的 LRC", "artist": "某人"}
    assert [line.singer for line in parsed.lines] == ["m", "m"]
    assert [line.text for line in parsed.lines] == ["前奏", "歌詞開始"]
    assert len(parsed.singers) == 3


@pytest.mark.parametrize(
    "text", ["abc好", "我們的歌", "[男] 夜空裡的星星慢慢亮起來\n[女] 你說過的話"]
)
def test_read_text_file_decodes_big5(tmp_path: Path, text: str) -> None:
    # Even byte lengths used to be mis-read as UTF-16; odd and even lengths are both covered.
    path = tmp_path / "big5.txt"
    path.write_bytes(text.encode("big5"))
    assert read_text_file(path) == text


def test_read_text_file_decodes_gb18030_and_utf16(tmp_path: Path) -> None:
    simplified = "我们的歌 这个时候 没有说过的话"
    path = tmp_path / "gbk.txt"
    path.write_bytes(simplified.encode("gb18030"))
    assert read_text_file(path) == simplified
    path = tmp_path / "utf16.txt"
    path.write_bytes("你好 world".encode("utf-16"))
    assert read_text_file(path) == "你好 world"


def test_read_text_file_rejects_undecodable_bytes(tmp_path: Path) -> None:
    path = tmp_path / "junk.txt"
    path.write_bytes(b"\xff\xff\xff\x80\x81")
    with pytest.raises(LyricsFormatError) as info:
        read_text_file(path)
    assert "UTF-8" in (info.value.hint_en or "")


def test_read_text_file_strips_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "你好".encode())
    assert read_text_file(path) == "你好"


def test_read_text_file_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(LyricsFormatError):
        read_text_file(tmp_path / "missing.txt")


def test_tokens_from_text_sets_manual_ruby_source() -> None:
    tokens = tokens_from_text("重{ㄔㄨㄥˊ}複")
    assert [(token.text, token.ruby, token.ruby_source) for token in tokens] == [
        ("重", "ㄔㄨㄥˊ", "manual"),
        ("複", None, None),
    ]
