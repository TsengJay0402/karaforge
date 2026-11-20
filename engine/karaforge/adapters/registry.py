"""Creates adapters from profile settings.

Imports of the heavy model libraries happen lazily inside each adapter, so listing or
describing adapters stays cheap.
"""

from __future__ import annotations

from karaforge.adapters.base import AdapterInfo, Aligner, Separator, Transcriber
from karaforge.device import DeviceChoice, resolve_device
from karaforge.errors import PipelineError
from karaforge.pipeline.profiles import AlignSettings, AsrSettings, Profile, SeparateSettings

SEPARATORS = ("audio-separator",)
TRANSCRIBERS = ("faster-whisper",)
ALIGNERS = ("whisper-attn", "ctc", "ctc-mms", "qwen", "hybrid", "auto")
"""``auto`` means ``hybrid`` when the optional Qwen package is installed, else ``ctc``;
``ctc-mms`` is the CTC aligner with the single multilingual MMS model (CC-BY-NC)."""


def _unknown(kind_zh: str, kind_en: str, name: str, options: tuple[str, ...]) -> PipelineError:
    return PipelineError(
        f"沒有這個{kind_zh}:{name}",
        f"Unknown {kind_en}: {name}",
        hint_zh=f"可用的選項:{'、'.join(options)}",
        hint_en=f"Available: {', '.join(options)}",
    )


def create_separator(settings: SeparateSettings, device: DeviceChoice) -> Separator:
    """Instantiate the separator selected by ``settings``."""
    if settings.adapter == "audio-separator":
        from karaforge.adapters.separators.uvr import UvrSeparator

        return UvrSeparator(settings.model, device)
    raise _unknown("分離器", "separator", settings.adapter, SEPARATORS)


def create_transcriber(settings: AsrSettings, device: DeviceChoice) -> Transcriber:
    """Instantiate the speech recogniser selected by ``settings``."""
    if settings.adapter == "faster-whisper":
        from karaforge.adapters.asr.faster_whisper import FasterWhisperTranscriber

        return FasterWhisperTranscriber(settings.model, device, settings.beam_size)
    raise _unknown("語音辨識器", "speech recogniser", settings.adapter, TRANSCRIBERS)


def qwen_available() -> bool:
    """Whether the optional ``qwen-asr`` package can be imported."""
    import importlib.util

    return importlib.util.find_spec("qwen_asr") is not None


def resolve_aligner(name: str) -> str:
    """Turn ``auto`` into a concrete aligner name."""
    if name != "auto":
        return name
    return "hybrid" if qwen_available() else "ctc"


def aligner_model(settings: AlignSettings, asr: AsrSettings) -> str:
    """Resolve ``align.model = "default"`` to a concrete registry id."""
    if settings.model != "default":
        return settings.model
    if resolve_aligner(settings.aligner) == "whisper-attn":
        return asr.model
    return "default"


def create_aligner(settings: AlignSettings, asr: AsrSettings, device: DeviceChoice) -> Aligner:
    """Instantiate the forced aligner selected by ``settings``."""
    name = resolve_aligner(settings.aligner)
    if name == "whisper-attn":
        from karaforge.adapters.aligners.whisper_attention import WhisperAttentionAligner

        return WhisperAttentionAligner(aligner_model(settings, asr), device)
    if name == "ctc":
        from karaforge.adapters.aligners.ctc import CtcAligner

        return CtcAligner(aligner_model(settings, asr), device)
    if name == "ctc-mms":
        from karaforge.adapters.aligners.ctc import CtcAligner

        return CtcAligner("mms-fa", device)
    if name == "qwen":
        from karaforge.adapters.aligners.qwen import QwenAligner

        return QwenAligner(aligner_model(settings, asr), device)
    if name == "hybrid":
        from karaforge.adapters.aligners.hybrid import HybridAligner

        return HybridAligner(device)
    raise _unknown("對齊器", "aligner", settings.aligner, ALIGNERS)


def describe_profile(profile: Profile) -> list[AdapterInfo]:
    """Adapter descriptions for everything a profile uses (no model is loaded)."""
    device = resolve_device(profile.device)
    return [
        create_separator(profile.separate, device).info,
        create_transcriber(profile.asr, device).info,
        create_aligner(profile.align, profile.asr, device).info,
    ]


def profile_model_ids(profile: Profile) -> list[str]:
    """Registry ids of every model a profile needs, including required companions."""
    from karaforge.models.registry import get_model

    ordered: list[str] = []

    def add(model_id: str) -> None:
        for dependency in get_model(model_id).requires:
            add(dependency)
        if model_id not in ordered:
            ordered.append(model_id)

    for info in describe_profile(profile):
        for model_id in info.models:
            add(model_id)
    return ordered
