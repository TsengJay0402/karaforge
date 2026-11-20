"""Processing-quality profiles: which adapter and model each stage uses, and its parameters.

Three profiles are built in (see ``docs/profiles.md``):

``cpu-lite``
    The fastest combination; used by CI and the integration tests.
``balanced``
    The default: a good trade-off between quality and speed on a CPU.
``gpu-quality``
    The best models; practical only with a GPU.

Every value can be overridden per run with dotted keys, e.g. ``align.aligner=whisper-attn``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from karaforge.errors import PipelineError

DevicePreference = Literal["auto", "cpu", "cuda", "mps"]
DEFAULT_PROFILE = "balanced"


class _Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SeparateSettings(_Settings):
    """Vocal / accompaniment separation."""

    adapter: str = "audio-separator"
    model: str = "uvr-mdxnet-kara-2"
    """Registry id of the model.  The default is a karaoke-type model: backing vocals stay
    in the accompaniment and the vocal stem is the clean lead used for alignment."""


class AnalyzeSettings(_Settings):
    """Voice-activity, onset and tempo analysis of the vocal stem."""

    vad: str = "energy"
    onset: str = "spectral-flux"
    vad_min_region_ms: int = Field(default=200, ge=0)
    vad_merge_gap_ms: int = Field(default=300, ge=0)


class AsrSettings(_Settings):
    """Speech recognition used for coarse alignment and for lyric drafts."""

    adapter: str = "faster-whisper"
    model: str = "whisper-small"
    """Registry id of the model."""
    beam_size: int = Field(default=5, ge=1)
    use_lyrics_prompt: bool = True
    """Bias recognition towards the known lyrics (when the project has lyrics)."""


class AlignSettings(_Settings):
    """The three-pass alignment algorithm."""

    aligner: str = "ctc"
    """``ctc``, ``whisper-attn``, ``qwen``, ``hybrid`` or ``auto`` (``hybrid`` when the
    optional Qwen package is installed, otherwise ``ctc``); see docs/alignment.md."""
    model: str = "default"
    """Registry id of the aligner's model; ``default`` picks the adapter's usual one."""
    coarse: Literal["asr", "regions", "global"] = "asr"
    """How lines get their time windows before the fine pass.

    ``asr`` — match a speech-recognition transcript against the lyrics (the normal mode);
    ``regions`` — no transcript: share out the voice-activity regions by token count;
    ``global`` — no windows at all: align the whole song in a single pass (only aligners
    without a window limit).  The last two exist for the benchmark's ablation study.
    """
    window_pad_ms: int = Field(default=1000, ge=0)
    """Audio kept on each side of a line's window for the fine pass."""
    context_tokens: int = Field(default=4, ge=0, le=16)
    """How many tokens of the neighbouring lines are given to the aligner as context when
    their sound may be inside a line's padded window (0 = none)."""
    lead_ms: int | None = Field(default=None, ge=-500, le=500)
    """Constant subtracted from every start the aligner reports, before refinement.

    Aligners have a characteristic bias (CTC models fire a little after a syllable begins).
    ``None`` uses the value calibrated for the selected aligner (its ``lead_ms`` attribute,
    determined on development data, never on test data); a number overrides it.
    """
    onset_snap: bool = True
    onset_snap_ms: int = Field(default=60, ge=0)
    """Maximum distance a token start may move to reach an onset."""
    weak_score: float | None = Field(default=None, ge=0.0, le=1.0)
    """Aligner score below which a token counts as placed without evidence; such a token is
    moved to the strongest unclaimed onset between its neighbours.  ``None`` uses the
    aligner's own threshold (its ``weak_score`` attribute, chosen on development data);
    0 disables the rule."""
    min_token_ms: int = Field(default=60, ge=1)
    pause_threshold_ms: int = Field(default=300, ge=0)
    """A gap longer than this ends the previous token at the vocal energy drop."""
    long_note: bool = True
    """Extend the last token of a line until the vocal energy fades."""
    max_tail_ms: int = Field(default=6000, ge=0)
    """Upper bound for how far a line-final token may be extended."""


class Profile(_Settings):
    """A complete set of processing settings."""

    name: str
    device: DevicePreference = "auto"
    separate: SeparateSettings = Field(default_factory=SeparateSettings)
    analyze: AnalyzeSettings = Field(default_factory=AnalyzeSettings)
    asr: AsrSettings = Field(default_factory=AsrSettings)
    align: AlignSettings = Field(default_factory=AlignSettings)

    def with_overrides(self, overrides: dict[str, Any]) -> Profile:
        """Return a copy with dotted-key overrides applied (``{"align.aligner": "x"}``).

        Raises:
            PipelineError: If a key does not name an existing setting or the value is invalid.
        """
        data = self.model_dump()
        for dotted, value in overrides.items():
            target: dict[str, Any] = data
            parts = dotted.split(".")
            for part in parts[:-1]:
                child = target.get(part)
                if not isinstance(child, dict):
                    raise _unknown_setting(dotted)
                target = child  # pyright: ignore[reportUnknownVariableType]
            if parts[-1] not in target:
                raise _unknown_setting(dotted)
            target[parts[-1]] = value
        try:
            return Profile.model_validate(data)
        except ValueError as exc:
            raise PipelineError(
                "處理設定的值不正確。",
                "Invalid value for a processing setting.",
                detail=str(exc),
            ) from exc


def _unknown_setting(key: str) -> PipelineError:
    return PipelineError(
        f"沒有這個處理設定:{key}",
        f"Unknown processing setting: {key}",
        hint_zh="可用的設定見 docs/profiles.md,格式為 區段.名稱=值,例如 align.onset_snap_ms=80。",
        hint_en="See docs/profiles.md; the format is section.name=value, "
        "e.g. align.onset_snap_ms=80.",
    )


def _builtin() -> dict[str, Profile]:
    return {
        # Smallest download and fastest: the aligner reuses the recogniser's Whisper model.
        "cpu-lite": Profile(
            name="cpu-lite",
            asr=AsrSettings(model="whisper-base", beam_size=2),
            align=AlignSettings(aligner="whisper-attn"),
        ),
        # The default: CTC alignment, permissively licensed models only, no optional package.
        "balanced": Profile(name="balanced"),
        # Best recogniser, and the hybrid CTC + Qwen aligner when its package is installed.
        "gpu-quality": Profile(
            name="gpu-quality",
            asr=AsrSettings(model="whisper-large-v3-turbo"),
            align=AlignSettings(aligner="auto"),
        ),
    }


def profile_names() -> list[str]:
    """Names of the built-in profiles."""
    return list(_builtin())


def get_profile(name: str = DEFAULT_PROFILE) -> Profile:
    """Return a fresh copy of a built-in profile.

    Raises:
        PipelineError: If there is no profile with that name.
    """
    profiles = _builtin()
    if name not in profiles:
        raise PipelineError(
            f"沒有這個處理品質設定檔:{name}",
            f"Unknown profile: {name}",
            hint_zh=f"可用的設定檔:{'、'.join(profiles)}",
            hint_en=f"Available profiles: {', '.join(profiles)}",
        )
    return profiles[name]


def parse_overrides(items: list[str]) -> dict[str, Any]:
    """Parse ``key=value`` strings from the command line into an overrides mapping.

    Values are interpreted as booleans, integers or floats when they look like one.
    """
    overrides: dict[str, Any] = {}
    for item in items:
        key, separator, raw = item.partition("=")
        if not separator or not key.strip():
            raise PipelineError(
                f"設定的格式不正確:{item}",
                f"Malformed setting: {item}",
                hint_zh="格式為 區段.名稱=值,例如 align.aligner=ctc。",
                hint_en="Use section.name=value, e.g. align.aligner=ctc.",
            )
        overrides[key.strip()] = _parse_value(raw.strip())
    return overrides


def _parse_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    for convert in (int, float):
        try:
            return convert(raw)
        except ValueError:
            continue
    return raw
