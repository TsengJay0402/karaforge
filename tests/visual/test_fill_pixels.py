r"""Visual regression: render frames and check the colours of sung and unsung pixels.

The tests use a palette in which every role has an unmistakable colour, draw the subtitles
with ffmpeg + libass exactly as an export does, and verify at several moments that

* the *body* of the text is in the sung colour left of the fill position and in the unsung
  colour right of it,
* the *outline* changes colour at the same position (this is what plain ``\k`` karaoke tags
  cannot do), and
* the fill position is where the timeline says it should be.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from karaforge.ass import render_ass
from karaforge.audio.io import write_wav
from karaforge.io.exporters.video import VideoOptions, export_mp4
from karaforge.layout.engine import build_plan
from karaforge.layout.plan import PlanLine, RenderPlan
from karaforge.layout.theme import Theme, load_theme
from karaforge.project import Line, Project, ProjectStore, Token
from support import (
    Frame,
    color_mask,
    fill_position,
    grab_frames,
    render_frames,
    song_project,
    timed_line,
)

pytestmark = [pytest.mark.visual, pytest.mark.ffmpeg]

Mask = npt.NDArray[np.bool_]

BACKGROUND = "#404040"
UNSUNG_FILL, UNSUNG_OUTLINE = "#FFFFFF", "#FF0000"
SUNG_FILL, SUNG_OUTLINE = "#0000FF", "#FFFF00"
FEMALE_FILL = "#00FF00"
FPS = 50.0
SIZE = (960, 540)
BLOCKS = 8
# The line is sung from 2.0 s to 6.0 s (0.5 s per block) and leaves the screen at 6.7 s.
TIMES = [1.0, 2.0, 2.26, 3.0, 3.74, 4.5, 5.98, 6.4]


def palette_theme(**overrides: object) -> Theme:
    """classic-ktv with test colours, a thick outline, no shadow, countdown or title card."""
    values: dict[str, object] = {
        "colors.unsung.fill": UNSUNG_FILL,
        "colors.unsung.outline": UNSUNG_OUTLINE,
        "colors.slots.male.fill": SUNG_FILL,
        "colors.slots.male.outline": SUNG_OUTLINE,
        "colors.slots.female.fill": FEMALE_FILL,
        "colors.slots.female.outline": SUNG_OUTLINE,
        "colors.shadow": "#00000000",
        "text.shadow": 0,
        "text.outline": 16,
        "font.letter_spacing": 0,
        "layout.fade_ms": 0,
        "countdown.enabled": False,
        "title_card.enabled": False,
    }
    values.update(overrides)
    return load_theme("classic-ktv").with_overrides(values)


def block_project(singer: str = "m") -> Project:
    """One line of eight full-block characters: a solid bar that is sung from 2.0 s to 6.0 s.

    The tokens are built by hand because the tokenizer (rightly) treats block characters as
    punctuation, not as eight separate units.
    """
    tokens = [
        Token(text="█", start_ms=2_000 + 500 * index, end_ms=2_500 + 500 * index)
        for index in range(BLOCKS)
    ]
    return song_project(
        [Line(id="L001", singer=singer, tokens=tokens)], resolution=SIZE, duration_ms=8_000
    )


def band(frame: Frame, top: float, bottom: float) -> Frame:
    """Rows ``top`` … ``bottom`` of a frame."""
    return frame[round(top) : round(bottom)]


def inner(mask: Mask, line: PlanLine) -> Mask:
    """The part of a row band that lies inside the line's glyph bodies.

    Where two glyphs meet, anti-aliasing lets a little of the outline underneath show
    through, so tests ask for "almost all" of these pixels rather than every single one.
    """
    return mask[:, round(line.x) + 3 : round(line.x + line.width) - 3]


def boundary(mask_left: Mask, mask_right: Mask) -> tuple[int, int]:
    """Rightmost column containing ``mask_left`` pixels and leftmost containing ``mask_right``.

    Returns ``-1`` / the frame width when a mask is empty.
    """
    left_columns = np.flatnonzero(mask_left.any(axis=0))
    right_columns = np.flatnonzero(mask_right.any(axis=0))
    rightmost = int(left_columns[-1]) if left_columns.size else -1
    leftmost = int(right_columns[0]) if right_columns.size else int(mask_right.shape[1])
    return rightmost, leftmost


def body_band(line: PlanLine) -> tuple[float, float]:
    """Rows well inside the bodies of a full-block line."""
    em = line.width / BLOCKS
    return line.baseline - 0.6 * em, line.baseline - 0.2 * em


def outline_band(plan: RenderPlan, line: PlanLine) -> tuple[float, float]:
    """Rows above the full blocks that contain nothing but their outline."""
    em = line.width / BLOCKS
    top_of_block = line.baseline - 0.88 * em
    return top_of_block - plan.style.outline + 2, top_of_block - 2


@pytest.fixture(scope="module")
def block_frames(repo_root: Path) -> tuple[RenderPlan, list[Frame]]:
    work = repo_root / ".pytest_tmp" / "visual_blocks"
    work.mkdir(parents=True, exist_ok=True)
    plan = build_plan(block_project(), palette_theme())
    frames = render_frames(render_ass(plan), plan, TIMES, work, fps=FPS, background=BACKGROUND)
    return plan, frames


def test_nothing_is_sung_before_the_line_starts(
    block_frames: tuple[RenderPlan, list[Frame]],
) -> None:
    plan, frames = block_frames
    line = plan.lines[0]
    frame = frames[0]
    body = band(frame, *body_band(line))
    assert not color_mask(frame, SUNG_FILL).any()
    assert not color_mask(frame, SUNG_OUTLINE).any()
    assert inner(color_mask(body, UNSUNG_FILL), line).mean() > 0.97
    assert color_mask(frame, UNSUNG_OUTLINE).sum() > 500


def test_everything_is_sung_after_the_line_ends(
    block_frames: tuple[RenderPlan, list[Frame]],
) -> None:
    plan, frames = block_frames
    line = plan.lines[0]
    frame = frames[-1]
    body = band(frame, *body_band(line))
    assert not color_mask(frame, UNSUNG_FILL).any()
    assert not color_mask(frame, UNSUNG_OUTLINE).any()
    assert inner(color_mask(body, SUNG_FILL), line).mean() > 0.97
    assert color_mask(frame, SUNG_OUTLINE).sum() > 500


@pytest.mark.parametrize("index", range(1, len(TIMES) - 1))
def test_body_and_outline_change_colour_at_the_fill_position(
    block_frames: tuple[RenderPlan, list[Frame]], index: int
) -> None:
    plan, frames = block_frames
    line = plan.lines[0]
    frame = frames[index]
    outline = plan.style.outline
    expected = fill_position(line, TIMES[index] * 1000)
    body_left, body_right = line.x, line.x + line.width

    body = band(frame, *body_band(line))
    sung_edge, unsung_edge = boundary(color_mask(body, SUNG_FILL), color_mask(body, UNSUNG_FILL))
    if expected > body_left + 2:
        assert sung_edge == pytest.approx(min(expected, body_right) - 1, abs=2.5)
    else:
        assert sung_edge == -1
    if expected < body_right - 2:
        assert unsung_edge == pytest.approx(max(expected, body_left), abs=2.5)

    rim = band(frame, *outline_band(plan, line))
    assert rim.shape[0] >= 3
    assert not color_mask(rim, SUNG_FILL).any()
    assert not color_mask(rim, UNSUNG_FILL).any()
    sung_rim, unsung_rim = boundary(color_mask(rim, SUNG_OUTLINE), color_mask(rim, UNSUNG_OUTLINE))
    if expected > body_left - outline + 2:
        assert sung_rim == pytest.approx(min(expected, body_right + outline) - 1, abs=2.5)
    else:
        assert sung_rim == -1
    if expected < body_right + outline - 2:
        assert unsung_rim == pytest.approx(max(expected, body_left - outline), abs=2.5)
    # Body and outline switch at the same place.
    if body_left + 2 < expected < body_right - 2:
        assert abs(sung_edge - sung_rim) <= 2


def test_fill_moves_linearly_within_a_token(block_frames: tuple[RenderPlan, list[Frame]]) -> None:
    plan, frames = block_frames
    line = plan.lines[0]
    # 2.26 s is 52 % through the first token; 3.74 s is 48 % through the fourth.
    for time_s, token_index, share in ((2.26, 0, 0.52), (3.74, 3, 0.48)):
        body = band(frames[TIMES.index(time_s)], *body_band(line))
        sung_edge, _ = boundary(color_mask(body, SUNG_FILL), color_mask(body, UNSUNG_FILL))
        token = line.tokens[token_index]
        left = token.x0 - plan.style.outline if token_index == 0 else token.x0
        assert sung_edge == pytest.approx(left + share * (token.x1 - left), abs=3.0)


def test_real_glyphs_show_only_their_side_colours(work_dir: Path) -> None:
    project = song_project(
        [timed_line("L001", "夜空裡的星星慢慢亮", 2_000, 400)], resolution=SIZE, duration_ms=8_000
    )
    plan = build_plan(project, palette_theme())
    line = plan.lines[0]
    time_s = 3.8  # in the middle of the fifth character
    (frame,) = render_frames(
        render_ass(plan), plan, [time_s], work_dir, fps=FPS, background=BACKGROUND
    )
    split = round(fill_position(line, time_s * 1000))
    region = frame[round(line.clip_top) : round(line.clip_bottom)]
    left, right = region[:, : split - 2], region[:, split + 2 :]
    assert color_mask(left, SUNG_FILL).sum() > 1500
    assert color_mask(left, SUNG_OUTLINE).sum() > 1500
    assert color_mask(left, UNSUNG_FILL).sum() == 0
    assert color_mask(left, UNSUNG_OUTLINE).sum() == 0
    assert color_mask(right, UNSUNG_FILL).sum() > 1500
    assert color_mask(right, UNSUNG_OUTLINE).sum() > 1500
    assert color_mask(right, SUNG_FILL).sum() == 0
    assert color_mask(right, SUNG_OUTLINE).sum() == 0


@pytest.mark.parametrize("theme_name", ["classic-ktv", "pop-round", "clean-center"])
def test_measured_width_matches_what_libass_draws(work_dir: Path, theme_name: str) -> None:
    """The layout's glyph positions are the renderer's: check the ink extent of mixed text."""
    theme = load_theme(theme_name).with_overrides(
        {
            "colors.unsung.fill": UNSUNG_FILL,
            "colors.unsung.outline": UNSUNG_FILL,
            "colors.shadow": "#00000000",
            "text.shadow": 0,
            "text.outline": 0,
            "countdown.enabled": False,
            "title_card.enabled": False,
            "layout.fade_ms": 0,
        }
    )
    # Kerned Latin pairs and CJK between two full blocks: the blocks mark the line's ends.
    tokens = [
        Token(text=text, start_ms=2_000 + 300 * index, end_ms=2_300 + 300 * index)
        for index, text in enumerate(["█", "夜", "空 ", "Wave ", "AV ", "To ", "星", "█"])
    ]
    project = song_project([Line(id="L001", tokens=tokens)], resolution=SIZE, duration_ms=8_000)
    plan = build_plan(project, theme)
    line = plan.lines[0]
    (frame,) = render_frames(
        render_ass(plan), plan, [1.0], work_dir, fps=FPS, background=BACKGROUND
    )
    ink = color_mask(frame, UNSUNG_FILL)
    columns = np.flatnonzero(ink.any(axis=0))
    rows = np.flatnonzero(ink.any(axis=1))
    assert columns[0] == pytest.approx(line.x, abs=1.5)
    assert columns[-1] + 1 == pytest.approx(line.x + line.width, abs=1.5)
    # The last block starts where the layout says the last token starts.
    block_width = line.tokens[-1].x1 - line.tokens[-1].x0
    last_block = ink[round(line.baseline - 0.5 * block_width)]
    gap = np.flatnonzero(~last_block[: columns[-1]])
    assert gap[-1] + 1 == pytest.approx(line.tokens[-1].x0, abs=2.0)
    assert rows[0] == pytest.approx(line.baseline - 0.88 * block_width, abs=2.5)


def test_dual_duet_uses_one_colour_per_half(work_dir: Path) -> None:
    theme = palette_theme(**{"colors.duet_mode": "dual"})
    plan = build_plan(block_project(singer="all"), theme)
    line = plan.lines[0]
    (frame,) = render_frames(
        render_ass(plan), plan, [6.4], work_dir, fps=FPS, background=BACKGROUND
    )
    middle = (line.clip_top + line.clip_bottom) / 2
    em = line.width / BLOCKS
    upper = band(frame, line.baseline - 0.8 * em, middle - 3)
    lower = band(frame, middle + 3, line.baseline + 0.05 * em)
    assert inner(color_mask(upper, SUNG_FILL), line).mean() > 0.97
    assert inner(color_mask(lower, FEMALE_FILL), line).mean() > 0.97
    assert not color_mask(upper, FEMALE_FILL).any()
    assert not color_mask(lower, SUNG_FILL).any()


def test_exported_video_shows_the_fill_at_the_right_place(work_dir: Path) -> None:
    """The same check on a real export: H.264 frames decoded from the MP4 file."""
    store = ProjectStore(work_dir / "blocks.kfproj")
    project = block_project()
    project.render.fps = FPS
    project.media.source = "media/source.wav"
    store.create(project, overwrite=True)
    tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(8 * 48000) / 48000)).astype(np.float32)
    write_wav(store.paths.media / "source.wav", np.stack([tone, tone], axis=1), 48000)

    plan = build_plan(project, palette_theme())
    output = work_dir / "blocks.mp4"
    export_mp4(
        project,
        store.paths,
        plan,
        render_ass(plan),
        output,
        VideoOptions(audio="original", background="color", color=BACKGROUND, dim_bottom=0.0),
    )
    times = [1.0, 3.0, 4.5, 6.4]
    frames = grab_frames(output, times, work_dir / "grab", fps=FPS)
    line = plan.lines[0]
    for time_s, frame in zip(times, frames, strict=True):
        body = band(frame, *body_band(line))
        expected = fill_position(line, time_s * 1000)
        sung = color_mask(body, SUNG_FILL, 70)
        unsung = color_mask(body, UNSUNG_FILL, 70)
        sung_edge, unsung_edge = boundary(sung, unsung)
        if time_s < 2.0:
            assert sung_edge == -1
            assert inner(unsung, line).mean() > 0.95
        elif time_s > 6.0:
            assert unsung_edge == body.shape[1]
            assert inner(sung, line).mean() > 0.95
        else:
            # Chroma subsampling blurs the edge by a few pixels.
            assert sung_edge == pytest.approx(expected - 1, abs=5)
            assert unsung_edge == pytest.approx(expected, abs=5)
