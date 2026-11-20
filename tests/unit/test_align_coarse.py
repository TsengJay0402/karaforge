from __future__ import annotations

import pytest

from karaforge.adapters.base import AsrWord
from karaforge.align.coarse import (
    CoarseSettings,
    LyricLine,
    coarse_align,
    distribute_lines,
    move_words_out_of_silence,
    transcript_letters,
)
from support import lyric_line, sung_words

LINES = ["夜空裡的星星慢慢亮起來", "我站在路口等一陣風", "你說過的話還留在耳邊"]


def three_lines() -> list[LyricLine]:
    return [lyric_line(f"L{index + 1}", text) for index, text in enumerate(LINES)]


def test_exact_transcript_anchors_every_line() -> None:
    words = [
        *sung_words(LINES[0], 10.0),
        *sung_words(LINES[1], 20.0),
        *sung_words(LINES[2], 30.0),
    ]
    windows = coarse_align(three_lines(), words, [(10, 15), (20, 24), (30, 35)], 40.0)
    assert [window.source for window in windows] == ["asr", "asr", "asr"]
    assert [window.quality for window in windows] == [1.0, 1.0, 1.0]
    for window, start in zip(windows, (10.0, 20.0, 30.0), strict=True):
        assert window.start_s == pytest.approx(start, abs=0.2)
    assert windows[0].end_s == pytest.approx(10.0 + 11 * 0.4, abs=0.3)
    assert windows[0].token_hints[0] == pytest.approx(10.0, abs=0.05)
    assert windows[0].token_hints[5] == pytest.approx(12.0, abs=0.05)


def test_misheard_but_similar_sounding_transcript_still_anchors() -> None:
    # What a recogniser really returned for the first line of a synthetic test song.
    heard = "請請慢慢聊起來"
    words = [*sung_words("也恐慌你啊", 37.5, 0.3), *sung_words(heard, 39.6, 0.45)]
    windows = coarse_align([lyric_line("L1", LINES[0])], words, [(37.6, 43.5)], 48.0)
    assert windows[0].source == "asr"
    assert 0.4 < windows[0].quality < 1.0
    assert windows[0].start_s == pytest.approx(37.6, abs=0.7)
    assert windows[0].end_s == pytest.approx(43.0, abs=1.0)


def test_traditional_lyrics_match_a_simplified_transcript() -> None:
    words = sung_words("夜空里的星星慢慢亮起来", 5.0)
    windows = coarse_align([lyric_line("L1", LINES[0])], words, [(5.0, 9.5)], 12.0)
    assert windows[0].quality == 1.0


def test_line_missing_from_the_transcript_is_placed_between_its_neighbours() -> None:
    words = [*sung_words(LINES[0], 10.0), *sung_words(LINES[2], 30.0)]
    regions = [(10.0, 14.5), (19.5, 23.0), (30.0, 34.5)]
    windows = coarse_align(three_lines(), words, regions, 40.0)
    assert [window.source for window in windows] == ["asr", "regions", "asr"]
    assert (windows[1].start_s, windows[1].end_s) == (19.5, 23.0)
    assert windows[1].quality == 0.0


def test_without_a_transcript_regions_are_used_one_per_line() -> None:
    regions = [(10.0, 14.5), (19.5, 23.0), (30.0, 34.5)]
    windows = coarse_align(three_lines(), [], regions, 40.0)
    assert [window.source for window in windows] == ["regions"] * 3
    assert [(window.start_s, window.end_s) for window in windows] == regions
    assert all(hint is None for window in windows for hint in window.token_hints)


def test_useless_transcript_falls_back_to_regions() -> None:
    nonsense = [AsrWord("zither", 4.0, 5.0), AsrWord("harp", 12.0, 13.0)]
    regions = [(10.0, 14.5), (19.5, 23.0), (30.0, 34.5)]
    windows = coarse_align(three_lines(), nonsense, regions, 40.0)
    assert [window.source for window in windows] == ["regions"] * 3


def test_voiced_time_is_shared_by_token_count_when_regions_do_not_match_lines() -> None:
    lines = [lyric_line("L1", "一二"), lyric_line("L2", "一二三四五六")]
    windows = coarse_align(lines, [], [(10.0, 18.0)], 20.0)
    assert [window.source for window in windows] == ["interpolated", "interpolated"]
    assert windows[0].start_s == pytest.approx(10.0, abs=0.01)
    assert windows[0].end_s == pytest.approx(12.0, abs=0.01)
    assert windows[1].start_s == pytest.approx(12.0, abs=0.01)
    assert windows[1].end_s == pytest.approx(18.0, abs=0.01)


def test_repeated_chorus_gets_two_separate_windows() -> None:
    chorus = LINES[0]
    lines = [lyric_line("L1", chorus), lyric_line("L2", LINES[1]), lyric_line("L3", chorus)]
    words = [
        *sung_words(chorus, 10.0),
        *sung_words(LINES[1], 20.0),
        *sung_words(chorus, 30.0),
    ]
    windows = coarse_align(lines, words, [(10, 15), (20, 24), (30, 35)], 40.0)
    assert [round(window.start_s) for window in windows] == [10, 20, 30]


def test_a_lone_far_away_match_does_not_stretch_the_window() -> None:
    line = lyric_line("L1", LINES[0])
    words = sung_words(LINES[0], 10.0)
    # The recogniser put the last word half a minute later (a hallucination in the outro).
    words[-1] = AsrWord(words[-1].text, 45.0, 45.4)
    windows = coarse_align([line], words, [(10.0, 14.5)], 50.0)
    assert windows[0].end_s < 16.0


def test_locked_token_anchors_its_line_exactly() -> None:
    lines = [
        lyric_line("L1", LINES[0]),
        lyric_line("L2", LINES[1], locked={0: (21.0, 21.3), 8: (24.2, 25.0)}),
    ]
    windows = coarse_align(lines, [], [(10.0, 14.5), (20.0, 25.0)], 40.0)
    assert windows[1].source == "anchor"
    assert windows[1].quality == 1.0
    assert windows[1].start_s == pytest.approx(21.0)
    assert windows[1].end_s == pytest.approx(25.0)
    # The unanchored first line has to fit before the locked line.
    assert windows[0].end_s <= 21.0


def test_transcript_that_contradicts_a_locked_token_is_ignored_for_that_line() -> None:
    lines = [
        lyric_line("L1", LINES[0], locked={0: (30.0, 30.4)}),
        lyric_line("L2", LINES[1]),
    ]
    # The recogniser heard line 2 *before* the locked start of line 1: impossible.
    words = sung_words(LINES[1], 12.0)
    windows = coarse_align(lines, words, [(30.0, 35.0), (36.0, 40.0)], 45.0)
    assert windows[0].source == "anchor"
    assert windows[1].source != "asr"
    assert windows[1].start_s >= windows[0].start_s


def test_windows_never_go_backwards_and_stay_inside_the_audio() -> None:
    words = [*sung_words(LINES[1], 20.0), *sung_words(LINES[0], 10.0)]
    windows = coarse_align(three_lines(), words, [(10, 14), (20, 24), (30, 34)], 36.0)
    starts = [window.start_s for window in windows]
    assert starts == sorted(starts)
    assert all(0.0 <= window.start_s <= window.end_s <= 36.0 for window in windows)


def test_thresholds_are_configurable() -> None:
    words = sung_words("夜空", 10.0)  # only two of eleven tokens were heard
    line = [lyric_line("L1", LINES[0])]
    strict = coarse_align(line, words, [(10.0, 15.0)], 20.0, CoarseSettings(min_line_quality=0.5))
    assert strict[0].source == "regions"
    loose = coarse_align(
        line,
        words,
        [(10.0, 15.0)],
        20.0,
        CoarseSettings(min_line_quality=0.1, min_global_quality=0.05),
    )
    assert loose[0].source == "asr"


def test_transcript_letters_interpolates_inside_words() -> None:
    letters, times = transcript_letters([AsrWord("你好", 1.0, 2.0), AsrWord("!?", 2.0, 2.1)])
    assert letters == "nihao"
    assert times == pytest.approx([1.0, 1.2, 1.4, 1.6, 1.8])


def test_words_in_silence_move_to_the_next_voiced_region() -> None:
    regions = [(5.0, 8.0), (11.0, 16.0)]
    words = [
        AsrWord("線", 7.2, 7.5),  # inside a region: untouched
        AsrWord("夜", 8.5, 9.0),  # in the pause: belongs to the next region
        AsrWord("空", 11.3, 11.6),
        AsrWord("遠", 30.0, 30.2),  # nothing follows: untouched
    ]
    moved = move_words_out_of_silence(words, regions)
    assert moved[0] == words[0]
    assert (moved[1].start_s, moved[1].end_s) == (11.0, 11.5)
    assert moved[2] == words[2]
    assert moved[3] == words[3]
    assert move_words_out_of_silence(words, []) == words


def test_distribute_lines_edge_cases() -> None:
    assert distribute_lines([], [(1.0, 2.0)], 0.0, 10.0) == []
    shared = distribute_lines([1, 3], [], 10.0, 18.0)
    assert [(start, end, source) for start, end, source in shared] == [
        (10.0, 12.0, "interpolated"),
        (12.0, 18.0, "interpolated"),
    ]
    spanning = distribute_lines([2, 2, 2], [(0.0, 3.0), (5.0, 8.0)], 0.0, 10.0)
    assert spanning[0][:2] == pytest.approx((0.0, 2.0), abs=0.01)
    assert spanning[1][0] == pytest.approx(2.0, abs=0.01)
    assert spanning[1][1] == pytest.approx(6.0, abs=0.01)
    assert spanning[2][:2] == pytest.approx((6.0, 8.0), abs=0.01)
