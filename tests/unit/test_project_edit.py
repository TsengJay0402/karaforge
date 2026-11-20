from __future__ import annotations

from karaforge.project import Line, Token
from karaforge.project.edit import EDITED_CONFIDENCE, retokenize_line
from support import timed_line


def times(line: Line) -> list[tuple[str, int | None, int | None]]:
    return [(token.text, token.start_ms, token.end_ms) for token in line.tokens]


def test_unchanged_text_keeps_everything() -> None:
    line = timed_line("L001", "夜空裡的星星", 10_000, 400, singer="f", paragraph=2)
    line.tokens[2] = line.tokens[2].retimed(10_800, 11_200, locked=True, source="manual")
    line.time_hint = (9_000, 13_000)
    edited = retokenize_line(line, "夜空裡的星星")
    assert edited == line
    assert edited is not line


def test_corrected_character_keeps_its_time_but_not_its_reading() -> None:
    line = timed_line("L001", "夜空裏的星星", 10_000, 400)
    line.tokens[2] = line.tokens[2].model_copy(
        update={"ruby": "ㄌㄧˇ", "ruby_source": "auto", "locked": True}
    )
    edited = retokenize_line(line, "夜空裡的星星")
    assert times(edited) == [
        ("夜", 10_000, 10_400),
        ("空", 10_400, 10_800),
        ("裡", 10_800, 11_200),
        ("的", 11_200, 11_600),
        ("星", 11_600, 12_000),
        ("星", 12_000, 12_400),
    ]
    fixed = edited.tokens[2]
    assert fixed.ruby is None and fixed.locked is True
    assert edited.tokens[0].confidence == 0.9


def test_punctuation_and_spacing_changes_do_not_touch_the_timing() -> None:
    line = timed_line("L001", "hello world", 1_000, 500)
    edited = retokenize_line(line, "Hello, world!")
    assert times(edited) == [("Hello, ", 1_000, 1_500), ("world!", 1_500, 2_000)]


def test_deleted_tokens_disappear_and_the_rest_stays() -> None:
    line = timed_line("L001", "一二三四五", 0, 400)
    edited = retokenize_line(line, "一二五")
    assert times(edited) == [("一", 0, 400), ("二", 400, 800), ("五", 1_600, 2_000)]


def test_a_stretch_replaced_by_more_tokens_shares_its_time() -> None:
    line = timed_line("L001", "我愛你", 3_000, 600)
    line.tokens[1] = line.tokens[1].model_copy(update={"locked": True})
    edited = retokenize_line(line, "我喜歡你")
    assert times(edited) == [
        ("我", 3_000, 3_600),
        ("喜", 3_600, 3_900),
        ("歡", 3_900, 4_200),
        ("你", 4_200, 4_800),
    ]
    assert [token.confidence for token in edited.tokens[1:3]] == [EDITED_CONFIDENCE] * 2
    assert not any(token.locked for token in edited.tokens[1:3])


def test_inserted_tokens_use_the_pause_between_their_neighbours() -> None:
    line = timed_line("L001", "一二", 1_000, 400, gap_ms=600)  # 一 1000-1400, 二 2000-2400
    edited = retokenize_line(line, "一啊喔二")
    assert times(edited) == [
        ("一", 1_000, 1_400),
        ("啊", 1_400, 1_700),
        ("喔", 1_700, 2_000),
        ("二", 2_000, 2_400),
    ]


def test_inserted_tokens_without_room_stay_untimed() -> None:
    line = timed_line("L001", "一二", 1_000, 400)
    edited = retokenize_line(line, "一啊二")
    assert times(edited) == [("一", 1_000, 1_400), ("啊", None, None), ("二", 1_400, 1_800)]
    appended = retokenize_line(line, "一二三")
    assert times(appended)[-1] == ("三", None, None)


def test_explicit_reading_in_the_new_text_is_applied() -> None:
    line = timed_line("L001", "長大", 0, 500)
    edited = retokenize_line(line, "長{ㄓㄤˇ}大")
    assert (edited.tokens[0].ruby, edited.tokens[0].ruby_source) == ("ㄓㄤˇ", "manual")
    assert times(edited) == [("長", 0, 500), ("大", 500, 1_000)]


def test_untimed_lines_and_complete_rewrites() -> None:
    untimed = Line(id="L001", tokens=[Token(text="一"), Token(text="二")])
    assert times(retokenize_line(untimed, "三四五")) == [
        ("三", None, None),
        ("四", None, None),
        ("五", None, None),
    ]
    line = timed_line("L001", "一二三", 6_000, 300)
    rewritten = retokenize_line(line, "ABCD EF")
    assert times(rewritten) == [("ABCD ", 6_000, 6_450), ("EF", 6_450, 6_900)]
    assert retokenize_line(line, "   ").tokens == []
