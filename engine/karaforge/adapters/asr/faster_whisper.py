"""Speech recognition with `faster-whisper <https://github.com/SYSTRAN/faster-whisper>`_."""

from __future__ import annotations

from typing import Any

from karaforge.adapters import pool
from karaforge.adapters.base import AdapterInfo, AsrSegment, AsrWord, Transcript
from karaforge.audio.io import MODEL_RATE, FloatArray
from karaforge.device import DeviceChoice, cpu_threads
from karaforge.errors import DependencyMissingError
from karaforge.models import store
from karaforge.models.registry import get_model
from karaforge.runtime import CancelToken, ProgressFn

_MEMORY_MB = {
    "whisper-tiny": 400,
    "whisper-base": 500,
    "whisper-small": 1000,
    "whisper-medium": 2600,
    "whisper-large-v3-turbo": 2800,
}


def whisper_language(language: str | None) -> str | None:
    """Map a project language such as ``zh-TW`` to Whisper's two-letter code."""
    if not language:
        return None
    prefix = language.split("-")[0].lower()
    return {"cmn": "zh", "yue": "yue", "mixed": "zh"}.get(prefix, prefix)


def load_whisper(model_id: str, device: DeviceChoice) -> Any:
    """Load (or reuse) a CTranslate2 Whisper model.

    The same instance is shared between the transcriber and the attention aligner.
    """
    directory = store.ensure(model_id)

    def create() -> Any:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise DependencyMissingError(
                "缺少 faster-whisper 套件，無法做語音辨識。",
                "The faster-whisper package is missing; speech recognition is unavailable.",
                hint_zh="請執行：uv sync --extra cpu",
                hint_en="Run: uv sync --extra cpu",
                detail=str(exc),
            ) from exc
        on_gpu = device.kind == "cuda"
        return WhisperModel(
            str(directory),
            device="cuda" if on_gpu else "cpu",
            compute_type="float16" if on_gpu else "int8",
            cpu_threads=cpu_threads(),
            local_files_only=True,
        )

    # CTranslate2 has no MPS backend: Apple GPUs fall back to the CPU for this model.
    return pool.shared(
        ("faster-whisper", model_id, "cuda" if device.kind == "cuda" else "cpu"), create
    )


class FasterWhisperTranscriber:
    """Whisper speech recognition with word-level timestamps.

    Args:
        model_id: Registry id, e.g. ``whisper-small``.
        device: Resolved compute device.
        beam_size: Beam width for decoding.
    """

    def __init__(self, model_id: str, device: DeviceChoice, beam_size: int = 5) -> None:
        spec = get_model(model_id)
        self._model_id = model_id
        self._device = device
        self._beam_size = beam_size
        self._info = AdapterInfo(
            name="faster-whisper",
            version=f"2+{model_id}",
            license=spec.license,
            languages=("*",),
            devices=("cpu", "cuda"),
            memory_mb=_MEMORY_MB.get(model_id, 1500),
            description_zh=f"Whisper 語音辨識（{spec.title}）",
            description_en=f"Whisper speech recognition ({spec.title})",
            models=(model_id,),
        )

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        return self._info

    def transcribe(
        self,
        audio: FloatArray,
        *,
        language: str | None,
        prompt: str | None,
        progress: ProgressFn,
        cancel: CancelToken,
    ) -> Transcript:
        """Transcribe 16 kHz mono audio; ``prompt`` (the known lyrics) biases every window.

        Without a prompt the transcript is going to be the lyric draft, and Whisper's
        "no speech" gate is switched off: the gate was made for talk, takes sustained singing
        for silence and drops whole 30-second windows of a song.  What is recognised where
        nobody sings is removed afterwards, with the voice-activity regions
        (:mod:`karaforge.align.draft`).
        """
        model = load_whisper(self._model_id, self._device)
        duration = max(1e-3, audio.size / MODEL_RATE)
        options: dict[str, Any] = {} if prompt else {"no_speech_threshold": None}
        segments, info = model.transcribe(
            audio,
            language=whisper_language(language),
            beam_size=self._beam_size,
            word_timestamps=True,
            condition_on_previous_text=False,
            vad_filter=False,
            hotwords=prompt or None,
            **options,
        )
        collected: list[AsrSegment] = []
        for segment in segments:
            cancel.raise_if_cancelled()
            raw_words: list[Any] = list(segment.words or ())
            words = tuple(
                AsrWord(
                    text=str(word.word).strip(),
                    start_s=float(word.start),
                    end_s=float(word.end),
                    probability=float(word.probability),
                )
                for word in raw_words
                if str(word.word).strip()
            )
            collected.append(
                AsrSegment(
                    text=str(segment.text).strip(),
                    start_s=float(segment.start),
                    end_s=float(segment.end),
                    words=words,
                )
            )
            progress(min(1.0, float(segment.end) / duration), "語音辨識 / transcribing")
        progress(1.0, "語音辨識 / transcribing")
        return Transcript(language=str(info.language), segments=tuple(collected))
