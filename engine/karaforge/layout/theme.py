"""Themes: fonts, colours, positions and timing of the KTV rendering.

A theme is a YAML file (see ``docs/themes.md`` for every field).  All lengths are pixels at
:attr:`Theme.reference_height` and are scaled to the output resolution by the layout engine;
positions are fractions of the frame.  Built-in themes live in ``themes/``; themes saved from
the editor go to ``$KARAFORGE_HOME/themes``.  A project can override individual values with
dotted keys in ``style.overrides``, e.g. ``{"font.size": 96, "colors.slots.male.fill": "#00AAFF"}``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from karaforge import paths
from karaforge.errors import ThemeError

THEME_FORMAT_VERSION = 1
_COLOR = re.compile(r"^#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$")


def _check_color(value: str) -> str:
    if not _COLOR.match(value):
        raise ValueError("colour must be #RRGGBB or #RRGGBBAA")
    return value.upper()


Color = Annotated[str, AfterValidator(_check_color)]
"""``#RRGGBB`` or ``#RRGGBBAA`` (alpha ``FF`` = opaque)."""


def ass_color(color: str) -> str:
    """Convert ``#RRGGBB[AA]`` to the ASS style notation ``&HAABBGGRR`` (ASS alpha 00 = opaque)."""
    match = _COLOR.match(color)
    if match is None:
        raise ValueError(f"invalid colour: {color}")
    rgb = match.group(1)
    alpha = 255 - int(match.group(2) or "FF", 16)
    return f"&H{alpha:02X}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def ass_color_tag(color: str) -> str:
    """Convert ``#RRGGBB`` to the override-tag notation ``&HBBGGRR&``."""
    match = _COLOR.match(color)
    if match is None:
        raise ValueError(f"invalid colour: {color}")
    rgb = match.group(1)
    return f"&H{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&".upper()


def rgb_of(color: str) -> tuple[int, int, int]:
    """Red, green and blue components (0–255) of ``#RRGGBB[AA]``."""
    match = _COLOR.match(color)
    if match is None:
        raise ValueError(f"invalid colour: {color}")
    rgb = match.group(1)
    return int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FontSettings(_Section):
    """Typeface of the lyrics."""

    family: str = "GenSenRounded2 TW B"
    fallback: str = "Noto Sans TC"
    """Used for characters the main font lacks."""
    size: float = Field(default=84.0, gt=4)
    """Height of a Chinese character (the em) in pixels at the reference height."""
    letter_spacing: float = 0.0


class TextSettings(_Section):
    """Outline and shadow of the lyrics."""

    outline: float = Field(default=6.0, ge=0)
    shadow: float = Field(default=3.0, ge=0)
    blur: float = Field(default=0.0, ge=0)


class ColorPair(_Section):
    """Fill and outline colour of one state."""

    fill: Color = "#FFFFFF"
    outline: Color = "#000000"


class Colors(_Section):
    """Colours before and after a token is sung."""

    unsung: ColorPair = Field(default_factory=lambda: ColorPair(fill="#FFFFFF", outline="#101010"))
    shadow: Color = "#000000A0"
    slots: dict[str, ColorPair] = Field(
        default_factory=lambda: {
            "male": ColorPair(fill="#2F7BFF", outline="#FFFFFF"),
            "female": ColorPair(fill="#FF4F9A", outline="#FFFFFF"),
            "duet": ColorPair(fill="#35D05B", outline="#FFFFFF"),
        }
    )
    """Sung colours per theme slot (a singer's ``theme_slot`` selects one)."""
    duet_mode: Literal["third", "dual"] = "third"
    """``third``: duet lines use the ``duet`` slot.  ``dual``: upper half ``male``, lower half
    ``female``."""


class RowSettings(_Section):
    """One of the rows in which lines are shown."""

    y: float = Field(ge=0, le=1)
    """Vertical centre of the row as a fraction of the frame height."""
    align: Literal["left", "center", "right"] = "left"
    margin: float = Field(default=0.06, ge=0, le=0.45)
    """Distance from the frame edge the row is aligned to, as a fraction of the width."""


class LayoutSettings(_Section):
    """Placement and timing of the lines."""

    rows: list[RowSettings] = Field(
        default_factory=lambda: [
            RowSettings(y=0.74, align="left", margin=0.06),
            RowSettings(y=0.88, align="right", margin=0.06),
        ],
        min_length=1,
        max_length=4,
    )
    max_width: float = Field(default=0.86, gt=0.2, le=1.0)
    """Longest line as a fraction of the frame width; longer lines are wrapped."""
    lead_in_ms: int = Field(default=1500, ge=0)
    """A line is on screen at least this long before it is sung (when its row is free)."""
    first_lead_in_ms: int = Field(default=3500, ge=0)
    """Lead-in of the first lines after a long pause."""
    swap_delay_ms: int = Field(default=350, ge=0)
    """How long after the other row starts being sung a finished line is replaced."""
    linger_ms: int = Field(default=700, ge=0)
    """How long the last lines stay after the singing stops."""
    fade_ms: int = Field(default=150, ge=0)
    section_gap_ms: int = Field(default=4000, ge=500)
    """A pause at least this long clears the screen and restarts with the first row."""
    paragraph_gap_ms: int = Field(default=2000, ge=0)
    """Where the lyrics start a new paragraph (a blank line), a shorter pause is enough: the
    screen is cleared and the countdown shown when the pause is at least this long."""


class RubySettings(_Section):
    """Small readings (zhuyin / pinyin) above the characters."""

    enabled: bool = False
    scale: float = Field(default=0.4, gt=0.1, le=1.0)
    """Size relative to the lyrics."""
    gap: float = Field(default=2.0, ge=0)
    """Space between the reading and the character below it."""
    min_spacing: float = Field(default=6.0, ge=0)
    """Minimum space between neighbouring readings."""


class CountdownSettings(_Section):
    """Dots that count in a line after a long pause."""

    enabled: bool = True
    min_gap_ms: int = Field(default=4000, ge=1000)
    dots: int = Field(default=3, ge=1, le=6)
    interval_ms: int = Field(default=1000, ge=200)
    """Spacing of the dots when the song has no usable tempo."""
    use_beats: bool = True
    radius: float = Field(default=13.0, gt=1)
    spacing: float = Field(default=16.0, ge=0)
    offset: float = Field(default=18.0, ge=0)
    """Distance between the dots and the top of the line."""
    fill: Color = "#FFE14D"
    outline: Color = "#202020"


class TitleCardSettings(_Section):
    """The card with title and credits shown before the first line."""

    enabled: bool = True
    y: float = Field(default=0.4, ge=0, le=1)
    title_size: float = Field(default=110.0, gt=4)
    info_size: float = Field(default=52.0, gt=4)
    line_gap: float = Field(default=26.0, ge=0)
    max_duration_ms: int = Field(default=6000, ge=500)
    min_duration_ms: int = Field(default=1500, ge=0)
    fill: Color = "#FFFFFF"
    outline: Color = "#101010"
    accent: Color = "#FFE14D"


class BackgroundSettings(_Section):
    """Defaults for what is behind the lyrics when the project does not say."""

    color: Color = "#12141C"
    dim_bottom: float = Field(default=0.45, ge=0, le=1)
    """Darkness of the gradient under the lyrics (0 = none, 1 = black at the bottom edge)."""


class Theme(_Section):
    """A complete theme."""

    format: int = THEME_FORMAT_VERSION
    name: str
    title: str = ""
    description: str = ""
    reference_height: int = Field(default=1080, ge=100)
    font: FontSettings = Field(default_factory=FontSettings)
    text: TextSettings = Field(default_factory=TextSettings)
    colors: Colors = Field(default_factory=Colors)
    layout: LayoutSettings = Field(default_factory=LayoutSettings)
    ruby: RubySettings = Field(default_factory=RubySettings)
    countdown: CountdownSettings = Field(default_factory=CountdownSettings)
    title_card: TitleCardSettings = Field(default_factory=TitleCardSettings)
    background: BackgroundSettings = Field(default_factory=BackgroundSettings)

    def slot(self, name: str) -> ColorPair:
        """Sung colours of a slot; unknown slots fall back to ``duet`` and then to any slot."""
        if name in self.colors.slots:
            return self.colors.slots[name]
        if "duet" in self.colors.slots:
            return self.colors.slots["duet"]
        return next(iter(self.colors.slots.values()), ColorPair(fill="#FFD400", outline="#FFFFFF"))

    def with_overrides(self, overrides: dict[str, Any]) -> Theme:
        """Return a copy with dotted-key overrides applied.

        Raises:
            ThemeError: If a key does not exist or a value is invalid.
        """
        if not overrides:
            return self
        data = self.model_dump()
        for dotted, value in overrides.items():
            target: Any = data
            parts = dotted.split(".")
            for part in parts[:-1]:
                target = _descend(target, part, dotted)
            _assign(target, parts[-1], value, dotted)
        return _validate(data, f"overrides of {self.name}")


def _descend(target: Any, part: str, dotted: str) -> Any:
    if isinstance(target, list) and part.isdigit() and int(part) < len(target):  # pyright: ignore[reportUnknownArgumentType]
        return target[int(part)]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(target, dict) and part in target:
        return target[part]  # pyright: ignore[reportUnknownVariableType]
    raise _unknown_key(dotted)


def _assign(target: Any, part: str, value: Any, dotted: str) -> None:
    if isinstance(target, list) and part.isdigit() and int(part) < len(target):  # pyright: ignore[reportUnknownArgumentType]
        target[int(part)] = value
    elif isinstance(target, dict) and (part in target or dotted.startswith("colors.slots.")):
        target[part] = value
    else:
        raise _unknown_key(dotted)


def _unknown_key(key: str) -> ThemeError:
    return ThemeError(
        f"主題沒有這個設定：{key}",
        f"Unknown theme setting: {key}",
        hint_zh="可用的設定見 docs/themes.md。",
        hint_en="See docs/themes.md for the available settings.",
    )


def _validate(data: Any, origin: str) -> Theme:
    try:
        return Theme.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:6]
        )
        raise ThemeError(
            f"主題內容不正確（{origin}）。",
            f"Invalid theme ({origin}).",
            detail=problems,
        ) from exc


def theme_directories() -> list[Path]:
    """Folders searched for themes: the user's first, then the built-in ones."""
    return [paths.user_themes_dir(), paths.bundled_dir("themes")]


def list_themes() -> list[str]:
    """Names of all available themes (user themes shadow built-in ones of the same name)."""
    names: list[str] = []
    for directory in theme_directories():
        if directory.is_dir():
            for path in sorted(directory.glob("*.yaml")):
                if path.stem not in names:
                    names.append(path.stem)
    return names


def load_theme_file(path: Path) -> Theme:
    """Load and validate a theme YAML file.

    Raises:
        ThemeError: If the file cannot be read or is not a valid theme.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ThemeError(
            f"無法讀取主題檔：{path}",
            f"Cannot read theme file: {path}",
            detail=str(exc),
        ) from exc
    if not isinstance(data, dict):
        raise ThemeError(
            f"主題檔格式錯誤：{path.name}",
            f"Malformed theme file: {path.name}",
            detail="top-level value is not a mapping",
        )
    data.setdefault("name", path.stem)  # pyright: ignore[reportUnknownMemberType]
    return _validate(data, path.name)


def load_theme(name: str) -> Theme:
    """Load a theme by name from the user or built-in theme folders.

    Raises:
        ThemeError: If there is no theme with that name.
    """
    for directory in theme_directories():
        candidate = directory / f"{name}.yaml"
        if candidate.is_file():
            return load_theme_file(candidate)
    available = list_themes()
    raise ThemeError(
        f"找不到主題「{name}」。",
        f"Theme not found: {name}",
        hint_zh=f"可用的主題：{'、'.join(available) or '(無)'}",
        hint_en=f"Available themes: {', '.join(available) or 'none'}",
    )


def dump_theme(theme: Theme) -> str:
    """Serialise a theme to YAML (the format accepted by :func:`load_theme_file`)."""
    return yaml.safe_dump(theme.model_dump(), allow_unicode=True, sort_keys=False)
