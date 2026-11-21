"""Separation with UVR models through the ``audio-separator`` package."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from karaforge.adapters import pool
from karaforge.adapters.base import AdapterInfo, SeparationResult
from karaforge.audio.io import FloatArray, read_wav, resample, write_wav
from karaforge.device import DeviceChoice
from karaforge.errors import DependencyMissingError, PipelineError
from karaforge.models import store
from karaforge.models.registry import get_model
from karaforge.runtime import CancelToken, ProgressFn
from karaforge.tools import ffmpeg

_MODEL_RATE = 44100
_CHUNK_S = 30.0
_OVERLAP_S = 3.0


def _ensure_ffmpeg_on_path() -> None:
    """``audio-separator`` refuses to start unless ``ffmpeg`` is on ``PATH``."""
    if shutil.which("ffmpeg") is None:
        tools = ffmpeg.find_tools()
        directory = str(Path(tools.ffmpeg).parent)
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")


class UvrSeparator:
    """Runs a UVR separation model (MDX-Net, VR, Roformer, Demucs) on overlapping chunks.

    The input is processed in 30-second chunks that overlap by three seconds and are
    cross-faded, which bounds memory use for long files and gives regular points at which
    progress is reported and cancellation is honoured.

    Args:
        model_id: Registry id of the model, e.g. ``uvr-mdxnet-kara-2``.
        device: Resolved compute device.
    """

    def __init__(self, model_id: str, device: DeviceChoice) -> None:
        self._spec = get_model(model_id)
        self._device = device
        self._info = AdapterInfo(
            name="audio-separator",
            version=f"1+{model_id}",
            license=self._spec.license,
            languages=("*",),
            devices=("cpu", "cuda", "mps"),
            memory_mb=2500,
            description_zh=f"UVR 分離模型：{self._spec.title}",
            description_en=f"UVR separation model: {self._spec.title}",
            models=(model_id,),
        )

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        return self._info

    def _load(self, work_dir: Path) -> Any:
        directory = store.ensure(self._spec.id)
        filename = self._spec.files[0].path

        def create() -> Any:
            try:
                from audio_separator.separator import Separator
            except ImportError as exc:
                raise DependencyMissingError(
                    "缺少 audio-separator 套件，無法分離人聲。",
                    "The audio-separator package is missing; vocals cannot be separated.",
                    hint_zh="請執行：uv sync --extra cpu",
                    hint_en="Run: uv sync --extra cpu",
                    detail=str(exc),
                ) from exc
            _ensure_ffmpeg_on_path()
            separator = Separator(
                log_level=logging.ERROR,
                model_file_dir=str(directory),
                output_dir=str(work_dir),
                output_format="WAV",
                output_single_stem="Vocals",
                sample_rate=_MODEL_RATE,
                use_soundfile=True,
            )
            separator.load_model(model_filename=filename)
            return separator

        separator = pool.shared(("audio-separator", self._spec.id, self._device.kind), create)
        separator.output_dir = str(work_dir)
        instance = getattr(separator, "model_instance", None)
        if instance is not None:
            instance.output_dir = str(work_dir)
        return separator

    def separate(
        self,
        audio: Path,
        out_dir: Path,
        *,
        progress: ProgressFn,
        cancel: CancelToken,
    ) -> SeparationResult:
        """Separate ``audio`` into ``vocals.wav`` and ``instrumental.wav`` inside ``out_dir``."""
        work_dir = out_dir / "chunks"
        work_dir.mkdir(parents=True, exist_ok=True)
        progress(0.0, "載入分離模型 / loading separation model")
        separator = self._load(work_dir)

        mix, rate = read_wav(audio)
        total = mix.shape[0]
        overlap = round(_OVERLAP_S * rate)
        spans = chunk_spans(total, round(_CHUNK_S * rate), overlap)
        vocals = np.zeros_like(mix)
        weight = np.zeros(total, dtype=np.float32)

        for index, (start, end) in enumerate(spans):
            cancel.raise_if_cancelled()
            piece_path = work_dir / f"chunk{index:04d}.wav"
            write_wav(piece_path, mix[start:end], rate)
            stem = self._separate_chunk(separator, piece_path, work_dir, index)
            stem = _fit(resample(stem, _MODEL_RATE, rate), end - start, mix.shape[1])
            window = _crossfade_window(end - start, overlap, first=index == 0, last=end == total)
            vocals[start:end] += stem * window[:, np.newaxis]
            weight[start:end] += window
            piece_path.unlink(missing_ok=True)
            progress((index + 1) / len(spans), "分離人聲 / separating vocals")

        vocals /= np.maximum(weight, 1e-6)[:, np.newaxis]
        instrumental = mix - vocals
        vocals_path = out_dir / "vocals.wav"
        instrumental_path = out_dir / "instrumental.wav"
        write_wav(vocals_path, vocals, rate)
        write_wav(instrumental_path, instrumental, rate)
        shutil.rmtree(work_dir, ignore_errors=True)
        return SeparationResult(vocals=vocals_path, instrumental=instrumental_path)

    def _separate_chunk(
        self, separator: Any, piece: Path, work_dir: Path, index: int
    ) -> FloatArray:
        names = {"Vocals": f"vocals{index:04d}", "Instrumental": f"inst{index:04d}"}
        try:
            outputs: list[str] = list(separator.separate(str(piece), custom_output_names=names))
        except Exception as exc:
            raise PipelineError(
                "人聲分離失敗。",
                "Vocal separation failed.",
                hint_zh="如果是記憶體不足，請關閉其他程式，或改用 cpu-lite 設定檔。",
                hint_en="If this is an out-of-memory error, close other programs or use "
                "the cpu-lite profile.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        vocal_file: Path | None = None
        for output in outputs:
            path = Path(output) if Path(output).is_absolute() else work_dir / output
            if path.stem.startswith("vocals"):
                vocal_file = path
            else:
                path.unlink(missing_ok=True)
        if vocal_file is None or not vocal_file.is_file():
            raise PipelineError(
                "分離模型沒有輸出人聲軌。",
                "The separation model did not produce a vocal stem.",
                detail=f"outputs: {outputs}",
            )
        stem, _rate = read_wav(vocal_file)
        vocal_file.unlink(missing_ok=True)
        return stem


def chunk_spans(total: int, chunk: int, overlap: int) -> list[tuple[int, int]]:
    """Split ``total`` frames into ``(start, end)`` spans that overlap by ``overlap`` frames.

    Consecutive spans start ``chunk`` frames apart.  A final span that would be shorter than
    a third of a chunk is merged into the one before it, because separation models do
    noticeably worse on very short inputs.
    """
    if total <= 0:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    while start < total:
        end = min(total, start + chunk + overlap)
        if total - end < chunk // 3:
            end = total
        spans.append((start, end))
        if end == total:
            break
        start += chunk
    return spans


def _fit(audio: FloatArray, length: int, channels: int) -> FloatArray:
    """Pad or trim ``audio`` to exactly ``length`` frames and ``channels`` channels."""
    if audio.shape[1] != channels:
        mono = audio.mean(axis=1, keepdims=True)
        audio = np.repeat(mono, channels, axis=1)
    if audio.shape[0] >= length:
        return np.asarray(audio[:length], dtype=np.float32)
    padding = np.zeros((length - audio.shape[0], channels), dtype=np.float32)
    return np.concatenate([audio, padding], axis=0)


def _crossfade_window(length: int, overlap: int, *, first: bool, last: bool) -> FloatArray:
    """Weights for overlap-adding a chunk: linear ramps over the overlapped ends."""
    window = np.ones(length, dtype=np.float32)
    ramp = min(overlap, length)
    if ramp > 1:
        if not first:
            window[:ramp] = np.linspace(0.0, 1.0, ramp, dtype=np.float32)
        if not last:
            window[-ramp:] = np.minimum(
                window[-ramp:], np.linspace(1.0, 0.0, ramp, dtype=np.float32)
            )
    return window
