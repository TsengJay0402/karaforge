from __future__ import annotations

import pytest

from karaforge.adapters.base import AsrWord
from karaforge.align.coarse import (
    CoarseSettings,
    LyricLine,
    clean_words,
    coarse_align,
    distribute_lines,
    drop_collapsed_words,
    transcript_letters,
)
from karaforge.text.tokenize import TextToken, tokenize
from support import lyric_line, sung_words

LINES = ["夜空裡的星星慢慢亮起來", "我站在路口等一陣風", "你說過的話還留在耳邊"]


def sung_tokens(text: str) -> list[TextToken]:
    return [token for token in tokenize(text) if token.core]


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


def test_imported_line_time_is_used_instead_of_searching() -> None:
    lines = [
        lyric_line("L1", LINES[0], hint=(10.0, 14.6)),
        lyric_line("L2", LINES[1], hint=(20.0, None)),
        lyric_line("L3", LINES[2]),
    ]
    # The recogniser heard line 1 somewhere else entirely; the file's time wins.
    words = [*sung_words(LINES[0], 50.0), *sung_words(LINES[2], 30.0)]
    windows = coarse_align(lines, words, [(10, 14.6), (20, 24), (30, 35), (50, 55)], 60.0)
    assert [window.source for window in windows] == ["hint", "hint", "asr"]
    assert (windows[0].start_s, windows[0].end_s) == (10.0, 14.6)
    assert windows[0].quality == pytest.approx(0.8)
    # Without an end the length is estimated from the number of tokens.
    assert windows[1].start_s == 20.0
    assert windows[1].end_s == pytest.approx(20.0 + 9 * 0.4 * 1.5)
    assert windows[2].start_s == pytest.approx(30.0, abs=0.2)


def test_imported_line_that_lasts_through_an_interlude_is_shortened() -> None:
    line = lyric_line("L1", "一二三", hint=(10.0, 40.0))  # the next LRC row came 30 s later
    window = coarse_align([line], [], [(10.0, 12.0)], 60.0)[0]
    assert window.source == "hint"
    assert window.end_s == pytest.approx(10.0 + 3 * 1.5 + 2.0)


def test_locked_tokens_beat_imported_line_times_and_both_beat_the_transcript() -> None:
    lines = [
        lyric_line("L1", LINES[0], hint=(30.0, 34.0)),
        lyric_line("L2", LINES[1], locked={0: (20.0, 20.4)}),
    ]
    windows = coarse_align(lines, [], [(10.0, 14.0), (20.0, 24.0)], 40.0)
    # The hint says line 1 starts after the locked start of line 2: the lock is kept and
    # line 1 is laid out in front of it instead.
    assert windows[1].source == "anchor"
    assert windows[0].source != "hint"
    assert windows[0].end_s <= 20.0

    lines = [
        lyric_line("L1", LINES[0], hint=(30.0, 34.0)),
        lyric_line("L2", LINES[1]),
    ]
    words = sung_words(LINES[1], 12.0)  # heard before the file's time for line 1
    windows = coarse_align(lines, words, [(12.0, 16.0), (30.0, 34.0)], 40.0)
    assert windows[0].source == "hint"
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


def test_a_detached_first_word_moves_to_where_the_voice_comes_in() -> None:
    regions = [(5.0, 8.0), (11.0, 16.0)]
    words = [
        AsrWord("線", 7.2, 7.5),  # inside a region: untouched
        AsrWord("夜", 8.5, 9.0),  # alone in the pause: belongs to the next region
        AsrWord("空", 11.3, 11.6),
        AsrWord("遠", 30.0, 30.2),  # nothing follows: untouched
    ]
    cleaned = clean_words(words, regions)
    assert cleaned[0] == words[0]
    assert (cleaned[1].start_s, cleaned[1].end_s) == (11.0, 11.5)
    assert cleaned[2] == words[2]
    assert cleaned[3] == words[3]
    assert clean_words(words, []) == words


def test_a_first_word_stretched_back_over_the_pause_keeps_only_its_end() -> None:
    # What a recogniser really returned: 鐘 "starts" 2.6 s before it is sung.
    words = [
        AsrWord("氣", 10.18, 10.70),
        AsrWord("鐘", 11.62, 14.22),
        AsrWord("聲", 14.22, 14.70),
        AsrWord("響", 14.70, 15.44),
    ]
    # With a region that starts where the line starts, the word starts with the region …
    with_regions = clean_words(words, [(6.7, 11.5), (14.0, 20.0)])
    assert (with_regions[1].start_s, with_regions[1].end_s) == pytest.approx((14.0, 14.22))
    # … and without usable regions the start is derived from the end.
    without = clean_words(words, [])
    assert (without[1].start_s, without[1].end_s) == pytest.approx((13.62, 14.22))
    assert without[0] == words[0] and without[2:] == words[2:]
    # A two-character word may be twice as long before it counts as stretched.
    pair = clean_words([AsrWord("慢慢", 20.0, 21.1)], [])
    assert pair[0].start_s == pytest.approx(20.0)


def test_a_word_stretched_across_a_pause_starts_where_the_voice_comes_back() -> None:
    # The recogniser glued 我們 to the end of the previous line's last word and stretched
    # it across a 2.6 s pause; the voice comes back at 23.2 s.
    regions = [(17.4, 20.5), (23.2, 26.2)]
    words = [
        AsrWord("so", 18.4, 18.9),
        AsrWord("soft", 18.9, 20.56),
        AsrWord("我們", 20.56, 23.7),
        AsrWord("唱", 23.7, 25.0),
    ]
    cleaned = clean_words(words, regions)
    assert cleaned[:2] == words[:2] and cleaned[3] == words[3]
    assert (cleaned[2].start_s, cleaned[2].end_s) == (23.2, 23.7)
    # A word that merely pokes out of a region by a few tenths of a second is left alone.
    edge = [AsrWord("泥", 8.50, 8.90), AsrWord("土", 8.90, 9.44)]
    assert clean_words(edge, [(9.3, 11.5)]) == edge


def test_consistently_timed_words_are_trusted_over_the_activity_detector() -> None:
    # The detector missed the quiet first half of the line (region starts at 9.3 s), but six
    # words in a row with ordinary durations are not a coincidence: they stay where they are.
    words = [
        AsrWord("雨", 0.0, 0.0, 0.01),
        AsrWord("後", 0.0, 7.08, 0.11),
        AsrWord("的", 7.08, 7.42),
        AsrWord("空", 7.42, 7.80),
        AsrWord("氣", 7.80, 8.10),
        AsrWord("有", 8.10, 8.50),
        AsrWord("泥", 8.50, 8.90),
        AsrWord("土", 8.90, 9.44),
        AsrWord("的", 9.44, 9.88),
    ]
    cleaned = clean_words(words, [(9.3, 11.5)])
    assert [word.start_s for word in cleaned[2:]] == [word.start_s for word in words[2:]]
    # The stretched 後 keeps its end; the durationless 雨 leans on it.
    assert cleaned[1].start_s == pytest.approx(6.48)
    assert cleaned[0].start_s == pytest.approx(6.48)


def test_hallucinated_words_collapsed_onto_one_instant_are_dropped() -> None:
    real_before = [AsrWord("散", 53.04, 53.54), AsrWord("去", 53.54, 54.38)]
    invented = [AsrWord(text, 54.38, 54.38) for text in "天亮之前不要說再見雨停了"]
    real_after = [AsrWord("天", 55.6, 57.6), AsrWord("亮", 57.6, 58.2)]
    words = [*real_before, *invented, *real_after]
    assert drop_collapsed_words(words) == [*real_before, *real_after]
    # One or two durationless words are not a run; they are kept (and re-timed by clean_words).
    pair = [AsrWord("啊", 3.0, 3.0), AsrWord("喔", 3.0, 3.0), AsrWord("好", 3.4, 3.8)]
    assert drop_collapsed_words(pair) == pair
    assert [word.start_s for word in clean_words(pair, [])] == [3.4, 3.4, 3.4]
    assert drop_collapsed_words([]) == []


def test_a_line_is_not_anchored_to_a_hallucinated_copy_of_the_lyrics() -> None:
    lines = [lyric_line("L1", LINES[0]), lyric_line("L2", LINES[1])]
    invented = [AsrWord(token.core, 16.0, 16.0) for token in sung_tokens(LINES[1])]
    words = [*sung_words(LINES[0], 10.0), *invented, *sung_words(LINES[1], 20.0)]
    windows = coarse_align(lines, words, [(10.0, 14.5), (20.0, 24.0)], 30.0)
    assert windows[1].source == "asr"
    assert windows[1].start_s == pytest.approx(20.0, abs=0.2)
    assert windows[1].end_s - windows[1].start_s > 2.0


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
