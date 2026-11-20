"""Pydantic models for ``project.json`` (schema version 2).

Version history:

* **1** — the format of the original specification.
* **2** — lines can carry a ``time_hint`` (the line-level time of an imported LRC / SRT / ASS
  file) and tokens can have ``source = "import"`` (word-level timing that came from a file).

Conventions (see ``docs/project-format.md``):

* every time is an integer number of milliseconds;
* a line has no stored start/end — they are derived from its tokens;
* a token whose times are ``None`` has not been aligned yet;
* a token with ``locked=True`` is never modified by any automatic process.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 2

TokenSource = Literal["auto", "manual", "import"]
RubySource = Literal["auto", "manual"]
BackgroundType = Literal["video", "image", "color", "blur"]


class _Model(BaseModel):
    """Base class: reject unknown fields so that typos and stale formats surface early."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Token(_Model):
    """The smallest unit that is timed and filled: one CJK character or one Latin word.

    ``text`` keeps any punctuation and whitespace attached to the unit, so joining the
    ``text`` of all tokens of a line reproduces the line exactly.
    """

    text: str = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    ruby: str | None = None
    ruby_source: RubySource | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    locked: bool = False
    source: TokenSource = "auto"

    @model_validator(mode="after")
    def _check_times(self) -> Token:
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("start_ms and end_ms must both be set or both be null")
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms must not be earlier than start_ms")
        if self.locked and self.start_ms is None:
            raise ValueError("a locked token must have times")
        return self

    @property
    def is_timed(self) -> bool:
        """Whether the token has been aligned."""
        return self.start_ms is not None

    def retimed(
        self,
        start_ms: int | None,
        end_ms: int | None,
        *,
        confidence: float | None = None,
        source: TokenSource | None = None,
        locked: bool | None = None,
    ) -> Token:
        """Return a validated copy with new times.

        Start and end have to change together (a token with only one of them is invalid),
        which plain attribute assignment cannot do, so timing changes go through this method.

        Args:
            start_ms: New start, or ``None`` to clear the timing.
            end_ms: New end, or ``None`` to clear the timing.
            confidence: New confidence (cleared when omitted).
            source: New source; unchanged when omitted.
            locked: New lock state; unchanged when omitted.
        """
        data = self.model_dump()
        data.update(start_ms=start_ms, end_ms=end_ms, confidence=confidence)
        if source is not None:
            data["source"] = source
        if locked is not None:
            data["locked"] = locked
        return Token.model_validate(data)


class Line(_Model):
    """One lyric line as written by the user (it may be wrapped for display later)."""

    id: str = Field(min_length=1)
    singer: str = "m"
    paragraph: int = Field(default=0, ge=0)
    tokens: list[Token] = Field(default_factory=list[Token])
    time_hint: tuple[int, int | None] | None = None
    """``(start_ms, end_ms)`` of the line as given by an imported file with line-level timing
    (``end_ms`` may be unknown).  The aligner uses it as the line's window instead of
    searching for the line; it is *not* the line's time — that is always derived from the
    tokens."""

    @model_validator(mode="after")
    def _check_hint(self) -> Line:
        if self.time_hint is not None:
            start, end = self.time_hint
            if start < 0 or (end is not None and end < start):
                raise ValueError("time_hint must be a non-negative, ordered (start, end) pair")
        return self

    @property
    def text(self) -> str:
        """The full line text."""
        return "".join(token.text for token in self.tokens)

    @property
    def start_ms(self) -> int | None:
        """Start of the first timed token, or ``None`` when nothing is timed."""
        return next((t.start_ms for t in self.tokens if t.start_ms is not None), None)

    @property
    def end_ms(self) -> int | None:
        """End of the last timed token, or ``None`` when nothing is timed."""
        return next((t.end_ms for t in reversed(self.tokens) if t.end_ms is not None), None)

    @property
    def is_timed(self) -> bool:
        """Whether every token of the line has times."""
        return bool(self.tokens) and all(token.is_timed for token in self.tokens)


class Meta(_Model):
    """Song metadata shown on the title card and written to exported files."""

    title: str = ""
    artist: str = ""
    lyricist: str = ""
    composer: str = ""
    language: str = "zh-TW"
    duration_ms: int = Field(default=0, ge=0)


class Media(_Model):
    """Paths of media files, relative to the project folder (POSIX separators)."""

    source: str | None = None
    audio: str | None = None
    vocals: str | None = None
    instrumental: str | None = None
    has_video: bool = False


class Analysis(_Model):
    """Results of audio analysis that the layout engine and the editor reuse."""

    tempo_bpm: float | None = Field(default=None, gt=0)
    beats_ms: list[int] = Field(default_factory=list[int])
    vocal_regions: list[tuple[int, int]] = Field(default_factory=list[tuple[int, int]])


class Singer(_Model):
    """A singer and the theme colour slot used for their lines."""

    id: str = Field(min_length=1)
    label: str
    theme_slot: str = "male"


class Style(_Model):
    """Which theme to use and per-project overrides of theme values."""

    theme: str = "classic-ktv"
    overrides: dict[str, Any] = Field(default_factory=dict[str, Any])


class Background(_Model):
    """What is shown behind the lyrics."""

    type: BackgroundType = "video"
    color: str | None = None
    image: str | None = None


class Render(_Model):
    """Output video settings."""

    resolution: tuple[int, int] = (1920, 1080)
    fps: float = Field(default=30.0, gt=0, le=240)
    background: Background = Field(default_factory=Background)

    @model_validator(mode="after")
    def _check_resolution(self) -> Render:
        width, height = self.resolution
        if width < 16 or height < 16 or width % 2 or height % 2:
            raise ValueError("resolution must be even numbers of at least 16 pixels")
        return self


def default_singers() -> list[Singer]:
    """The three singers every new project starts with."""
    return [
        Singer(id="m", label="男", theme_slot="male"),
        Singer(id="f", label="女", theme_slot="female"),
        Singer(id="all", label="合", theme_slot="duet"),
    ]


class Project(_Model):
    """The document stored in ``project.json``."""

    schema_version: int = SCHEMA_VERSION
    revision: int = Field(default=0, ge=0)
    meta: Meta = Field(default_factory=Meta)
    media: Media = Field(default_factory=Media)
    analysis: Analysis = Field(default_factory=Analysis)
    singers: list[Singer] = Field(default_factory=default_singers)
    lines: list[Line] = Field(default_factory=list[Line])
    style: Style = Field(default_factory=Style)
    render: Render = Field(default_factory=Render)

    @model_validator(mode="after")
    def _check_references(self) -> Project:
        singer_ids = [singer.id for singer in self.singers]
        if len(set(singer_ids)) != len(singer_ids):
            raise ValueError("singer ids must be unique")
        line_ids = [line.id for line in self.lines]
        if len(set(line_ids)) != len(line_ids):
            raise ValueError("line ids must be unique")
        known = set(singer_ids)
        for line in self.lines:
            if line.singer not in known:
                raise ValueError(f"line {line.id} refers to unknown singer {line.singer!r}")
        return self

    def singer(self, singer_id: str) -> Singer:
        """Look up a singer by id."""
        for singer in self.singers:
            if singer.id == singer_id:
                return singer
        raise KeyError(singer_id)

    def line(self, line_id: str) -> Line:
        """Look up a line by id."""
        for line in self.lines:
            if line.id == line_id:
                return line
        raise KeyError(line_id)

    @property
    def has_lyrics(self) -> bool:
        """Whether the project has at least one token."""
        return any(line.tokens for line in self.lines)

    @property
    def is_aligned(self) -> bool:
        """Whether every token has times."""
        return self.has_lyrics and all(line.is_timed for line in self.lines if line.tokens)
