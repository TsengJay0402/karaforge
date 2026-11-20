"""The render plan: the layout engine's output and the ASS writer's input.

Everything in a plan is concrete — pixel coordinates in the output resolution, times in
milliseconds — and JSON-serialisable, which is what makes layout rules testable with golden
files.  Coordinates use the frame's top-left corner as origin, x to the right, y downwards.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

PLAN_VERSION = 1


class _Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextRun(_Plan):
    """A stretch of a line's text set in one font."""

    text: str
    family: str
    """Font family name to request from libass."""
    ass_size: float
    """ASS ``\\fs`` value that gives the intended em size in this font."""
    spacing: float = 0.0
    """Extra space (``\\fsp``) added after each glyph of the run, in pixels."""


class PlanToken(_Plan):
    """Where a token is drawn and when it is sung."""

    index: int
    """Index of the token in its source line."""
    text: str
    x0: float
    """Left edge of the token (absolute)."""
    x1: float
    """Right edge: where the fill is once the token has been sung."""
    start_ms: int
    end_ms: int


class PlanRuby(_Plan):
    """A reading shown above a token."""

    token_index: int
    text: str
    x: float
    y: float
    width: float
    height: float
    ass_size: float
    family: str
    start_ms: int
    end_ms: int


class FillKey(_Plan):
    """A keyframe of the fill: at ``time_ms`` everything left of ``x`` is sung."""

    time_ms: int
    x: float


class PlanLine(_Plan):
    """One line as displayed (a long lyric line may give several)."""

    id: str
    source_line: str
    """Id of the lyric line this display line comes from."""
    part: int = 0
    """0 for an unwrapped line, otherwise the 1-based part number."""
    singer: str
    slot: str
    row: int
    x: float
    y: float
    """Top-left corner of the text box (``\\an7\\pos``)."""
    width: float
    height: float
    baseline: float
    """y coordinate of the text baseline."""
    text: str
    runs: list[TextRun]
    tokens: list[PlanToken]
    rubies: list[PlanRuby] = Field(default_factory=list[PlanRuby])
    appear_ms: int
    disappear_ms: int
    sing_start_ms: int
    sing_end_ms: int
    fill: list[FillKey]
    clip_top: float
    clip_bottom: float
    """Vertical extent that the fill clips must cover (text, outline and shadow)."""
    clip_left: float
    clip_right: float


class PlanDot(_Plan):
    """One countdown dot."""

    x: float
    y: float
    """Centre of the dot."""
    radius: float
    off_ms: int
    """When the dot disappears."""


class PlanCountdown(_Plan):
    """Dots counting in a line."""

    line_id: str
    appear_ms: int
    dots: list[PlanDot]


class PlanCardLine(_Plan):
    """A line of text on the title card."""

    text: str
    role: str
    """``title`` or ``info``."""
    x: float
    y: float
    width: float
    family: str
    ass_size: float


class PlanTitleCard(_Plan):
    """Title and credits shown before the first line."""

    start_ms: int
    end_ms: int
    lines: list[PlanCardLine]


class PlanFont(_Plan):
    """A font file the plan needs."""

    family: str
    file: str
    """File name (the file lives in one of the font folders)."""


class PlanStyle(_Plan):
    """Resolved style values in output pixels (already scaled from the theme)."""

    theme: str
    font_family: str
    """Family of the theme's main font (the default of every style)."""
    font_ass_size: float
    """ASS font size of the lyrics in the main font."""
    ruby_ass_size: float
    letter_spacing: float
    """Extra space after every glyph of the lyrics (the style's ``Spacing``), in pixels."""
    outline: float
    shadow: float
    blur: float
    fade_ms: int
    unsung_fill: str
    unsung_outline: str
    shadow_color: str
    slots: dict[str, tuple[str, str]]
    """Sung ``(fill, outline)`` colours per slot."""
    duet_mode: str
    countdown_fill: str
    countdown_outline: str
    card_fill: str
    card_outline: str
    card_accent: str


class RenderPlan(_Plan):
    """Everything needed to draw the karaoke subtitles."""

    version: int = PLAN_VERSION
    width: int
    height: int
    duration_ms: int
    style: PlanStyle
    fonts: list[PlanFont]
    lines: list[PlanLine]
    countdowns: list[PlanCountdown] = Field(default_factory=list[PlanCountdown])
    title_card: PlanTitleCard | None = None
    missing_glyphs: list[str] = Field(default_factory=list[str])
    """Characters that neither the theme's font nor its fallback can draw."""
