"""Readings (zhuyin / pinyin) for Chinese lyrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from karaforge.errors import LyricsFormatError
from karaforge.project.schema import Line, Project, Token
from karaforge.text.ruby import (
    annotate_line,
    annotate_project,
    clear_project,
    default_kind,
    format_reading,
    han_readings,
    kind_of,
    line_readings,
    uses_taiwan_readings,
)
from karaforge.text.ruby_eval import evaluate, load_cases, readers
from karaforge.text.tokenize import tokenize

POLYPHONES = (
    Path(__file__).resolve().parent.parent / "fixtures" / "polyphones" / "zh-polyphones.tsv"
)


def read(text: str, *, taiwan: bool = True) -> str:
    return " ".join(reading or "-" for reading in han_readings(text, taiwan=taiwan))


def line_of(text: str) -> Line:
    return Line(id="L001", tokens=[Token(text=item.text) for item in tokenize(text)])


@pytest.mark.parametrize(
    ("reading", "kind", "expected"),
    [
        ("wo3", "zhuyin", "ㄨㄛˇ"),
        ("ma1", "zhuyin", "ㄇㄚ"),  # the first tone has no mark
        ("ma5", "zhuyin", "˙ㄇㄚ"),  # the neutral-tone dot goes in front
        ("lv4", "zhuyin", "ㄌㄩˋ"),
        ("xiong2", "zhuyin", "ㄒㄩㄥˊ"),
        ("wo3", "pinyin", "wǒ"),
        ("nv3", "pinyin", "nǚ"),
        ("ma5", "pinyin", "ma"),
        ("zhuang1", "pinyin", "zhuāng"),
    ],
)
def test_format_reading(reading: str, kind: str, expected: str) -> None:
    assert kind in ("zhuyin", "pinyin")
    assert format_reading(reading, "zhuyin" if kind == "zhuyin" else "pinyin") == expected


def test_words_decide_the_reading_in_either_script() -> None:
    assert read("銀行") == "yin2 hang2"
    assert read("銀行裡的音樂") == "yin2 hang2 li3 de5 yin1 yue4"
    assert read("银行里的音乐") == "yin2 hang2 li3 de5 yin1 yue4"
    assert read("旅行") == "lv3 xing2"
    assert read("快樂") == "kuai4 le4"


def test_other_text_is_skipped_without_shifting_the_readings() -> None:
    readings = han_readings("我 love 你, baby")
    assert len(readings) == len("我 love 你, baby")
    assert readings[0] == "wo3" and readings[7] == "ni3"
    assert [reading for index, reading in enumerate(readings) if index not in (0, 7)] == [None] * 12
    assert han_readings("") == []
    assert han_readings("hello") == [None] * 5


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 得: complement marker, "must", "to get"
        ("跑得很快", "pao3 de5 hen3 kuai4"),
        ("受得了", "shou4 de5 liao3"),
        ("做得到", "zuo4 de5 dao4"),
        ("我得回家", "wo3 dei3 hui2 jia1"),
        ("你得到了", "ni3 de2 dao4 le5"),
        ("我得了獎", "wo3 de2 le5 jiang3"),
        ("記不得", "ji4 bu4 de2"),
        # 地: adverb marker after a reduplication or an adverbial word
        ("靜靜地看著你", "jing4 jing4 de5 kan4 zhe5 ni3"),
        ("不停地跳", "bu4 ting2 de5 tiao4"),
        ("這片大地", "zhe4 pian4 da4 di4"),
        # 了: "cannot / can …"
        ("忘不了你", "wang4 bu4 liao3 ni3"),
        ("我懂了", "wo3 dong3 le5"),
        # 著: zháo after 不 / 得 and in 著了迷
        ("找不著", "zhao3 bu4 zhao2"),
        ("他著了迷", "ta1 zhao2 le5 mi2"),
        ("看著你", "kan4 zhe5 ni3"),
        ("著名", "zhu4 ming2"),
        # 還: adverb or "to return"
        ("我還在", "wo3 hai2 zai4"),
        ("還有你", "hai2 you3 ni3"),
        ("還給我", "huan2 gei3 wo3"),
        ("還你自由", "huan2 ni3 zi4 you2"),
        ("怎麼還", "zen3 me5 huan2"),
    ],
)
def test_function_words_follow_their_context(text: str, expected: str) -> None:
    assert read(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("一個人", "yi2 ge4 ren2"),
        ("一天", "yi4 tian1"),
        ("一起走", "yi4 qi3 zou3"),
        ("一隻鳥", "yi4 zhi1 niao3"),
        ("一生一世", "yi4 sheng1 yi2 shi4"),
        ("第一次", "di4 yi1 ci4"),
        ("十一月", "shi2 yi1 yue4"),
        ("一二三", "yi1 er4 san1"),
        ("唯一的愛", "wei2 yi1 de5 ai4"),
        ("不要", "bu2 yao4"),
        ("不好", "bu4 hao3"),
        ("不一樣", "bu4 yi2 yang4"),
        ("對不起", "dui4 bu4 qi3"),
    ],
)
def test_tone_sandhi_of_one_and_not(text: str, expected: str) -> None:
    assert read(text) == expected


def test_traditional_characters_that_simplified_merges() -> None:
    assert read("乾杯") == "gan1 bei1"
    assert read("幹嘛") == "gan4 ma2"
    assert read("只要你").split()[0] == "zhi3"
    assert read("發現") == "fa1 xian4"
    assert read("頭髮", taiwan=False) == "tou2 fa4"


@pytest.mark.parametrize(
    ("text", "taiwan", "mainland"),
    [
        ("垃圾", "le4 se4", "la1 ji1"),
        ("寂寞的夕陽", "ji2 mo4 de5 xi4 yang2", "ji4 mo4 de5 xi1 yang2"),
        ("擁抱你", "yong3 bao4 ni3", "yong1 bao4 ni3"),
        ("珍惜", "zhen1 xi2", "zhen1 xi1"),
        ("頭髮", "tou2 fa3", "tou2 fa4"),
        ("星期天", "xing1 qi2 tian1", "xing1 qi1 tian1"),
        ("突然", "tu2 ran2", "tu1 ran2"),
        ("奇蹟", "qi2 ji1", "qi2 ji4"),
        ("法國", "fa4 guo2", "fa3 guo2"),
        ("微笑", "wei2 xiao4", "wei1 xiao4"),
    ],
)
def test_taiwan_readings_replace_the_mainland_ones(text: str, taiwan: str, mainland: str) -> None:
    assert read(text, taiwan=True) == taiwan
    assert read(text, taiwan=False) == mainland


def test_default_kind_follows_the_language() -> None:
    assert default_kind("zh-TW") == "zhuyin"
    assert default_kind("zh") == "zhuyin"
    assert default_kind("zh-CN") == "pinyin"
    assert default_kind("zh-HK") == "pinyin"
    assert default_kind("ja") is None and default_kind("en") is None
    assert uses_taiwan_readings("zh-TW") and not uses_taiwan_readings("zh-CN")


def test_line_readings_follow_the_tokens() -> None:
    texts = [item.text for item in tokenize("我愛你, baby 行不行？")]
    assert texts == ["我", "愛", "你, ", "baby ", "行", "不", "行？"]
    assert line_readings(texts, "zhuyin") == [
        "ㄨㄛˇ",
        "ㄞˋ",
        "ㄋㄧˇ",
        None,
        "ㄒㄧㄥˊ",
        "ㄅㄨˋ",
        "ㄒㄧㄥˊ",
    ]
    assert line_readings(texts, "pinyin", taiwan=False) == [
        "wǒ",
        "ài",
        "nǐ",
        None,
        "xíng",
        "bù",
        "xíng",
    ]
    assert line_readings([], "zhuyin") == []


def test_annotating_a_line_keeps_manual_readings() -> None:
    line = line_of("銀行 open 了")
    manual = line.tokens[1].model_copy(update={"ruby": "ㄒㄧㄥˊ", "ruby_source": "manual"})
    stale = line.tokens[2].model_copy(update={"ruby": "ㄎㄞ", "ruby_source": "auto"})
    line = line.model_copy(update={"tokens": [line.tokens[0], manual, stale, line.tokens[3]]})
    annotated = annotate_line(line, "zhuyin")
    assert [(token.ruby, token.ruby_source) for token in annotated.tokens] == [
        ("ㄧㄣˊ", "auto"),
        ("ㄒㄧㄥˊ", "manual"),  # typed by the user: never replaced
        (None, None),  # a Latin word loses a stale automatic reading
        ("˙ㄌㄜ", "auto"),
    ]
    # Text and timing are untouched, and the original line is not modified.
    assert annotated.text == line.text
    assert line.tokens[0].ruby is None
    assert annotate_line(annotated, "zhuyin") == annotated


def project_of(language: str, *texts: str) -> Project:
    project = Project()
    project.meta.language = language
    project.lines = [
        Line(id=f"L{number:03d}", tokens=[Token(text=item.text) for item in tokenize(text)])
        for number, text in enumerate(texts, start=1)
    ]
    return project


def test_annotating_a_project_uses_the_language_and_can_switch_kind() -> None:
    project = project_of("zh-TW", "寂寞的夜", "love 你")
    assert kind_of(project.lines) is None
    assert annotate_project(project) == 5
    assert [token.ruby for token in project.lines[0].tokens] == ["ㄐㄧˊ", "ㄇㄛˋ", "˙ㄉㄜ", "ㄧㄝˋ"]
    assert [token.ruby for token in project.lines[1].tokens] == [None, "ㄋㄧˇ"]
    assert kind_of(project.lines) == "zhuyin"

    # Switching to pinyin replaces the automatic readings; the Taiwan reading stays (jí).
    assert annotate_project(project, "pinyin") == 5
    assert [token.ruby for token in project.lines[0].tokens] == ["jí", "mò", "de", "yè"]
    assert kind_of(project.lines) == "pinyin"
    # Without a kind the project keeps the one it has.
    annotate_project(project)
    assert project.lines[0].tokens[0].ruby == "jí"

    assert clear_project(project) == 5
    assert all(token.ruby is None for line in project.lines for token in line.tokens)
    assert kind_of(project.lines) is None


def test_mainland_projects_get_pinyin_and_other_languages_nothing() -> None:
    mainland = project_of("zh-CN", "寂寞的夜")
    annotate_project(mainland)
    assert [token.ruby for token in mainland.lines[0].tokens] == ["jì", "mò", "de", "yè"]

    japanese = project_of("ja", "夜空ノムコウ")
    assert annotate_project(japanese) == 0
    assert all(token.ruby is None for token in japanese.lines[0].tokens)


def test_manual_readings_survive_annotating_and_clearing() -> None:
    project = project_of("zh-TW", "一行白鷺")
    tokens = project.lines[0].tokens
    tokens[1] = tokens[1].model_copy(update={"ruby": "ㄏㄤˊ", "ruby_source": "manual"})
    annotate_project(project)
    assert [token.ruby for token in project.lines[0].tokens] == ["ㄧˋ", "ㄏㄤˊ", "ㄅㄞˊ", "ㄌㄨˋ"]
    assert clear_project(project) == 3
    assert [token.ruby for token in project.lines[0].tokens] == [None, "ㄏㄤˊ", None, None]


# ------------------------------------------------------------------ the polyphone test set


def test_polyphone_test_set_is_well_formed() -> None:
    cases = load_cases(POLYPHONES)
    assert len(cases) >= 50
    assert len(cases) == 171 and len({case.char for case in cases}) == 68
    by_char: dict[str, set[str]] = {}
    for case in cases:
        by_char.setdefault(case.char, set()).add(case.expected)
        assert case.expected[-1] in "12345" and case.expected[:-1].isalpha()
    # Every character is tested with at least two of its readings.
    assert all(len(readings) >= 2 for readings in by_char.values())


def test_polyphone_accuracy_is_what_the_documentation_says(repo_root: Path) -> None:
    cases = load_cases(POLYPHONES)
    results = {name: evaluate(cases, reader) for name, reader in readers().items()}
    engine = results["KaraForge (Taiwan readings)"]
    simplified = results["pypinyin on Simplified text"]
    as_written = results["pypinyin on the text as written"]
    # Measured on 2026-11-21 with pypinyin 0.55: 158, 151 and 106 of 171.  The floors leave
    # room for a few cases to move with a new dictionary version, nothing more.
    assert engine.correct >= 154
    assert simplified.correct >= 145
    assert engine.correct >= simplified.correct > as_written.correct
    # The published figure must be the measured one.
    documented = (repo_root / "docs" / "ruby.md").read_text(encoding="utf-8")
    assert f"{engine.correct} / {engine.total}" in documented
    assert f"{engine.accuracy:.1%}" in documented


def test_malformed_test_sets_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "set.tsv"
    path.write_text("# comment\n\n我【行】\txing2\n", encoding="utf-8")
    cases = load_cases(path)
    assert [(case.phrase, case.index, case.char, case.expected) for case in cases] == [
        ("我行", 1, "行", "xing2")
    ]
    for broken in ("沒有標記\txing2", "【行】沒有讀音", "【銀行】\thang2", "【行】【行】\txing2"):
        path.write_text(broken + "\n", encoding="utf-8")
        with pytest.raises(LyricsFormatError):
            load_cases(path)
