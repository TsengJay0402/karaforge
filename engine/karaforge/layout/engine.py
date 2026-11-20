"""The KTV layout engine: project + theme → :class:`~karaforge.layout.plan.RenderPlan`.

Rules implemented here (see ``docs/layout.md`` for the reasoning and pictures):

* **Rows alternate.**  After a long pause the first line goes to the first row and the second
  line to the second row, and both appear together.  From then on each new line takes the row
  whose line has just been sung, shortly after the other row's line starts, but never later
  than the lead-in time before it is sung itself.
* **Fill.**  The sung colour sweeps from the left edge of a token to its right edge linearly
  over the token's duration; a line's fill is therefore piecewise linear over its tokens.
* **Wrapping.**  A line wider than the allowed share of the frame is split into several
  display lines at the most balanced point, preferring a punctuation mark or a space and
  never inside a word; each part keeps the times of its own tokens.
* **Countdown.**  When a line follows a pause of at least ``countdown.min_gap_ms``, dots above
  its start disappear one per beat until it begins.  Where the lyrics start a new paragraph
  a pause of ``layout.paragraph_gap_ms`` is enough for a fresh screen and a countdown.
* **Title card.**  Title and credits are shown before the first line when there is time.
* **Ruby.**  Readings are centred above their token; neighbours are pushed apart just enough
  for their readings not to collide.

Text is measured with the real fonts through HarfBuzz; characters missing from the theme's
font are set in the fallback font explicitly so that the browser preview and the ffmpeg export
(which have different system fonts) draw the same glyphs.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, replace
from itertools import pairwise

from karaforge.errors import ThemeError
from karaforge.layout.fonts import FontFace, FontLibrary, default_library
from karaforge.layout.plan import (
    FillKey,
    PlanCardLine,
    PlanCountdown,
    PlanDot,
    PlanFont,
    PlanLine,
    PlanRuby,
    PlanStyle,
    PlanTitleCard,
    PlanToken,
    RenderPlan,
    TextRun,
)
from karaforge.layout.theme import Theme, load_theme
from karaforge.project.schema import Line, Project
from karaforge.text.tokenize import TokenKind, tokenize

LAYOUT_VERSION = "2"
"""Bump when layout rules change in a way that moves or re-times anything."""

_MIN_LINGER_MS = 300
_CARD_START_MS = 300
_UNKERNED_SPACING = 0.02


def _r(value: float) -> float:
    """Round a coordinate for stable, readable plans."""
    return round(value, 2)


@dataclass
class _Char:
    char: str
    advance: float
    """Advance in pixels, without any extra spacing."""
    face: FontFace
    extra: float = 0.0
    """Extra space after this character (letter spacing, room for ruby)."""


@dataclass
class _Tok:
    index: int
    text: str
    start_ms: int
    end_ms: int
    first: int
    """Index of the token's first character in the line."""
    last: int
    """One past the token's last character."""
    core_first: int
    core_last: int
    ruby: str | None
    breakable: bool
    """A line may be wrapped after this token without splitting a word."""
    preferred_break: bool
    """The token ends with punctuation or a space."""


@dataclass
class _Measured:
    """A display line before it is placed."""

    source: Line
    part: int
    chars: list[_Char]
    tokens: list[_Tok]
    slot: str
    row: int = 0
    appear_ms: int = 0
    disappear_ms: int = 0
    rubies: list[tuple[int, str, float, FontFace]] = field(
        default_factory=list[tuple[int, str, float, FontFace]]
    )
    """``(token position, text, width, face)`` for each reading."""

    @property
    def width(self) -> float:
        if not self.chars:
            return 0.0
        return sum(c.advance + c.extra for c in self.chars) - self.chars[-1].extra

    @property
    def sing_start(self) -> int:
        return self.tokens[0].start_ms

    @property
    def sing_end(self) -> int:
        return max(token.end_ms for token in self.tokens)

    def left_of(self, char_index: int) -> float:
        """Offset from the line's left edge to the left side of a character."""
        return sum(c.advance + c.extra for c in self.chars[:char_index])

    def core_centre(self, token: _Tok) -> float:
        """Offset of the middle of a token's core glyphs (spacing after them excluded)."""
        left = self.left_of(token.core_first)
        if token.core_last <= token.core_first:
            return left
        last = token.core_last - 1
        return (left + self.left_of(last) + self.chars[last].advance) / 2.0


class _Fonts:
    """Resolves which font draws a character and measures text at pixel sizes."""

    def __init__(self, library: FontLibrary, theme: Theme) -> None:
        self.library = library
        self.main = library.find(theme.font.family)
        try:
            self.fallback = library.find(theme.font.fallback)
        except ThemeError:
            self.fallback = self.main
        self.used: dict[str, FontFace] = {self.main.family: self.main}
        self.missing: set[str] = set()

    def face_for(self, char: str) -> FontFace:
        if char.isspace() or unicodedata.category(char)[0] in "CM":
            return self.main
        if self.library.measurer(self.main).has_glyph(char):
            return self.main
        if self.fallback is not self.main and self.library.measurer(self.fallback).has_glyph(char):
            self.used[self.fallback.family] = self.fallback
            return self.fallback
        self.missing.add(char)
        return self.main

    def measure(self, text: str, em_px: float, *, kerned: bool = True) -> list[_Char]:
        """Measure ``text`` character by character, switching fonts where needed."""
        result: list[_Char] = []
        start = 0
        faces = [self.face_for(char) for char in text]
        while start < len(text):
            end = start
            while end < len(text) and faces[end] is faces[start]:
                end += 1
            face = faces[start]
            scale = em_px / face.units_per_em
            advances = self.library.measurer(face).advances(text[start:end], kerned=kerned)
            result.extend(
                _Char(char, advance * scale, face)
                for char, advance in zip(text[start:end], advances, strict=True)
            )
            start = end
        return result

    def single_face(self, text: str) -> FontFace:
        """One font for all of ``text``: the main font unless it lacks one of the glyphs."""
        if all(self.face_for(char) is self.main for char in text):
            return self.main
        self.used[self.fallback.family] = self.fallback
        return self.fallback


def _timed_tokens(line: Line) -> list[tuple[int, str, int, int, str | None]]:
    """Tokens of a line as ``(index, text, start_ms, end_ms, ruby)``.

    Tokens without times (inserted by an edit and not aligned yet) are placed where the
    previous token ends, so they are drawn but take no time.  Returns an empty list when no
    token of the line has times.
    """
    starts = [token.start_ms for token in line.tokens if token.start_ms is not None]
    if not starts:
        return []
    result: list[tuple[int, str, int, int, str | None]] = []
    previous_end = starts[0]
    for index, token in enumerate(line.tokens):
        if token.start_ms is not None and token.end_ms is not None:
            start = max(0, token.start_ms)
            end = max(start, token.end_ms)
        else:
            start = end = previous_end
        result.append((index, token.text, start, end, token.ruby))
        previous_end = max(previous_end, end)
    return result


def _measure_line(
    line: Line, fonts: _Fonts, em_px: float, spacing: float, slot: str
) -> _Measured | None:
    timed = _timed_tokens(line)
    if not timed:
        return None
    text = "".join(item[1] for item in timed).rstrip()
    if not text:
        return None
    chars = fonts.measure(text, em_px, kerned=spacing == 0.0)
    for char in chars:
        char.extra = spacing
    tokens: list[_Tok] = []
    cursor = 0
    for index, token_text, start, end, ruby in timed:
        first = cursor
        last = min(len(text), cursor + len(token_text))
        cursor += len(token_text)
        if first >= len(text):
            break
        pieces = tokenize(token_text)
        core = "".join(piece.core for piece in pieces)
        offset = max(0, token_text.find(core)) if core else 0
        core_first = min(last, first + offset)
        core_last = min(last, core_first + len(core)) if core else last
        suffix = token_text[offset + len(core) :]
        tokens.append(
            _Tok(
                index=index,
                text=text[first:last],
                start_ms=start,
                end_ms=end,
                first=first,
                last=last,
                core_first=core_first,
                core_last=core_last,
                ruby=ruby,
                breakable=True,
                # A good place to wrap: after a space, or after CJK punctuation.  A hyphen
                # inside a compound is only a last resort.
                preferred_break=bool(suffix)
                and (suffix[-1].isspace() or not (pieces and pieces[-1].kind is TokenKind.WORD)),
            )
        )
    if not tokens:
        return None
    # A hyphenated or glued word ("rock-" "n-" "roll", "3" "D") must stay on one line: a
    # break is only allowed where the text itself has a boundary.
    for position, token in enumerate(tokens[:-1]):
        following = tokens[position + 1]
        glued = (
            token.text[-1:].isalnum()
            and following.text[:1].isalnum()
            and token.text[-1:].isascii()
            and following.text[:1].isascii()
        )
        token.breakable = not glued
    return _Measured(source=line, part=0, chars=chars, tokens=tokens, slot=slot)


def _split(measured: _Measured, at: int) -> tuple[_Measured, _Measured]:
    """Split a measured line before token position ``at``."""
    boundary = measured.tokens[at].first
    left_chars = measured.chars[:boundary]
    while left_chars and left_chars[-1].char.isspace():
        left_chars = left_chars[:-1]
    kept = len(left_chars)
    left_tokens = [
        replace(token, last=min(token.last, kept), core_last=min(token.core_last, kept))
        for token in measured.tokens[:at]
    ]
    right_tokens = [
        replace(
            token,
            first=token.first - boundary,
            last=token.last - boundary,
            core_first=token.core_first - boundary,
            core_last=token.core_last - boundary,
        )
        for token in measured.tokens[at:]
    ]
    left = _Measured(measured.source, 0, left_chars, left_tokens, measured.slot)
    right = _Measured(measured.source, 0, measured.chars[boundary:], right_tokens, measured.slot)
    return left, right


def wrap(measured: _Measured, max_width: float, depth: int = 0) -> list[_Measured]:
    """Split a line that is too wide into balanced parts at the best boundaries."""
    if measured.width <= max_width or len(measured.tokens) < 2 or depth >= 3:
        return [measured]
    total = measured.width
    best: tuple[float, int] | None = None
    for at in range(1, len(measured.tokens)):
        previous = measured.tokens[at - 1]
        if not previous.breakable:
            continue
        left_width = measured.left_of(measured.tokens[at].first)
        imbalance = abs(2.0 * left_width - total)
        penalty = 0.0 if previous.preferred_break else 0.12 * total
        cost = imbalance + penalty
        if best is None or cost < best[0]:
            best = (cost, at)
    if best is None:
        return [measured]
    left, right = _split(measured, best[1])
    return [*wrap(left, max_width, depth + 1), *wrap(right, max_width, depth + 1)]


def _apply_ruby(
    measured: _Measured, fonts: _Fonts, theme: Theme, em_px: float, scale: float
) -> None:
    """Measure readings and widen the gaps between tokens whose readings would collide."""
    ruby_em = em_px * theme.ruby.scale
    entries: list[tuple[int, str, float, FontFace, float]] = []
    for position, token in enumerate(measured.tokens):
        if not token.ruby:
            continue
        face = fonts.single_face(token.ruby)
        if face is not fonts.main:
            fonts.used[face.family] = face
        width = fonts.library.measurer(face).width(token.ruby) * ruby_em / face.units_per_em
        entries.append((position, token.ruby, width, face, 0.0))
    if not entries:
        return
    min_spacing = theme.ruby.min_spacing * scale
    for (position, _text, width, _face, _), (next_position, _t, next_width, _f, _n) in pairwise(
        entries
    ):
        token, following = measured.tokens[position], measured.tokens[next_position]
        centre = measured.core_centre(token)
        next_centre = measured.core_centre(following)
        needed = (width + next_width) / 2.0 + min_spacing - (next_centre - centre)
        if needed > 0.0 and following.first > 0:
            measured.chars[following.first - 1].extra += needed
    measured.rubies = [(position, text, width, face) for position, text, width, face, _ in entries]


def _runs(measured: _Measured, em_px: float) -> list[TextRun]:
    """Group characters into runs of equal font and spacing."""
    runs: list[TextRun] = []
    for char in measured.chars:
        family = char.face.family
        if runs and runs[-1].family == family and abs(runs[-1].spacing - char.extra) < 1e-6:
            runs[-1].text += char.char
        else:
            runs.append(
                TextRun(
                    text=char.char,
                    family=family,
                    ass_size=_r(char.face.ass_size(em_px)),
                    spacing=_r(char.extra),
                )
            )
    return runs


def _sections(lines: list[_Measured], gap_ms: int, paragraph_gap_ms: int) -> list[list[_Measured]]:
    """Group the lines into stretches of continuous singing.

    A new stretch starts after a pause of ``gap_ms``, or after a pause of only
    ``paragraph_gap_ms`` where the lyrics begin a new paragraph.
    """
    structured = _has_paragraphs(lines)
    sections: list[list[_Measured]] = []
    latest_end: int | None = None
    for line in lines:
        pause = None if latest_end is None else line.sing_start - latest_end
        new_paragraph = structured and bool(sections) and _starts_paragraph(line, sections[-1][-1])
        if pause is None or pause >= gap_ms or (new_paragraph and pause >= paragraph_gap_ms):
            sections.append([])
        sections[-1].append(line)
        latest_end = max(latest_end or 0, line.sing_end)
    return sections


def _starts_paragraph(line: _Measured, previous: _Measured) -> bool:
    return line.source.paragraph != previous.source.paragraph


def _has_paragraphs(lines: list[_Measured]) -> bool:
    """Whether the paragraphs of the lyrics mean anything.

    Lyrics pasted from a web page often have a blank line after *every* line.  Then each
    line is a "paragraph" of its own and the blank lines say nothing about the song's
    sections; paragraphs only count when at least one of them holds two lines.
    """
    sources: list[Line] = []
    for line in lines:
        if not sources or sources[-1] is not line.source:
            sources.append(line.source)
    return any(first.paragraph == second.paragraph for first, second in pairwise(sources))


def _schedule(sections: list[list[_Measured]], theme: Theme, duration_ms: int) -> None:
    """Assign rows and appear/disappear times."""
    layout = theme.layout
    rows = len(layout.rows)
    previous_end: int | None = None
    previous_tail: list[_Measured] = []
    for section in sections:
        first_start = section[0].sing_start
        first_appear = max(0, first_start - layout.first_lead_in_ms)
        if previous_end is not None:
            first_appear = max(first_appear, previous_end + _MIN_LINGER_MS)
            first_appear = min(first_appear, max(previous_end, first_start - layout.fade_ms))
            for line in previous_tail:
                line.disappear_ms = min(line.disappear_ms, first_appear)
        for index, line in enumerate(section):
            line.row = index % rows
            if index < rows:
                line.appear_ms = min(first_appear, line.sing_start)
                continue
            predecessor = section[index - rows]
            trigger = section[index - 1].sing_start + layout.swap_delay_ms
            earliest = predecessor.sing_end
            latest = line.sing_start - layout.lead_in_ms
            appear = max(earliest, min(trigger, latest))
            appear = min(appear, max(earliest, line.sing_start))
            line.appear_ms = max(0, appear)
            predecessor.disappear_ms = line.appear_ms
        section_end = max(line.sing_end for line in section)
        tail = section[-rows:]
        clear_at = section_end + layout.linger_ms
        if duration_ms:
            clear_at = min(clear_at, max(duration_ms, section_end))
        for line in tail:
            line.disappear_ms = clear_at
        previous_end = section_end
        previous_tail = tail
    for section in sections:
        for line in section:
            line.disappear_ms = max(line.disappear_ms, line.sing_end, line.appear_ms + 1)


def _beat_interval(project: Project, theme: Theme) -> int:
    tempo = project.analysis.tempo_bpm
    if not theme.countdown.use_beats or tempo is None or not 30.0 <= tempo <= 300.0:
        return theme.countdown.interval_ms
    interval = 60000.0 / tempo
    while interval < 450.0:
        interval *= 2.0
    while interval > 1150.0:
        interval /= 2.0
    return round(interval)


def _credits(project: Project) -> list[str]:
    meta = project.meta
    english = meta.language.lower().startswith("en")
    rows: list[str] = []
    if meta.artist:
        rows.append(f"Vocals  {meta.artist}" if english else f"演唱 {meta.artist}")
    writers: list[str] = []
    if meta.lyricist:
        writers.append(f"Lyrics  {meta.lyricist}" if english else f"作詞 {meta.lyricist}")
    if meta.composer:
        writers.append(f"Music  {meta.composer}" if english else f"作曲 {meta.composer}")
    if writers:
        rows.append("    ".join(writers) if english else " ".join(writers))
    return rows


def build_plan(
    project: Project,
    theme: Theme | None = None,
    library: FontLibrary | None = None,
) -> RenderPlan:
    """Lay out a project.

    Args:
        project: The project; lines without any timed token are left out.
        theme: Theme to use.  Defaults to the project's theme with its overrides applied.
        library: Fonts to use.  Defaults to the bundled and user fonts.

    Returns:
        The render plan in the project's output resolution.

    Raises:
        ThemeError: If the theme or one of its fonts cannot be found.
    """
    resolved = theme or load_theme(project.style.theme).with_overrides(project.style.overrides)
    fonts = _Fonts(library or default_library(), resolved)
    width, height = project.render.resolution
    scale = height / resolved.reference_height
    em_px = resolved.font.size * scale
    outline = resolved.text.outline * scale
    shadow = resolved.text.shadow * scale
    slots = {singer.id: singer.theme_slot for singer in project.singers}

    # libass kerns text only when its letter spacing is exactly zero.  Ruby adds spacing to
    # single glyphs, which would leave a line half kerned; a negligible uniform spacing keeps
    # the whole plan in the unkerned mode instead.
    spacing = resolved.font.letter_spacing * scale
    if resolved.ruby.enabled and spacing == 0.0:
        spacing = _UNKERNED_SPACING

    # ---- measure, add ruby spacing, wrap
    display: list[_Measured] = []
    max_width = resolved.layout.max_width * width
    for line in project.lines:
        measured = _measure_line(line, fonts, em_px, spacing, slots.get(line.singer, "male"))
        if measured is None:
            continue
        if resolved.ruby.enabled:
            _apply_ruby(measured, fonts, resolved, em_px, scale)
        parts = wrap(measured, max_width)
        for number, part in enumerate(parts, start=1):
            part.part = number if len(parts) > 1 else 0
            if resolved.ruby.enabled and len(parts) > 1:
                part.rubies = []
                _apply_ruby(part, fonts, resolved, em_px, scale)
            display.append(part)

    duration_ms = project.meta.duration_ms
    sections = _sections(display, resolved.layout.section_gap_ms, resolved.layout.paragraph_gap_ms)
    structured = _has_paragraphs(display)
    _schedule(sections, resolved, duration_ms)

    main = fonts.main
    unit = em_px / main.units_per_em
    ruby_em = em_px * resolved.ruby.scale
    plan_lines: list[PlanLine] = []
    countdowns: list[PlanCountdown] = []
    interval = _beat_interval(project, resolved)
    previous_section_end: int | None = None
    previous_tail: _Measured | None = None

    for section in sections:
        for position, measured in enumerate(section):
            row = resolved.layout.rows[measured.row]
            line_width = measured.width
            if row.align == "left":
                x = row.margin * width
            elif row.align == "right":
                x = width - row.margin * width - line_width
            else:
                x = (width - line_width) / 2.0
            # Put the middle of the ideographs on the row's centre line.
            centre_above_baseline = (main.ideograph_top_units - main.ideograph_bottom_units) / 2.0
            baseline = row.y * height + centre_above_baseline * unit
            ascent = max(
                char.face.ascent_units * em_px / char.face.units_per_em for char in measured.chars
            )
            line_height = max(
                char.face.line_units * em_px / char.face.units_per_em for char in measured.chars
            )
            y = baseline - ascent
            ideograph_top = baseline - main.ideograph_top_units * unit

            tokens: list[PlanToken] = []
            for index, token in enumerate(measured.tokens):
                x0 = x + measured.left_of(token.first)
                if index + 1 < len(measured.tokens):
                    x1 = x + measured.left_of(measured.tokens[index + 1].first)
                else:
                    x1 = x + line_width
                tokens.append(
                    PlanToken(
                        index=token.index,
                        text=token.text,
                        x0=_r(x0),
                        x1=_r(x1),
                        start_ms=token.start_ms,
                        end_ms=token.end_ms,
                    )
                )

            fill: list[FillKey] = []
            for index, token in enumerate(tokens):
                left = token.x0 - outline if index == 0 else token.x0
                right = token.x1 + outline + shadow if index == len(tokens) - 1 else token.x1
                for key in (
                    FillKey(time_ms=token.start_ms, x=_r(left)),
                    FillKey(time_ms=max(token.end_ms, token.start_ms), x=_r(right)),
                ):
                    if fill and key.time_ms < fill[-1].time_ms:
                        key = FillKey(time_ms=fill[-1].time_ms, x=key.x)
                    if fill and key.time_ms == fill[-1].time_ms and key.x == fill[-1].x:
                        continue
                    fill.append(key)

            rubies: list[PlanRuby] = []
            ruby_height = 0.0
            for token_position, text, ruby_width, face in measured.rubies:
                token = measured.tokens[token_position]
                centre = x + measured.core_centre(token)
                ruby_unit = ruby_em / face.units_per_em
                ruby_baseline = (
                    ideograph_top
                    - resolved.ruby.gap * scale
                    - (face.ideograph_bottom_units * ruby_unit)
                )
                ruby_height = max(ruby_height, face.line_units * ruby_unit)
                rubies.append(
                    PlanRuby(
                        token_index=token.index,
                        text=text,
                        x=_r(centre - ruby_width / 2.0),
                        y=_r(ruby_baseline - face.ascent_units * ruby_unit),
                        width=_r(ruby_width),
                        height=_r(face.line_units * ruby_unit),
                        ass_size=_r(face.ass_size(ruby_em)),
                        family=face.family,
                        start_ms=token.start_ms,
                        end_ms=token.end_ms,
                    )
                )

            line_id = (
                measured.source.id
                if measured.part == 0
                else f"{measured.source.id}.{measured.part}"
            )
            margin = outline + shadow + 4.0 * scale
            plan_lines.append(
                PlanLine(
                    id=line_id,
                    source_line=measured.source.id,
                    part=measured.part,
                    singer=measured.source.singer,
                    slot=measured.slot,
                    row=measured.row,
                    x=_r(x),
                    y=_r(y),
                    width=_r(line_width),
                    height=_r(line_height),
                    baseline=_r(baseline),
                    text="".join(char.char for char in measured.chars),
                    runs=_runs(measured, em_px),
                    tokens=tokens,
                    rubies=rubies,
                    appear_ms=measured.appear_ms,
                    disappear_ms=measured.disappear_ms,
                    sing_start_ms=measured.sing_start,
                    sing_end_ms=measured.sing_end,
                    fill=fill,
                    clip_top=_r(y - margin),
                    clip_bottom=_r(y + line_height + margin),
                    clip_left=_r(x - margin),
                    clip_right=_r(x + line_width + margin),
                )
            )

            # ---- countdown for the first line after a long pause
            if position == 0 and resolved.countdown.enabled:
                gap = measured.sing_start - (previous_section_end or 0)
                # A paragraph that got its own section counts in after a shorter pause too.
                counted_in = (
                    structured
                    and previous_tail is not None
                    and _starts_paragraph(measured, previous_tail)
                )
                if gap >= resolved.countdown.min_gap_ms or counted_in:
                    radius = resolved.countdown.radius * scale
                    step = 2.0 * radius + resolved.countdown.spacing * scale
                    dots_top = (
                        (ideograph_top - ruby_height if rubies else y)
                        - resolved.countdown.offset * scale
                        - 2.0 * radius
                    )
                    count = resolved.countdown.dots
                    appear = max(measured.appear_ms, measured.sing_start - (count + 1) * interval)
                    dots = [
                        PlanDot(
                            x=_r(x + radius + number * step),
                            y=_r(dots_top + radius),
                            radius=_r(radius),
                            off_ms=measured.sing_start - (count - number) * interval,
                        )
                        for number in range(count)
                    ]
                    dots = [dot for dot in dots if dot.off_ms > appear]
                    if dots:
                        countdowns.append(
                            PlanCountdown(line_id=line_id, appear_ms=max(0, appear), dots=dots)
                        )
        previous_section_end = max(line.sing_end for line in section)
        previous_tail = section[-1]

    # ---- title card
    card: PlanTitleCard | None = None
    settings = resolved.title_card
    if settings.enabled and project.meta.title.strip() and plan_lines:
        first_start = min(line.sing_start_ms for line in plan_lines)
        end = min(_CARD_START_MS + settings.max_duration_ms, first_start - 500)
        if end - _CARD_START_MS >= settings.min_duration_ms:
            rows = [(project.meta.title.strip(), "title", settings.title_size * scale)]
            rows += [(text, "info", settings.info_size * scale) for text in _credits(project)]
            total = sum(size for _t, _role, size in rows) + settings.line_gap * scale * (
                len(rows) - 1
            )
            cursor = settings.y * height - total / 2.0
            card_lines: list[PlanCardLine] = []
            for text, role, size in rows:
                face = fonts.single_face(text)
                fonts.used[face.family] = face
                text_width = fonts.library.measurer(face).width(text) * size / face.units_per_em
                # Vertically centre the ideographs of this row in a box of height ``size``.
                row_baseline = (
                    cursor
                    + size / 2.0
                    + ((face.ideograph_top_units - face.ideograph_bottom_units) / 2.0)
                    * size
                    / face.units_per_em
                )
                card_lines.append(
                    PlanCardLine(
                        text=text,
                        role=role,
                        x=_r((width - text_width) / 2.0),
                        y=_r(row_baseline - face.ascent_units * size / face.units_per_em),
                        width=_r(text_width),
                        family=face.family,
                        ass_size=_r(face.ass_size(size)),
                    )
                )
                cursor += size + settings.line_gap * scale
            card = PlanTitleCard(start_ms=_CARD_START_MS, end_ms=end, lines=card_lines)

    style = PlanStyle(
        theme=resolved.name,
        font_family=main.family,
        font_ass_size=_r(main.ass_size(em_px)),
        ruby_ass_size=_r(main.ass_size(ruby_em)),
        letter_spacing=_r(spacing),
        outline=_r(outline),
        shadow=_r(shadow),
        blur=_r(resolved.text.blur * scale),
        fade_ms=resolved.layout.fade_ms,
        unsung_fill=resolved.colors.unsung.fill,
        unsung_outline=resolved.colors.unsung.outline,
        shadow_color=resolved.colors.shadow,
        slots={name: (pair.fill, pair.outline) for name, pair in resolved.colors.slots.items()},
        duet_mode=resolved.colors.duet_mode,
        countdown_fill=resolved.countdown.fill,
        countdown_outline=resolved.countdown.outline,
        card_fill=resolved.title_card.fill,
        card_outline=resolved.title_card.outline,
        card_accent=resolved.title_card.accent,
    )
    for line in plan_lines:
        if line.slot not in style.slots:
            pair = resolved.slot(line.slot)
            style.slots[line.slot] = (pair.fill, pair.outline)
    return RenderPlan(
        width=width,
        height=height,
        duration_ms=duration_ms,
        style=style,
        fonts=[PlanFont(family=face.family, file=face.path.name) for face in fonts.used.values()],
        lines=plan_lines,
        countdowns=countdowns,
        title_card=card,
        missing_glyphs=sorted(fonts.missing),
    )
