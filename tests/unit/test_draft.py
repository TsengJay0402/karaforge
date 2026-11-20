"""Unit tests for :mod:`karaforge.align.draft`."""

from __future__ import annotations

import pytest

from karaforge.adapters.base import AsrSegment, AsrWord, Transcript
from karaforge.align.draft import DraftLine, clean_text, draft_lyrics, to_project_lines
from karaforge.project.schema import Line

REGIONS: list[tuple[float, float]] = [(9.8, 16.0), (21.5, 24.0)]
"""Voice-activity regions covering every segment of the shared transcript but the first."""


def seg(start: float, words: list[tuple[str, float] | tuple[str, float, float]]) -> AsrSegment:
    """A segment whose words follow each other; an optional third number is a pause."""
    items: list[AsrWord] = []
    clock = start
    for word in words:
        if len(word) == 3:
            clock += word[2]
        items.append(AsrWord(word[0], clock, clock + word[1], 0.9))
        clock += word[1]
    return AsrSegment(
        "".join(item.text for item in items), items[0].start_s, items[-1].end_s, tuple(items)
    )


def shared_transcript() -> Transcript:
    """Four segments: one in silence, two inside the singing, one English with an annotation."""
    first = seg(0.0, [("字幕", 0.5), ("由志愿者", 0.5), ("提供", 0.5)])
    second = seg(
        10.0,
        [("车窗", 0.6), ("上的", 0.5), ("雨滴，", 0.6), ("排成", 0.5, 0.9), ("一条线", 0.9)],
    )
    third = seg(14.5, [("我", 0.3), (" love", 0.4), (" you", 0.4), ("。", 0.0)])
    fourth = seg(
        22.0,
        [(" Don't", 0.4), (" stop", 0.4), (" believin'", 0.6), (" [Music]", 1.0)],
    )
    return Transcript("zh", (first, second, third, fourth))


def draft_with_regions() -> list[DraftLine]:
    """The shared transcript cut into lines, with the silent first segment dropped."""
    return draft_lyrics(shared_transcript(), "zh-TW", regions=REGIONS)


def assert_times_are_sane(lines: list[Line]) -> None:
    """Token times never overlap inside a line and never move backwards across lines."""
    previous_start: int | None = None
    for line in lines:
        for index, token in enumerate(line.tokens):
            assert token.start_ms is not None
            assert token.end_ms is not None
            if previous_start is not None:
                assert token.start_ms >= previous_start
            previous_start = token.start_ms
            following = line.tokens[index + 1] if index + 1 < len(line.tokens) else None
            if following is not None:
                assert following.start_ms is not None
                assert token.end_ms <= following.start_ms


def test_full_case_cuts_lines_drops_silence_and_times_tokens() -> None:
    lines = draft_with_regions()
    assert len(lines) == 4
    assert [line.text for line in lines[:3]] == ["車窗上的雨滴", "排成一條線", "我 love you"]
    assert lines[3].text.startswith("Don't stop believin")

    first = lines[0]
    assert first.paragraph == 0
    assert first.start_s == pytest.approx(10.0, abs=1e-6)
    assert first.end_s == pytest.approx(11.7, abs=1e-6)
    assert [token.text for token in first.tokens] == ["車", "窗", "上", "的", "雨", "滴"]
    assert [token.start_s for token in first.tokens] == pytest.approx(
        [10.0, 10.3, 10.6, 10.85, 11.1, 11.4], abs=1e-6
    )
    assert [token.end_s for token in first.tokens] == pytest.approx(
        [10.3, 10.6, 10.85, 11.1, 11.4, 11.7], abs=1e-6
    )

    second = lines[1]
    assert second.text == "排成一條線"
    assert second.paragraph == 0
    assert (second.start_s, second.end_s) == pytest.approx((12.6, 14.0), abs=1e-6)
    # The 0.9 s pause before 排成 ends the line and spreads its two characters.
    assert [token.start_s for token in second.tokens] == pytest.approx(
        [12.6, 12.85, 13.1, 13.4, 13.7], abs=1e-6
    )

    third = lines[2]
    assert third.paragraph == 0
    assert third.start_s == pytest.approx(14.5, abs=1e-6)
    assert third.end_s == pytest.approx(15.6, abs=1e-6)
    assert [token.text for token in third.tokens] == ["我 ", "love ", "you"]

    fourth = lines[3]
    assert fourth.paragraph == 1
    assert fourth.start_s == pytest.approx(22.0, abs=1e-6)
    assert fourth.end_s == pytest.approx(23.4, abs=1e-6)
    assert fourth.tokens[0].text == "Don't "


def test_without_regions_nothing_is_dropped_for_silence() -> None:
    lines = draft_lyrics(shared_transcript(), "zh-TW")
    assert len(lines) == 5
    assert lines[0].text == "字幕由志願者提供"
    assert lines[1].text == "車窗上的雨滴"


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        (
            " Hello, world! (yeah) rock-n-roll - it's 5:30…",
            "en",
            "Hello world rock-n-roll it's 5 30",
        ),
        ("雨滴，排成一条线。", "zh-TW", "雨滴 排成一條線"),
        ("[Music]", "en", ""),
        ("（音樂）", "zh-TW", ""),
    ],
)
def test_clean_text(text: str, language: str, expected: str) -> None:
    assert clean_text(text, language) == expected


def test_over_long_line_is_cut_into_lines_of_at_most_max_width() -> None:
    characters = "一二三四五六七八九十"
    words: list[tuple[str, float] | tuple[str, float, float]] = [
        (char, 0.2) for char in characters * 3
    ]
    lines = draft_lyrics(Transcript("zh", (seg(0.0, words),)), "zh-TW")
    assert len(lines) == 2
    assert all(len(line.text) <= 16 for line in lines)
    assert "".join(line.text for line in lines) == characters * 3


def test_very_short_line_is_joined_to_its_neighbour() -> None:
    transcript = Transcript(
        "zh",
        (
            seg(0.0, [("啊", 0.3)]),
            seg(0.4, [("雨", 0.3), ("滴", 0.3), ("落", 0.3), ("下", 0.3)]),
        ),
    )
    lines = draft_lyrics(transcript, "zh-TW")
    assert len(lines) == 1
    assert lines[0].text == "啊雨滴落下"
    assert len(lines[0].tokens) == 5


def test_words_collapsed_on_one_instant_are_dropped() -> None:
    hallucination = AsrSegment(
        "幻覺文字呀", 3.0, 3.0, tuple(AsrWord(char, 3.0, 3.0, 0.9) for char in "幻覺文字呀")
    )
    transcript = Transcript("zh", (hallucination, seg(10.0, [("雨", 0.4), ("滴", 0.4)])))
    lines = draft_lyrics(transcript, "zh-TW")
    assert [line.text for line in lines] == ["雨滴"]


def test_to_project_lines_maps_draft_onto_schema_lines() -> None:
    project = to_project_lines(draft_with_regions())
    assert [line.id for line in project] == ["L001", "L002", "L003", "L004"]
    assert all(line.singer == "m" for line in project)
    assert to_project_lines(draft_with_regions(), singer="f")[0].singer == "f"

    first = project[0]
    assert first.tokens[0].text == "車"
    assert first.tokens[0].start_ms == 10000
    assert first.tokens[0].end_ms == 10300
    assert first.time_hint == (10000, 11700)
    assert all(token.source == "auto" for line in project for token in line.tokens)
    assert all(token.locked is False for line in project for token in line.tokens)
    assert all(
        token.confidence == pytest.approx(0.9, abs=1e-6)
        for line in project
        for token in line.tokens
    )
    assert_times_are_sane(project)


def test_to_project_lines_of_empty_draft_is_empty() -> None:
    assert to_project_lines([]) == []


def test_empty_transcript_gives_no_lines() -> None:
    assert draft_lyrics(Transcript("zh", ()), "zh-TW") == []


def test_apostrophes_stay_where_a_letter_carries_them() -> None:
    assert clean_text(" believin'", "en") == "believin'"
    assert clean_text("'cause I'm here", "en") == "'cause I'm here"
    # A quote mark next to a Chinese character is punctuation and goes.
    assert clean_text("「你好」’", "zh-TW") == "你好"


def test_every_line_keeps_its_time_as_a_hint_and_its_paragraph() -> None:
    draft = draft_with_regions()
    lines = to_project_lines(draft)
    assert [line.paragraph for line in lines] == [0, 0, 0, 1]
    for line in lines:
        assert line.time_hint == (line.tokens[0].start_ms, line.tokens[-1].end_ms)
    assert [line.text for line in lines] == [item.text for item in draft]
