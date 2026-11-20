"""Two aligners combined: CTC for Chinese characters, Qwen3 for everything else.

On the benchmark's development songs the two aligners fail in different places:

* The CTC models place **Chinese characters** very reliably (one syllable, one probability
  spike) but are late on English words, whose letters fire well after the word begins, and
  the English model babbles letters over held Chinese vowels in mixed lines.
* Qwen3-ForcedAligner is precise on **words** when it is confident, and it says so: tokens
  with a low score are wrong two times out of three, tokens with a high one almost never.

So each token takes its time from the aligner that is better at its kind, and falls back to
the other one when the preferred aligner had no evidence:

==================  =========================  =======================================
token               normally                   unless
==================  =========================  =======================================
Chinese character   CTC                        CTC heard nothing and Qwen is confident
anything else       Qwen                       Qwen is unsure
==================  =========================  =======================================

Qwen is only run for lines that need it (a non-Chinese token, or a character without CTC
evidence), so a purely Chinese song costs little more than CTC alone.
"""

from __future__ import annotations

from karaforge.adapters.aligners.ctc import CtcAligner
from karaforge.adapters.aligners.qwen import QwenAligner
from karaforge.adapters.base import AdapterInfo, Aligner, AlignRequest, UnitTiming
from karaforge.audio.io import FloatArray
from karaforge.device import DeviceChoice
from karaforge.text.tokenize import TokenKind

CTC_WEAK = 0.3
"""CTC evidence below which a Chinese character counts as not heard."""
QWEN_SURE = 0.5
"""Qwen score from which its answer is preferred for words (and accepted for characters)."""
AGREE_S = 0.08
"""Two answers this close confirm each other."""


def merge(
    kinds: list[TokenKind], ctc: list[UnitTiming], qwen: list[UnitTiming]
) -> list[UnitTiming]:
    """Choose, per unit, between the CTC and the Qwen answer (see the module description).

    The score of the chosen answer is raised when the other aligner independently put the
    unit in the same place.
    """
    result: list[UnitTiming] = []
    for kind, by_ctc, by_qwen in zip(kinds, ctc, qwen, strict=True):
        if kind is TokenKind.HAN:
            use_qwen = by_ctc.score < CTC_WEAK and by_qwen.score >= QWEN_SURE
        else:
            use_qwen = by_qwen.score >= QWEN_SURE
        chosen = by_qwen if use_qwen else by_ctc
        score = chosen.score
        if abs(by_ctc.start_s - by_qwen.start_s) <= AGREE_S:
            score = min(1.0, max(by_ctc.score, by_qwen.score) + 0.2)
        result.append(UnitTiming(chosen.start_s, chosen.end_s, score))
    return result


class HybridAligner:
    """CTC and Qwen3-ForcedAligner, each used for what it does best.

    Args:
        device: Resolved compute device.
        ctc: The CTC aligner (created with the default models when omitted).
        qwen: The Qwen aligner (created when omitted).
    """

    weak_score: float = 0.3

    def __init__(
        self,
        device: DeviceChoice,
        ctc: Aligner | None = None,
        qwen: Aligner | None = None,
    ) -> None:
        self._ctc: Aligner = ctc or CtcAligner("default", device)
        self._qwen: Aligner = qwen or QwenAligner("default", device)
        first, second = self._ctc.info, self._qwen.info
        self._info = AdapterInfo(
            name="hybrid",
            version=f"1+{first.tag}+{second.tag}",
            license=" / ".join(sorted({first.license, second.license})),
            languages=tuple(sorted(set(first.languages) | set(second.languages))),
            devices=tuple(kind for kind in first.devices if kind in second.devices),
            memory_mb=first.memory_mb + second.memory_mb,
            description_zh="CTC(中文字)與 Qwen3-ForcedAligner(其餘)互補,並互為備援",
            description_en="CTC for Chinese characters and Qwen3-ForcedAligner for the rest, "
            "each backing the other up",
            models=(*first.models, *second.models),
        )

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        return self._info

    @property
    def max_window_s(self) -> float | None:
        """The shorter of the two aligners' window limits."""
        limits = [
            float(limit)
            for limit in (
                getattr(self._ctc, "max_window_s", None),
                getattr(self._qwen, "max_window_s", None),
            )
            if limit is not None
        ]
        return min(limits) if limits else None

    def prepare(self, audio: FloatArray) -> None:
        """Pass the whole stem on to the aligners that can use it."""
        for aligner in (self._ctc, self._qwen):
            prepare = getattr(aligner, "prepare", None)
            if callable(prepare):
                prepare(audio)

    def align(self, request: AlignRequest) -> list[UnitTiming]:
        """Align with CTC, add Qwen where it can make a difference, and merge."""
        units = list(request.units)
        if not units:
            return []
        by_ctc = self._ctc.align(request)
        needed = any(
            unit.kind is not TokenKind.HAN or timing.score < CTC_WEAK
            for unit, timing in zip(units, by_ctc, strict=True)
        )
        if not needed:
            return by_ctc
        by_qwen = self._qwen.align(request)
        return merge([unit.kind for unit in units], by_ctc, by_qwen)
