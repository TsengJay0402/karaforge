from __future__ import annotations

import pytest

from karaforge.layout.engine import build_plan, wrap
from karaforge.layout.plan import RenderPlan
from karaforge.layout.theme import load_theme
from karaforge.project import Line, Singer, Token
from support import song_project, timed_line

W, H = 1920, 1080
EM = 84.0  # classic-ktv font size at 1080p
SPACING = 2.0
MARGIN = 0.06 * W


def four_lines() -> list[Line]:
    return [
        timed_line("L001", "夜空裡的星星", 10_000),
        timed_line("L002", "慢慢亮起來", 13_000),
        timed_line("L003", "我站在路口", 16_000),
        timed_line("L004", "等一陣風", 19_000),
    ]


def test_width_comes_from_real_glyph_advances() -> None:
    plan = build_plan(song_project([timed_line("L001", "夜空裡的星", 10_000)]))
    line = plan.lines[0]
    # Five full-width ideographs plus letter spacing between (not after) them.
    assert line.width == pytest.approx(5 * EM + 4 * SPACING, abs=0.01)
    assert [round(token.x1 - token.x0, 2) for token in line.tokens] == [
        86.0,
        86.0,
        86.0,
        86.0,
        84.0,
    ]
    assert line.tokens[0].x0 == pytest.approx(line.x)
    assert line.tokens[-1].x1 == pytest.approx(line.x + line.width)
    assert plan.style.font_family == "GenSenRounded2 TW B"
    # ASS font size = em * (winAscent + winDescent) / unitsPerEm for this font.
    assert plan.style.font_ass_size == pytest.approx(EM * 1120 / 1000, abs=0.01)
    assert line.runs[0].ass_size == plan.style.font_ass_size


def test_latin_text_is_narrower_and_measured_per_word() -> None:
    plan = build_plan(song_project([timed_line("L001", "so happy 快樂", 10_000)]))
    line = plan.lines[0]
    assert [token.text for token in line.tokens] == ["so ", "happy ", "快", "樂"]
    assert line.width < 8 * EM
    widths = [token.x1 - token.x0 for token in line.tokens]
    assert widths[1] > widths[0] > 0
    assert widths[2] == pytest.approx(EM + SPACING, abs=0.01)


def test_everything_scales_with_the_output_height() -> None:
    lines = [timed_line("L001", "夜空裡的星", 10_000)]
    big = build_plan(song_project(lines)).lines[0]
    small = build_plan(song_project(lines, resolution=(1280, 720))).lines[0]
    ratio = 720 / 1080
    assert small.width == pytest.approx(big.width * ratio, abs=0.02)
    assert small.x == pytest.approx(big.x * ratio, abs=0.02)
    assert small.y == pytest.approx(big.y * ratio, abs=0.02)
    assert small.runs[0].ass_size == pytest.approx(big.runs[0].ass_size * ratio, abs=0.02)


def test_rows_alternate_left_and_right() -> None:
    plan = build_plan(song_project(four_lines()))
    assert [line.row for line in plan.lines] == [0, 1, 0, 1]
    top, bottom = plan.lines[0], plan.lines[1]
    assert top.x == pytest.approx(MARGIN)
    assert bottom.x + bottom.width == pytest.approx(W - MARGIN, abs=0.01)
    assert top.y < bottom.y
    # The ideographs are centred on the row's centre line (0.74 and 0.88 of the height).
    assert top.baseline - 0.38 * EM == pytest.approx(0.74 * H, abs=0.5)
    assert bottom.baseline - 0.38 * EM == pytest.approx(0.88 * H, abs=0.5)


def test_first_two_lines_appear_together_before_the_first_is_sung() -> None:
    plan = build_plan(song_project(four_lines()))
    first, second = plan.lines[0], plan.lines[1]
    assert first.appear_ms == second.appear_ms == 10_000 - 3500


def test_next_line_takes_the_freed_row_shortly_after_the_other_row_starts() -> None:
    plan = build_plan(song_project(four_lines()))
    first, second, third, fourth = plan.lines
    # L003 replaces L001 once L002 has started (13 000 + swap delay 350).
    assert third.appear_ms == 13_350
    assert first.disappear_ms == third.appear_ms
    assert fourth.appear_ms == 16_350
    assert second.disappear_ms == fourth.appear_ms
    # The last two lines leave together, after the lingering time.
    assert third.disappear_ms == fourth.disappear_ms == 19_000 + 4 * 400 + 700


def test_a_line_is_shown_at_least_the_lead_in_before_it_is_sung() -> None:
    lines = [
        timed_line("L001", "一二三", 10_000),
        timed_line("L002", "四五六七八九十", 11_300),  # ends at 14 100
        timed_line("L003", "一二", 12_600),  # sung while L002 is still going
    ]
    plan = build_plan(song_project(lines))
    third = plan.lines[2]
    # Preferred: 11 300 + 350 = 11 650; lead-in limit: 12 600 - 1500 = 11 100; but the row is
    # only free once L001 has been sung (11 200).
    assert third.appear_ms == 11_200
    assert plan.lines[0].disappear_ms == 11_200


def test_long_pause_starts_a_new_screen_with_a_countdown() -> None:
    lines = [
        timed_line("L001", "夜空裡的星星", 10_000),
        timed_line("L002", "慢慢亮起來", 13_000),
        timed_line("L003", "我站在路口", 30_000),
    ]
    plan = build_plan(song_project(lines))
    assert [line.row for line in plan.lines] == [0, 1, 0]
    first, second, third = plan.lines
    assert first.disappear_ms == second.disappear_ms == 15_000 + 700
    assert third.appear_ms == 30_000 - 3500
    assert [countdown.line_id for countdown in plan.countdowns] == ["L001", "L003"]
    dots = plan.countdowns[1].dots
    assert [dot.off_ms for dot in dots] == [27_000, 28_000, 29_000]
    assert dots[0].x < dots[1].x < dots[2].x
    assert all(dot.y + dot.radius < third.y for dot in dots)
    assert dots[0].x - dots[0].radius == pytest.approx(third.x, abs=0.01)
    assert plan.countdowns[1].appear_ms == third.appear_ms


def test_a_new_paragraph_starts_a_new_screen_after_a_shorter_pause() -> None:
    def plan_for(paragraph: int, pause_ms: int, **overrides: object) -> RenderPlan:
        first = timed_line("L001", "夜空裡的星星", 10_000)  # sung until 12.4 s
        second = timed_line("L002", "慢慢亮起來", 12_400 + pause_ms, paragraph=paragraph)
        theme = load_theme("classic-ktv").with_overrides(dict(overrides))
        return build_plan(song_project([first, second]), theme)

    # The same paragraph: 2.5 s is an ordinary breath, the second line waits in the lower row.
    same = plan_for(0, 2_500)
    assert [line.row for line in same.lines] == [0, 1]
    assert [countdown.line_id for countdown in same.countdowns] == ["L001"]

    # After a blank line in the lyrics the same pause clears the screen and counts in.
    new = plan_for(1, 2_500)
    first, second = new.lines
    assert [first.row, second.row] == [0, 0]
    assert second.appear_ms >= first.disappear_ms
    assert [countdown.line_id for countdown in new.countdowns] == ["L001", "L002"]
    dots = new.countdowns[1].dots
    assert dots and all(
        new.countdowns[1].appear_ms < dot.off_ms <= second.sing_start_ms for dot in dots
    )

    # A paragraph break without a real pause changes nothing, and the threshold is a setting.
    assert [line.row for line in plan_for(1, 1_200).lines] == [0, 1]
    assert [
        line.row for line in plan_for(1, 2_500, **{"layout.paragraph_gap_ms": 4_000}).lines
    ] == [
        0,
        1,
    ]
    assert [line.row for line in plan_for(1, 600, **{"layout.paragraph_gap_ms": 500}).lines] == [
        0,
        0,
    ]


def test_no_countdown_without_a_long_pause_or_when_disabled() -> None:
    plan = build_plan(song_project([timed_line("L001", "一二三", 2_000)]))
    assert plan.countdowns == []
    theme = load_theme("classic-ktv").with_overrides({"countdown.enabled": False})
    plan = build_plan(song_project([timed_line("L001", "一二三", 20_000)]), theme)
    assert plan.countdowns == []


@pytest.mark.parametrize(
    ("tempo", "interval"),
    [(None, 1000), (120.0, 500), (60.0, 1000), (200.0, 600), (40.0, 750), (500.0, 1000)],
)
def test_countdown_follows_the_beat(tempo: float | None, interval: int) -> None:
    project = song_project([timed_line("L001", "一二三", 20_000)])
    project.analysis.tempo_bpm = tempo
    dots = build_plan(project).countdowns[0].dots
    assert [20_000 - dot.off_ms for dot in dots] == [3 * interval, 2 * interval, interval]


def test_fill_sweeps_each_token_during_its_time() -> None:
    plan = build_plan(song_project([timed_line("L001", "夜空裡", 10_000, gap_ms=200)]))
    line = plan.lines[0]
    outline, shadow = plan.style.outline, plan.style.shadow
    keys = [(key.time_ms, key.x) for key in line.fill]
    t0, t1, t2 = line.tokens
    assert keys == [
        (10_000, pytest.approx(t0.x0 - outline)),
        (10_400, pytest.approx(t0.x1)),
        (10_600, pytest.approx(t1.x0)),  # nothing moves during the 200 ms gap
        (11_000, pytest.approx(t1.x1)),
        (11_200, pytest.approx(t2.x0)),
        (11_600, pytest.approx(t2.x1 + outline + shadow)),
    ]
    times = [key.time_ms for key in line.fill]
    positions = [key.x for key in line.fill]
    assert times == sorted(times)
    assert positions == sorted(positions)
    assert line.clip_left < line.x - outline
    assert line.clip_right > line.x + line.width + outline
    assert line.clip_top < line.y and line.clip_bottom > line.y + line.height


def test_long_line_is_wrapped_into_balanced_parts_with_their_own_times() -> None:
    text = "夜空裡的星星慢慢亮起來,我站在路口等一陣風吹過來"
    plan = build_plan(song_project([timed_line("L001", text, 10_000, 300)]))
    assert [line.id for line in plan.lines] == ["L001.1", "L001.2"]
    first, second = plan.lines
    assert first.source_line == second.source_line == "L001"
    assert (first.part, second.part) == (1, 2)
    assert first.text == "夜空裡的星星慢慢亮起來,"
    assert second.text == "我站在路口等一陣風吹過來"
    assert max(first.width, second.width) <= 0.86 * W
    assert [token.index for token in second.tokens] == list(range(11, 23))
    assert first.sing_start_ms == 10_000
    assert second.sing_start_ms == 10_000 + 11 * 300
    assert (first.row, second.row) == (0, 1)
    assert second.tokens[0].x0 == pytest.approx(second.x)


def test_wrapping_breaks_only_after_a_space_or_a_hyphen() -> None:
    text = "supercalifragilistic-expialidocious wonderful beautiful extraordinary magnificent days"
    plan = build_plan(song_project([timed_line("L001", text, 10_000)]))
    assert len(plan.lines) >= 2
    position = 0
    for line in plan.lines:
        assert line.width <= 0.86 * W
        position = text.index(line.text, position) + len(line.text)
        # Whatever follows the part in the original text is a space, or the part ended in "-".
        assert position == len(text) or text[position] == " " or line.text.endswith("-")
    assert "".join(line.text for line in plan.lines).replace(" ", "") == text.replace(" ", "")


def test_syllables_of_one_word_are_never_separated() -> None:
    # Syllable-level tokens (as imported from enhanced LRC) with no space between them.
    syllables = ["to", "ge", "ther ", "for", "e", "ver ", "and ", "e", "ver"]
    tokens = [
        Token(text=text, start_ms=10_000 + 300 * index, end_ms=10_300 + 300 * index)
        for index, text in enumerate(syllables)
    ]
    theme = load_theme("classic-ktv").with_overrides({"layout.max_width": 0.22})
    plan = build_plan(song_project([Line(id="L001", tokens=tokens)]), theme)
    assert [line.text for line in plan.lines] == ["together", "forever", "and ever"]
    assert [[token.index for token in line.tokens] for line in plan.lines] == [
        [0, 1, 2],
        [3, 4, 5],
        [6, 7, 8],
    ]


def test_cjk_text_prefers_to_break_after_punctuation() -> None:
    text = "一二三四五六七八九十一二,三四五六七八九十一二三四五六"
    plan = build_plan(song_project([timed_line("L001", text, 10_000, 200)]))
    assert [line.text for line in plan.lines] == [
        "一二三四五六七八九十一二,",
        "三四五六七八九十一二三四五六",
    ]


def test_wrap_leaves_short_and_unsplittable_lines_alone() -> None:
    plan = build_plan(song_project([timed_line("L001", "短短的一行", 10_000)]))
    assert [line.id for line in plan.lines] == ["L001"]
    assert plan.lines[0].part == 0
    assert wrap.__name__ == "wrap"


def test_ruby_is_centred_over_its_token_and_pushes_neighbours_apart() -> None:
    line = timed_line("L001", "重{ㄔㄨㄥˊ}複{ㄈㄨˋ}了", 10_000)
    with_ruby = build_plan(song_project([line], theme="zhuyin-learner")).lines[0]
    theme = load_theme("zhuyin-learner").with_overrides({"ruby.enabled": False})
    without = build_plan(song_project([line], theme="zhuyin-learner"), theme).lines[0]

    assert [ruby.text for ruby in with_ruby.rubies] == ["ㄔㄨㄥˊ", "ㄈㄨˋ"]
    assert without.rubies == []
    em = 76.0
    for ruby, token in zip(with_ruby.rubies, with_ruby.tokens, strict=False):
        assert ruby.x + ruby.width / 2 == pytest.approx(token.x0 + em / 2, abs=0.6)
        assert ruby.y + ruby.height <= with_ruby.baseline - 0.8 * em
        assert (ruby.start_ms, ruby.end_ms) == (token.start_ms, token.end_ms)
    first, second = with_ruby.rubies
    assert second.x - (first.x + first.width) >= 8.0 - 0.01
    # ㄔㄨㄥˊ is wider than one character: the gap between 重 and 複 had to grow.
    assert (
        with_ruby.tokens[1].x0 - with_ruby.tokens[0].x0
        > without.tokens[1].x0 - without.tokens[0].x0
    )
    assert with_ruby.width > without.width


def test_title_card_shows_title_and_credits_before_the_first_line() -> None:
    project = song_project([timed_line("L001", "一二三", 12_000)])
    project.meta.lyricist = "詞人"
    project.meta.composer = "曲人"
    card = build_plan(project).title_card
    assert card is not None
    assert (card.start_ms, card.end_ms) == (300, 6300)
    assert [(row.role, row.text) for row in card.lines] == [
        ("title", "測試歌曲"),
        ("info", "演唱 某歌手"),
        ("info", "作詞 詞人 作曲 曲人"),
    ]
    for row in card.lines:
        assert row.x + row.width / 2 == pytest.approx(W / 2, abs=0.01)
    assert card.lines[0].y < card.lines[1].y < card.lines[2].y
    assert card.lines[0].ass_size > card.lines[1].ass_size


def test_title_card_ends_before_an_early_first_line_or_is_dropped() -> None:
    early = song_project([timed_line("L001", "一二三", 3_000)])
    card = build_plan(early).title_card
    assert card is not None
    assert card.end_ms == 2_500
    too_early = song_project([timed_line("L001", "一二三", 1_500)])
    assert build_plan(too_early).title_card is None
    untitled = song_project([timed_line("L001", "一二三", 12_000)], title="")
    assert build_plan(untitled).title_card is None


def test_english_song_gets_english_credits() -> None:
    project = song_project([timed_line("L001", "hello world", 12_000)], title="Hello")
    project.meta.language = "en"
    project.meta.lyricist = "A"
    card = build_plan(project).title_card
    assert card is not None
    assert [row.text for row in card.lines] == ["Hello", "Vocals  某歌手", "Lyrics  A"]


def test_singer_slots_select_the_sung_colours() -> None:
    project = song_project(
        [
            timed_line("L001", "一二三", 10_000, singer="m"),
            timed_line("L002", "四五六", 12_000, singer="f"),
            timed_line("L003", "七八九", 14_000, singer="all"),
        ]
    )
    project.singers.append(Singer(id="guest", label="來賓", theme_slot="sparkle"))
    project.lines.append(timed_line("L004", "十", 16_000, singer="guest"))
    plan = build_plan(project)
    assert [line.slot for line in plan.lines] == ["male", "female", "duet", "sparkle"]
    assert plan.style.slots["male"] == ("#2F7BFF", "#FFFFFF")
    # An unknown slot is resolved to the duet colours so that the script stays valid.
    assert plan.style.slots["sparkle"] == plan.style.slots["duet"]


def test_characters_missing_from_the_font_use_the_fallback_explicitly() -> None:
    # jf open 粉圓 covers Traditional Chinese only; the Simplified 东 comes from Noto Sans TC.
    plan = build_plan(song_project([timed_line("L001", "火东东", 10_000)], theme="pop-round"))
    line = plan.lines[0]
    assert [(run.text, run.family) for run in line.runs] == [
        ("火", "jf-openhuninn-2.1"),
        ("东东", "Noto Sans TC"),
    ]
    assert {font.family for font in plan.fonts} == {"jf-openhuninn-2.1", "Noto Sans TC"}
    assert line.runs[0].ass_size != line.runs[1].ass_size  # same em, different ASS size
    # Both fonts draw the ideograph one em wide, so the tokens stay evenly spaced.
    assert line.tokens[1].x0 - line.tokens[0].x0 == pytest.approx(
        line.tokens[2].x0 - line.tokens[1].x0, abs=0.01
    )
    assert plan.missing_glyphs == []


def test_characters_no_font_can_draw_are_reported() -> None:
    plan = build_plan(song_project([timed_line("L001", "火🎤", 10_000)]))
    assert plan.missing_glyphs == ["🎤"]


def test_untimed_lines_are_left_out_and_untimed_tokens_take_no_time() -> None:
    partly = timed_line("L002", "四五六", 12_000)
    partly.tokens[1] = Token(text="五")
    project = song_project(
        [timed_line("L001", "一二三", 10_000), partly, Line(id="L003", tokens=[Token(text="七")])]
    )
    plan = build_plan(project)
    assert [line.id for line in plan.lines] == ["L001", "L002"]
    middle = plan.lines[1].tokens[1]
    assert (middle.start_ms, middle.end_ms) == (12_400, 12_400)


def test_plan_survives_a_json_round_trip() -> None:
    plan = build_plan(song_project(four_lines(), theme="zhuyin-learner"))
    assert RenderPlan.model_validate_json(plan.model_dump_json()) == plan


def test_every_builtin_theme_lays_out() -> None:
    for name in ("classic-ktv", "pop-round", "clean-center", "zhuyin-learner"):
        plan = build_plan(song_project(four_lines(), theme=name))
        assert len(plan.lines) == 4
        assert plan.style.theme == name
        for line in plan.lines:
            assert line.x >= 0 and line.x + line.width <= W
            assert line.y >= 0 and line.y + line.height <= H


def test_centred_rows_are_centred() -> None:
    plan = build_plan(song_project(four_lines(), theme="clean-center"))
    for line in plan.lines:
        assert line.x + line.width / 2 == pytest.approx(W / 2, abs=0.01)
