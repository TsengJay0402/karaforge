"""Forced alignment with Qwen3-ForcedAligner (optional: needs the ``qwen-asr`` package).

Qwen3-ForcedAligner is a 0.6 B-parameter speech language model that reads the audio together
with the text and *predicts a time for every word boundary* in one forward pass: the text is
written as ``word<timestamp><timestamp>word<timestamp><timestamp>…`` and the model fills each
``<timestamp>`` slot with one of 5000 classes, each standing for 80 ms.

Compared with CTC alignment this has two consequences:

* the model sees the whole window and the whole text at once, so a slurred or held syllable
  does not derail the tokens after it;
* time is quantised to 80 ms.  To get below that, the adapter does not take the most probable
  class but the probability-weighted mean of the classes around it (see
  :func:`expected_bin`), which the refinement pass then snaps to the nearest vocal onset.

The model code lives in Alibaba's ``qwen-asr`` package (Apache-2.0), which pins exact versions
of ``transformers`` and friends; it is therefore an optional extra::

    uv sync --extra cpu --extra qwen        # or: pip install "karaforge[qwen]"
"""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np
import numpy.typing as npt

from karaforge.adapters import pool
from karaforge.adapters.base import AdapterInfo, AlignRequest, AlignUnit, UnitTiming
from karaforge.audio.io import MODEL_RATE
from karaforge.device import DeviceChoice, cpu_threads
from karaforge.errors import DependencyMissingError
from karaforge.models import store

MODEL_ID = "qwen3-forced-aligner"
_AUDIO_PREFIX = "<|audio_start|><|audio_pad|><|audio_end|>"
_SLOT = "<timestamp>"
_NEIGHBOURS = 2
"""Classes on each side of the most probable one that enter the weighted mean."""
_MIN_WINDOW_S = 0.3

F64 = npt.NDArray[np.float64]


def expected_bin(probabilities: F64) -> tuple[float, float]:
    """Sub-class position of the peak of a probability distribution, and its mass.

    Args:
        probabilities: Probabilities over the time classes for one timestamp slot.

    Returns:
        ``(position, mass)``: the probability-weighted mean class index over the peak and its
        neighbours, and the share of the total probability that sits there (a confidence).
    """
    peak = int(np.argmax(probabilities))
    low = max(0, peak - _NEIGHBOURS)
    high = min(probabilities.size, peak + _NEIGHBOURS + 1)
    local = probabilities[low:high]
    mass = float(local.sum())
    if mass <= 0.0:
        return float(peak), 0.0
    position = float((local * np.arange(low, high)).sum() / mass)
    return position, min(1.0, mass)


def repair_order(times: list[float]) -> tuple[list[float], list[bool]]:
    """Make a sequence of predicted times non-decreasing.

    The values on the longest non-decreasing subsequence are trusted; every other value is
    replaced by an interpolation between its trusted neighbours.

    Returns:
        The repaired times and, per value, whether it was replaced.
    """
    count = len(times)
    if count == 0:
        return [], []
    length = [1] * count
    parent = [-1] * count
    for index in range(1, count):
        for earlier in range(index):
            if times[earlier] <= times[index] and length[earlier] + 1 > length[index]:
                length[index] = length[earlier] + 1
                parent[index] = earlier
    cursor = max(range(count), key=lambda index: length[index])
    trusted = [False] * count
    while cursor != -1:
        trusted[cursor] = True
        cursor = parent[cursor]

    result = list(times)
    index = 0
    while index < count:
        if trusted[index]:
            index += 1
            continue
        stop = index
        while stop < count and not trusted[stop]:
            stop += 1
        left = result[index - 1] if index > 0 else None
        right = result[stop] if stop < count else None
        for position in range(index, stop):
            if left is not None and right is not None:
                share = (position - index + 1) / (stop - index + 1)
                result[position] = left + (right - left) * share
            elif left is not None:
                result[position] = left
            elif right is not None:
                result[position] = right
        index = stop
    return result, [not flag for flag in trusted]


class QwenAligner:
    """Aligner based on Qwen3-ForcedAligner-0.6B.

    Args:
        model: Registry id of the weights (``default`` = :data:`MODEL_ID`).
        device: Resolved compute device.
    """

    max_window_s: float | None = 170.0
    """The model accepts at most 180 s of audio."""
    weak_score: float = 0.3
    """Below this probability mass the model's answer for a token is a guess."""

    def __init__(self, model: str, device: DeviceChoice) -> None:
        self._model_id = MODEL_ID if model == "default" else model
        self._device = device
        self._info = AdapterInfo(
            name="qwen3-fa",
            version="1",
            license="Apache-2.0",
            languages=("zh", "yue", "en", "ja", "ko", "fr", "de", "es", "pt", "it", "ru"),
            devices=("cpu", "cuda"),
            memory_mb=3200,
            description_zh="Qwen3-ForcedAligner-0.6B:一次前向計算預測每個字的起訖時間(80 ms 量化)",
            description_en="Qwen3-ForcedAligner-0.6B: predicts every word boundary in one pass "
            "(80 ms classes)",
            models=(self._model_id,),
        )

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        return self._info

    def _load(self) -> Any:
        try:
            import torch

            package: Any = importlib.import_module("qwen_asr")
        except ImportError as exc:
            raise DependencyMissingError(
                "缺少 qwen-asr 套件,無法使用 Qwen3 對齊器。",
                "The qwen-asr package is missing; the Qwen3 aligner is unavailable.",
                hint_zh='請執行:uv sync --extra cpu --extra qwen(或 pip install "karaforge[qwen]")',
                hint_en='Run: uv sync --extra cpu --extra qwen (or pip install "karaforge[qwen]")',
                detail=str(exc),
            ) from exc
        directory = store.ensure(self._model_id)
        on_cpu = self._device.kind == "cpu"
        if on_cpu:
            torch.set_num_threads(cpu_threads())
        wrapper: Any = package.Qwen3ForcedAligner.from_pretrained(
            str(directory),
            dtype=torch.float32 if on_cpu else torch.bfloat16,
            device_map="cpu" if on_cpu else "cuda:0",
        )
        wrapper.model.eval()
        return wrapper

    def _words(self, wrapper: Any, units: list[AlignUnit]) -> list[list[str]]:
        """The model's own word tokens for each unit (empty for unpronounceable units)."""
        tokenizer: Any = wrapper.aligner_processor
        return [list(tokenizer.tokenize_space_lang(unit.text)) for unit in units]

    def align(self, request: AlignRequest) -> list[UnitTiming]:
        """Align the units of ``request`` to its audio window."""
        units = list(request.units)
        if not units:
            return []
        duration = request.audio.size / MODEL_RATE
        if duration < _MIN_WINDOW_S:
            return _spread(len(units), duration)
        wrapper: Any = pool.shared(("qwen3-fa", self._model_id, self._device.kind), self._load)
        import torch

        prefix = [
            word for words in self._words(wrapper, list(request.prefix_units)) for word in words
        ]
        suffix = [
            word for words in self._words(wrapper, list(request.suffix_units)) for word in words
        ]
        per_unit = self._words(wrapper, units)
        words = [*prefix, *(word for group in per_unit for word in group), *suffix]
        if not any(per_unit):
            return _spread(len(units), duration)

        text = _AUDIO_PREFIX + (_SLOT * 2).join(words) + _SLOT * 2
        inputs: Any = wrapper.processor(
            text=[text],
            audio=[request.audio.astype(np.float32)],
            return_tensors="pt",
            padding=True,
        )
        inputs = inputs.to(wrapper.model.device).to(wrapper.model.dtype)
        with torch.inference_mode():
            logits: Any = wrapper.model.thinker(**inputs).logits[0]
            slots: Any = inputs["input_ids"][0] == wrapper.timestamp_token_id
            distribution: Any = torch.softmax(logits[slots].float(), dim=-1)
        probabilities = np.asarray(distribution.cpu().numpy(), dtype=np.float64)
        if probabilities.shape[0] != 2 * len(words):
            return _spread(len(units), duration)

        step = float(wrapper.timestamp_segment_time) / 1000.0
        raw: list[float] = []
        masses: list[float] = []
        for row in probabilities:
            position, mass = expected_bin(row)
            raw.append(position * step)
            masses.append(mass)
        times, replaced = repair_order(raw)

        timings: list[UnitTiming] = []
        cursor = len(prefix)
        previous_end = 0.0
        for group in per_unit:
            if not group:
                timings.append(UnitTiming(previous_end, previous_end, 0.0))
                continue
            first, last = cursor, cursor + len(group) - 1
            cursor += len(group)
            start = min(duration, max(0.0, times[2 * first]))
            end = min(duration, max(start, times[2 * last + 1]))
            # The start is what the listener sees; a start that had to be repaired is a guess.
            score = masses[2 * first] * (0.3 if replaced[2 * first] else 1.0)
            timings.append(UnitTiming(start, end, score))
            previous_end = end
        return timings


def _spread(count: int, duration: float) -> list[UnitTiming]:
    """Evenly spaced timings with zero confidence (used when alignment is impossible)."""
    step = duration / count if count else 0.0
    return [UnitTiming(index * step, (index + 1) * step, 0.0) for index in range(count)]
