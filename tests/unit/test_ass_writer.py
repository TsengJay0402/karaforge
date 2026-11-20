from __future__ import annotations

import re

import pytest

from conftest import GoldenChecker
from karaforge.ass.writer import (
    ass_time,
    ceil_cs,
    circle_path,
    escape_text,
    floor_cs,
    render_ass,
)
from karaforge.layout.engine import build_plan
from karaforge.layout.plan import RenderPlan
from karaforge.layout.theme import load_theme
from karaforge.project import Project
from support import song_project, timed_line


def demo_project(theme: str = "classic-ktv") -> Project:
    project = song_project(
        [
            timed_line("L001", "夜空裡的星星", 10_000, singer="m"),
            timed_line("L002", "慢慢 so bright", 13_000, singer="f"),
            timed_line("L003", "我們一起唱", 30_000, singer="all"),
        ],
        resolution=(1280, 720),
        theme=theme,
    )
    project.meta.lyricist = "詞人"
    return project


def dialogues(script: str, name: str | None = None) -> list[str]:
    rows = [line for line in script.splitlines() if line.startswith("Dialogue:")]
    return [row for row in rows if name is None or row.split(",")[4] == name]


def test_ass_time_and_rounding_helpers() -> None:
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(15_239) == "0:00:15.23"
    assert ass_time(3_723_450) == "1:02:03.45"
    assert ass_time(-5) == "0:00:00.00"
    assert (floor_cs(1239), ceil_cs(1231), ceil_cs(1230), floor_cs(-4)) == (1230, 1240, 1230, 0)


def test_text_is_escaped() -> None:
    assert escape_text("a{b}c") == r"a\{b\}c"
    assert escape_text("back\\slash") == "back＼slash"
    assert escape_text("two\nlines\r") == "two lines"


def test_circle_path_is_a_closed_curve_in_eighth_pixels() -> None:
    path = circle_path(10.0)
    assert path.startswith("m 80 0 b ")
    assert path.count(" b ") == 4
    assert path.endswith("80 0")
    numbers = [int(value) for value in re.findall(r"-?\d+", path)]
    assert min(numbers) == 0 and max(numbers) == 160


def test_header_declares_resolution_styles_and_fonts() -> None:
    script = render_ass(build_plan(demo_project()), title="測試歌曲")
    assert "PlayResX: 1280\n" in script
    assert "PlayResY: 720\n" in script
    assert "WrapStyle: 2\n" in script
    assert "ScaledBorderAndShadow: yes\n" in script
    assert "Title: 測試歌曲\n" in script
    styles = [
        line.split(",")[0].removeprefix("Style: ")
        for line in script.splitlines()
        if line.startswith("Style:")
    ]
    assert styles[:2] == ["KF-Unsung", "KF-Ruby-Unsung"]
    for slot in ("male", "female", "duet"):
        assert f"KF-Sung-{slot}" in styles
    assert {"KF-Card-Title", "KF-Card-Info", "KF-Dot"} <= set(styles)
    unsung = next(line for line in script.splitlines() if line.startswith("Style: KF-Unsung,"))
    fields = unsung.split(",")
    # Font, size (em 56 px at 720p → ASS size 62.72), white fill, near-black outline, top-left.
    assert fields[1] == "GenSenRounded2 TW B"
    assert float(fields[2]) == pytest.approx(62.72)
    assert fields[3] == "&H00FFFFFF"
    assert fields[5] == "&H00101010"
    assert fields[18] == "7"
    sung = next(line for line in script.splitlines() if line.startswith("Style: KF-Sung-male,"))
    assert sung.split(",")[3] == "&H00FF7B2F"  # #2F7BFF as BGR
    assert sung.split(",")[5] == "&H00FFFFFF"


def test_each_line_is_drawn_twice_with_complementary_clips() -> None:
    plan = build_plan(demo_project())
    script = render_ass(plan)
    rows = dialogues(script, "L001")
    assert len(rows) == 2
    unsung, sung = rows
    assert unsung.startswith("Dialogue: 0,0:00:06.50,") and ",KF-Unsung,L001," in unsung
    assert sung.startswith("Dialogue: 1,0:00:06.50,") and ",KF-Sung-male,L001," in sung
    line = plan.lines[0]
    assert f"\\an7\\pos({line.x:g},{line.y:g})" in sung
    assert sung.endswith("}夜空裡的星星")
    # Same geometry and timing in both layers; only clip vs inverse clip differs.
    assert unsung.split("{", 1)[1].replace("\\iclip(", "\\clip(") == sung.split("{", 1)[1]
    assert "\\k" not in sung


def test_fill_waits_then_jumps_to_the_line_and_sweeps_token_by_token() -> None:
    plan = build_plan(demo_project())
    line = plan.lines[0]
    sung = dialogues(render_ass(plan), "L001")[1]
    left, top, bottom = (
        int(line.clip_left // 1),
        int(line.clip_top // 1),
        -int(-line.clip_bottom // 1),
    )
    assert f"\\clip({left},{top},{left},{bottom})" in sung  # nothing sung at first
    transforms = re.findall(r"\\t\((\d+),(\d+),\\clip\((\d+),(\d+),(\d+),(\d+)\)\)", sung)
    # The event starts at 6500 ms; the first token is sung from 10 000 ms (relative 3500).
    first = transforms[0]
    assert (first[0], first[1]) == ("3500", "3500")  # a jump, not a slow creep during the wait
    assert int(first[4]) == round(line.tokens[0].x0 - plan.style.outline)
    spans = [(int(begin), int(end)) for begin, end, *_ in transforms[1:]]
    assert spans == [(3500 + 400 * index, 3900 + 400 * index) for index in range(6)]
    rights = [int(item[4]) for item in transforms]
    assert rights == sorted(rights)
    assert rights[1:6] == [round(token.x1) for token in line.tokens[:5]]
    assert all((int(t[2]), int(t[3]), int(t[5])) == (left, top, bottom) for t in transforms)


def test_karaoke_comment_carries_k_timing_for_other_tools() -> None:
    script = render_ass(build_plan(demo_project()))
    comments = [line for line in script.splitlines() if line.startswith("Comment:")]
    assert len(comments) == 3
    assert comments[0] == (
        "Comment: 0,0:00:10.00,0:00:12.40,KF-Unsung,m,0,0,0,karaoke,"
        "{\\k40}夜{\\k40}空{\\k40}裡{\\k40}的{\\k40}星{\\k40}星"
    )
    assert comments[1].endswith("karaoke,{\\k40}慢{\\k40}慢 {\\k40}so {\\k40}bright")


def test_gap_between_tokens_becomes_an_empty_k_tag() -> None:
    project = song_project([timed_line("L001", "一二", 10_000, 300, gap_ms=500)])
    comment = next(
        line for line in render_ass(build_plan(project)).splitlines() if line.startswith("Comment:")
    )
    assert comment.endswith("karaoke,{\\k30}一{\\k50}{\\k30}二")


def test_countdown_and_title_card_events() -> None:
    plan = build_plan(demo_project())
    script = render_ass(plan)
    dots = [row for row in dialogues(script) if ",KF-Dot," in row]
    assert len(dots) == 6  # three before L001, three before L003
    assert all("\\p4}m " in row and row.endswith("{\\p0}") for row in dots)
    ends = [row.split(",")[2] for row in dots[:3]]
    assert ends == ["0:00:07.00", "0:00:08.00", "0:00:09.00"]
    card = dialogues(script, "card")
    assert [row.split(",")[3] for row in card] == ["KF-Card-Title", "KF-Card-Info", "KF-Card-Info"]
    assert card[0].endswith("}測試歌曲")
    assert all(row.startswith("Dialogue: 3,0:00:00.30,0:00:06.30,") for row in card)


def test_dual_duet_mode_splits_the_sung_layer_into_two_halves() -> None:
    plan = build_plan(demo_project("pop-round"))
    assert plan.style.duet_mode == "dual"
    rows = dialogues(render_ass(plan), "L003")
    assert [row.split(",")[3] for row in rows] == ["KF-Unsung", "KF-Sung-male", "KF-Sung-female"]
    line = plan.lines[2]
    top = re.search(r"\\clip\((\d+),(\d+),(\d+),(\d+)\)", rows[1])
    bottom = re.search(r"\\clip\((\d+),(\d+),(\d+),(\d+)\)", rows[2])
    assert top is not None and bottom is not None
    middle = round((line.clip_top + line.clip_bottom) / 2)
    assert abs(int(top.group(4)) - middle) <= 1
    assert abs(int(bottom.group(2)) - middle) <= 1
    assert int(top.group(2)) < int(bottom.group(2))
    # A single-singer line in the same theme still has one sung layer.
    assert len(dialogues(render_ass(plan), "L001")) == 2


def test_ruby_gets_its_own_pair_of_events() -> None:
    project = song_project([timed_line("L001", "重{ㄔㄨㄥˊ}複", 10_000)], theme="zhuyin-learner")
    plan = build_plan(project)
    rows = dialogues(render_ass(plan), "L001")
    assert [row.split(",")[3] for row in rows] == [
        "KF-Unsung",
        "KF-Sung-male",
        "KF-Ruby-Unsung",
        "KF-Ruby-Sung-male",
    ]
    ruby = plan.lines[0].rubies[0]
    assert rows[2].endswith("}ㄔㄨㄥˊ")
    assert f"\\pos({ruby.x:g},{ruby.y:g})" in rows[3]
    assert "\\t(3500,3500,\\clip(" in rows[3]


def test_font_switches_are_written_inline_and_reset() -> None:
    project = song_project([timed_line("L001", "火东火", 10_000)], theme="pop-round")
    row = dialogues(render_ass(build_plan(project)), "L001")[1]
    text = row.split("}", 1)[1]
    assert re.fullmatch(
        r"火\{\\fnNoto Sans TC\\fs[\d.]+\}东\{\\fnjf-openhuninn-2\.1\\fs[\d.]+\}火", text
    )


def test_special_characters_in_lyrics_cannot_break_the_script() -> None:
    # In the lyrics syntax ``\{`` is a literal brace (a bare ``{…}`` would be a reading).
    project = song_project([timed_line("L001", r"a\{b\} c\d", 10_000)])
    row = dialogues(render_ass(build_plan(project)), "L001")[1]
    assert row.endswith("}a\\{b\\} c＼d")


def test_every_event_time_is_on_the_centisecond_grid_and_ordered() -> None:
    script = render_ass(build_plan(demo_project("zhuyin-learner")))
    for row in dialogues(script):
        start, end = row.split(",")[1:3]
        assert re.fullmatch(r"\d:\d\d:\d\d\.\d\d", start) and re.fullmatch(
            r"\d:\d\d:\d\d\.\d\d", end
        )
        assert start < end


def test_plan_without_lines_still_gives_a_valid_script() -> None:
    plan = build_plan(song_project([]))
    script = render_ass(plan)
    assert "[Events]" in script and dialogues(script) == []
    assert RenderPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize("theme", ["classic-ktv", "pop-round", "clean-center", "zhuyin-learner"])
def test_golden_scripts(theme: str, golden: GoldenChecker) -> None:
    project = demo_project(theme)
    project.lines[0].tokens[1] = (
        project.lines[0].tokens[1].model_copy(update={"ruby": "ㄎㄨㄥ", "ruby_source": "auto"})
    )
    plan = build_plan(project, load_theme(theme))
    golden.check(f"ass/{theme}.plan.json", plan.model_dump_json(indent=1) + "\n")
    script = render_ass(plan, title=project.meta.title)
    version_line = next(line for line in script.splitlines() if line.startswith("; Generated by"))
    golden.check(f"ass/{theme}.ass", script.replace(version_line, "; Generated by KaraForge"))
