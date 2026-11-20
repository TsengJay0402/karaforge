r"""ASS (Advanced SubStation Alpha) generator: render plan → subtitle script.

The same script is drawn by JASSUB in the browser and by ffmpeg's ``ass`` filter on export,
so what the editor previews is what the video contains.

**How the fill works.**  ASS has karaoke tags (``\k``, ``\kf``) but they only recolour the
text body: the outline keeps its colour, which is not how KTV videos look.  Instead every
line is drawn twice at the same position:

* layer 0 — the whole line in the *unsung* style, hidden left of the fill position with an
  inverse clip (``\iclip``);
* layer 1 — the whole line in the *sung* style, visible only left of the fill position
  (``\clip``).

Both clips are animated with a chain of ``\t(t1,t2,\clip(...))`` tags, one per token, so the
boundary sweeps across each token linearly during the token's time and body, outline and
shadow change colour together.

Every event is positioned absolutely with ``\an7\pos(x,y)``; ``PlayResX``/``PlayResY`` equal
the output resolution, so script units are pixels.

For interoperability the script also carries one *comment* event per lyric line with classic
``\k`` timing (the convention karaoke templaters use for their source lines).  Renderers
ignore comments; KaraForge's own ASS importer and Aegisub can read the timing back from them.
"""

from __future__ import annotations

import math

from karaforge import __version__
from karaforge.layout.plan import FillKey, PlanLine, PlanRuby, RenderPlan, TextRun
from karaforge.layout.theme import ass_color

ASS_WRITER_VERSION = "2"
_KAPPA = 0.5522847498
_DRAW_SCALE = 8  # \p4: drawing coordinates are in 1/8 pixel

_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FORMAT = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"


def ass_time(ms: int) -> str:
    """Format milliseconds as an ASS timestamp ``H:MM:SS.cc`` (rounded down to 10 ms)."""
    centiseconds = max(0, ms) // 10
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    seconds, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def floor_cs(ms: int) -> int:
    """Round a time down to the 10 ms grid of ASS event timestamps."""
    return (max(0, ms) // 10) * 10


def ceil_cs(ms: int) -> int:
    """Round a time up to the 10 ms grid of ASS event timestamps."""
    return -((-max(0, ms)) // 10) * 10


def escape_text(text: str) -> str:
    """Escape characters that ASS would interpret: braces, backslashes and line breaks."""
    return (
        text.replace("\\", "＼")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\r", "")
        .replace("\n", " ")
    )


def _num(value: float) -> str:
    """Compact decimal representation (at most two decimals, no trailing zeros)."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _style(
    name: str,
    family: str,
    size: float,
    fill: str,
    outline: str,
    shadow_color: str,
    outline_width: float,
    shadow: float,
    spacing: float = 0.0,
) -> str:
    return (
        f"Style: {name},{family},{_num(size)},{ass_color(fill)},{ass_color(fill)},"
        f"{ass_color(outline)},{ass_color(shadow_color)},0,0,0,0,100,100,{_num(spacing)},0,1,"
        f"{_num(outline_width)},{_num(shadow)},7,0,0,0,1"
    )


def _runs_text(runs: list[TextRun], base_family: str, base_size: float, base_spacing: float) -> str:
    """Text of a line with font / size / spacing switches where a run deviates from the style."""
    parts: list[str] = []
    family, size, spacing = base_family, base_size, base_spacing
    for run in runs:
        tags = ""
        if run.family != family:
            tags += f"\\fn{run.family}"
            family = run.family
        if abs(run.ass_size - size) > 1e-6:
            tags += f"\\fs{_num(run.ass_size)}"
            size = run.ass_size
        if abs(run.spacing - spacing) > 1e-6:
            tags += f"\\fsp{_num(run.spacing)}"
            spacing = run.spacing
        if tags:
            parts.append("{" + tags + "}")
        parts.append(escape_text(run.text))
    return "".join(parts)


def _fill_tags(
    keys: list[FillKey],
    event_start: int,
    left: float,
    top: float,
    bottom: float,
    tag: str,
) -> str:
    r"""Initial clip plus the chain of ``\t`` transforms that moves its right edge."""
    x_left, y_top, y_bottom = math.floor(left), math.floor(top), math.ceil(bottom)

    def clip(x: float) -> str:
        return f"\\{tag}({x_left},{y_top},{max(x_left, round(x))},{y_bottom})"

    # Before the first key nothing is sung.  Keys at or before the event start set the
    # initial state; the first key that lies in the future is reached with a jump (the fill
    # does not creep towards the line while it waits), later keys by linear motion.
    current = float(x_left)
    remaining = list(keys)
    jump = True
    previous_time = event_start
    while remaining and remaining[0].time_ms <= event_start:
        current = remaining.pop(0).x
        jump = False
    result = clip(current)
    for key in remaining:
        end = max(1, key.time_ms - event_start)
        begin = end if jump else min(end, max(1, previous_time - event_start))
        jump = False
        previous_time = key.time_ms
        if round(key.x) == round(current):
            continue
        result += f"\\t({begin},{end},{clip(key.x)})"
        current = key.x
    return result


def _line_events(line: PlanLine, plan: RenderPlan, base_family: str, base_size: float) -> list[str]:
    style = plan.style
    start = floor_cs(line.appear_ms)
    end = max(start + 10, ceil_cs(line.disappear_ms))
    fade = min(style.fade_ms, max(0, (end - start) // 3))
    prefix = f"\\an7\\pos({_num(line.x)},{_num(line.y)})"
    if fade > 0:
        prefix += f"\\fad({fade},{fade})"
    if style.blur > 0:
        prefix += f"\\blur{_num(style.blur)}"
    text = _runs_text(line.runs, base_family, base_size, style.letter_spacing)
    times = f"{ass_time(start)},{ass_time(end)}"

    def tags(tag: str, top: float, bottom: float) -> str:
        return _fill_tags(line.fill, start, line.clip_left, top, bottom, tag)

    events = [
        f"Dialogue: 0,{times},KF-Unsung,{line.id},0,0,0,,"
        f"{{{prefix}{tags('iclip', line.clip_top, line.clip_bottom)}}}{text}"
    ]
    if line.slot == "duet" and style.duet_mode == "dual" and {"male", "female"} <= set(style.slots):
        middle = (line.clip_top + line.clip_bottom) / 2.0
        events.append(
            f"Dialogue: 1,{times},KF-Sung-male,{line.id},0,0,0,,"
            f"{{{prefix}{tags('clip', line.clip_top, middle)}}}{text}"
        )
        events.append(
            f"Dialogue: 1,{times},KF-Sung-female,{line.id},0,0,0,,"
            f"{{{prefix}{tags('clip', middle, line.clip_bottom)}}}{text}"
        )
    else:
        events.append(
            f"Dialogue: 1,{times},KF-Sung-{line.slot},{line.id},0,0,0,,"
            f"{{{prefix}{tags('clip', line.clip_top, line.clip_bottom)}}}{text}"
        )
    for ruby in line.rubies:
        events.extend(_ruby_events(ruby, line, plan, times, start, fade))
    return events


def _ruby_events(
    ruby: PlanRuby, line: PlanLine, plan: RenderPlan, times: str, start: int, fade: int
) -> list[str]:
    margin = plan.style.outline + 2.0
    keys = [
        FillKey(time_ms=ruby.start_ms, x=ruby.x - margin),
        FillKey(time_ms=max(ruby.end_ms, ruby.start_ms), x=ruby.x + ruby.width + margin),
    ]
    prefix = f"\\an7\\pos({_num(ruby.x)},{_num(ruby.y)})\\fn{ruby.family}\\fs{_num(ruby.ass_size)}"
    if fade > 0:
        prefix += f"\\fad({fade},{fade})"
    top, bottom, left = ruby.y - margin, ruby.y + ruby.height + margin, ruby.x - margin - 2.0
    text = escape_text(ruby.text)
    return [
        f"Dialogue: 0,{times},KF-Ruby-Unsung,{line.id},0,0,0,,"
        f"{{{prefix}{_fill_tags(keys, start, left, top, bottom, 'iclip')}}}{text}",
        f"Dialogue: 1,{times},KF-Ruby-Sung-{line.slot},{line.id},0,0,0,,"
        f"{{{prefix}{_fill_tags(keys, start, left, top, bottom, 'clip')}}}{text}",
    ]


def circle_path(radius: float) -> str:
    r"""ASS drawing commands for a circle of the given radius (with ``\p4`` scaling)."""
    r = radius * _DRAW_SCALE
    k = r * _KAPPA
    points = [
        ("m", [(r, 0)]),
        ("b", [(r + k, 0), (2 * r, r - k), (2 * r, r)]),
        ("b", [(2 * r, r + k), (r + k, 2 * r), (r, 2 * r)]),
        ("b", [(r - k, 2 * r), (0, r + k), (0, r)]),
        ("b", [(0, r - k), (r - k, 0), (r, 0)]),
    ]
    return " ".join(
        command + " " + " ".join(f"{round(x)} {round(y)}" for x, y in coordinates)
        for command, coordinates in points
    )


def _karaoke_comment(line: PlanLine) -> str:
    r"""A comment event with ``\k`` timing, for other tools and for re-importing."""
    start = floor_cs(line.sing_start_ms)
    end = max(start + 10, ceil_cs(line.sing_end_ms))
    cursor = start
    parts: list[str] = []
    for token in line.tokens:
        token_start = max(cursor, floor_cs(token.start_ms))
        if token_start > cursor:
            parts.append(f"{{\\k{(token_start - cursor) // 10}}}")
        token_end = max(token_start, floor_cs(token.end_ms))
        parts.append(f"{{\\k{(token_end - token_start) // 10}}}{escape_text(token.text)}")
        cursor = token_end
    return (
        f"Comment: 0,{ass_time(start)},{ass_time(end)},KF-Unsung,{line.singer},0,0,0,"
        f"karaoke,{''.join(parts)}"
    )


def render_ass(plan: RenderPlan, *, title: str = "") -> str:
    """Generate the ASS script for a render plan.

    Args:
        plan: Output of :func:`karaforge.layout.engine.build_plan`.
        title: Song title for the script header.

    Returns:
        The complete script as text with Unix line endings.
    """
    style = plan.style
    base_family = style.font_family
    base_size = style.font_ass_size
    ruby_size = style.ruby_ass_size
    ruby_outline = max(1.0, style.outline * 0.5)

    header = [
        "[Script Info]",
        f"; Generated by KaraForge {__version__} (theme: {style.theme})",
        f"Title: {title.replace(chr(10), ' ')}",
        "ScriptType: v4.00+",
        f"PlayResX: {plan.width}",
        f"PlayResY: {plan.height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "Kerning: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        _STYLE_FORMAT,
        _style(
            "KF-Unsung",
            base_family,
            base_size,
            style.unsung_fill,
            style.unsung_outline,
            style.shadow_color,
            style.outline,
            style.shadow,
            style.letter_spacing,
        ),
        _style(
            "KF-Ruby-Unsung",
            base_family,
            ruby_size,
            style.unsung_fill,
            style.unsung_outline,
            style.shadow_color,
            ruby_outline,
            0.0,
        ),
    ]
    for slot, (fill, outline) in style.slots.items():
        header.append(
            _style(
                f"KF-Sung-{slot}",
                base_family,
                base_size,
                fill,
                outline,
                style.shadow_color,
                style.outline,
                style.shadow,
                style.letter_spacing,
            )
        )
        header.append(
            _style(
                f"KF-Ruby-Sung-{slot}",
                base_family,
                ruby_size,
                fill,
                outline,
                style.shadow_color,
                ruby_outline,
                0.0,
            )
        )
    card = plan.title_card
    card_rows = card.lines if card is not None else []
    card_title_size = next((row.ass_size for row in card_rows if row.role == "title"), base_size)
    card_info_size = next((row.ass_size for row in card_rows if row.role == "info"), base_size)
    header += [
        _style(
            "KF-Card-Title",
            base_family,
            card_title_size,
            style.card_accent,
            style.card_outline,
            style.shadow_color,
            style.outline,
            style.shadow,
        ),
        _style(
            "KF-Card-Info",
            base_family,
            card_info_size,
            style.card_fill,
            style.card_outline,
            style.shadow_color,
            max(1.0, style.outline * 0.7),
            style.shadow,
        ),
        _style(
            "KF-Dot",
            base_family,
            base_size,
            style.countdown_fill,
            style.countdown_outline,
            style.shadow_color,
            max(1.0, style.outline * 0.5),
            0.0,
        ),
        "",
        "[Events]",
        _EVENT_FORMAT,
    ]

    events: list[str] = []
    if card is not None:
        times = f"{ass_time(floor_cs(card.start_ms))},{ass_time(ceil_cs(card.end_ms))}"
        fade = min(400, max(0, (card.end_ms - card.start_ms) // 4))
        for row in card.lines:
            name = "KF-Card-Title" if row.role == "title" else "KF-Card-Info"
            events.append(
                f"Dialogue: 3,{times},{name},card,0,0,0,,"
                f"{{\\an7\\pos({_num(row.x)},{_num(row.y)})\\fn{row.family}\\fs{_num(row.ass_size)}"
                f"\\fad({fade},{fade})}}{escape_text(row.text)}"
            )
    for countdown in plan.countdowns:
        for dot in countdown.dots:
            start = floor_cs(countdown.appear_ms)
            end = max(start + 10, floor_cs(dot.off_ms))
            fade = min(120, (end - start) // 3)
            events.append(
                f"Dialogue: 2,{ass_time(start)},{ass_time(end)},KF-Dot,countdown,0,0,0,,"
                f"{{\\an7\\pos({_num(dot.x - dot.radius)},{_num(dot.y - dot.radius)})"
                f"\\fad({fade},{fade})\\p4}}{circle_path(dot.radius)}{{\\p0}}"
            )
    for line in plan.lines:
        events.append(_karaoke_comment(line))
        events.extend(_line_events(line, plan, base_family, base_size))
    return "\n".join([*header, *events]) + "\n"
