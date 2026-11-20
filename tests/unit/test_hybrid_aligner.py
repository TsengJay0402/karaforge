"""The hybrid aligner's merging rules, with scripted stand-ins for both aligners."""

from __future__ import annotations

import numpy as np
import pytest

from karaforge.adapters import registry
from karaforge.adapters.aligners.hybrid import HybridAligner, merge
from karaforge.adapters.base import AdapterInfo, AlignRequest, AlignUnit, UnitTiming
from karaforge.audio.io import FloatArray
from karaforge.device import DeviceChoice
from karaforge.pipeline.profiles import get_profile
from karaforge.text.tokenize import TokenKind

CPU = DeviceChoice(kind="cpu", name="test cpu")
HAN, WORD = TokenKind.HAN, TokenKind.WORD


class Scripted:
    """An aligner that returns prepared answers and counts how often it is asked."""

    def __init__(self, name: str, answers: list[UnitTiming], limit: float | None = None) -> None:
        self.answers = answers
        self.calls = 0
        self.prepared: list[int] = []
        self.max_window_s = limit
        self._info = AdapterInfo(
            name=name,
            version="t",
            license="Apache-2.0",
            languages=("zh", "en"),
            devices=("cpu", "cuda"),
            memory_mb=100,
            models=(f"{name}-model",),
        )

    @property
    def info(self) -> AdapterInfo:
        return self._info

    def prepare(self, audio: FloatArray) -> None:
        self.prepared.append(int(audio.size))

    def align(self, request: AlignRequest) -> list[UnitTiming]:
        self.calls += 1
        return self.answers[: len(request.units)]


def request(*units: tuple[str, TokenKind]) -> AlignRequest:
    return AlignRequest(
        audio=np.zeros(16000, dtype=np.float32),
        units=[AlignUnit(text=text, kind=kind) for text, kind in units],
        language="zh-TW",
    )


def t(start: float, score: float) -> UnitTiming:
    return UnitTiming(start, start + 0.2, score)


def test_chinese_characters_come_from_ctc_and_words_from_qwen() -> None:
    merged = merge([HAN, WORD], [t(1.0, 0.9), t(2.0, 0.9)], [t(1.5, 0.9), t(2.6, 0.9)])
    assert [timing.start_s for timing in merged] == [1.0, 2.6]
    assert [timing.score for timing in merged] == [0.9, 0.9]


def test_each_aligner_backs_the_other_up() -> None:
    # A character CTC did not hear: Qwen's confident answer is used …
    assert merge([HAN], [t(1.0, 0.1)], [t(1.5, 0.8)])[0].start_s == 1.5
    # … but not an unsure one.
    assert merge([HAN], [t(1.0, 0.1)], [t(1.5, 0.4)])[0].start_s == 1.0
    # A word Qwen is unsure about falls back to CTC, whatever CTC's own score.
    assert merge([WORD], [t(2.0, 0.2)], [t(2.6, 0.3)])[0].start_s == 2.0
    assert merge([WORD], [t(2.0, 0.2)], [t(2.6, 0.5)])[0].start_s == 2.6


def test_agreement_raises_the_score() -> None:
    agreeing = merge([HAN], [t(1.00, 0.6)], [t(1.05, 0.7)])[0]
    assert agreeing.start_s == 1.00
    assert agreeing.score == pytest.approx(0.9)  # max(0.6, 0.7) + 0.2
    assert merge([WORD], [t(1.0, 0.95)], [t(1.02, 0.95)])[0].score == 1.0
    apart = merge([HAN], [t(1.0, 0.6)], [t(1.5, 0.7)])[0]
    assert apart.score == 0.6


def test_qwen_is_only_asked_when_it_can_matter() -> None:
    ctc = Scripted("ctc", [t(1.0, 0.9), t(1.4, 0.8)])
    qwen = Scripted("qwen3-fa", [t(1.1, 0.9), t(1.5, 0.9)])
    hybrid = HybridAligner(CPU, ctc=ctc, qwen=qwen)
    # A Chinese line that CTC heard clearly: Qwen is not run at all.
    assert hybrid.align(request(("你", HAN), ("好", HAN))) == ctc.answers
    assert (ctc.calls, qwen.calls) == (1, 0)
    # A word in the line: Qwen is needed.
    mixed = hybrid.align(request(("你", HAN), ("hello", WORD)))
    assert [timing.start_s for timing in mixed] == [1.0, 1.5]
    assert qwen.calls == 1
    # A character without CTC evidence: Qwen is needed too.
    ctc.answers = [t(1.0, 0.9), t(1.4, 0.1)]
    weak = hybrid.align(request(("你", HAN), ("好", HAN)))
    assert [timing.start_s for timing in weak] == [1.0, 1.5]
    assert qwen.calls == 2
    assert hybrid.align(request()) == []


def test_info_and_limits_combine_both_aligners() -> None:
    ctc = Scripted("ctc", [])
    qwen = Scripted("qwen3-fa", [], limit=170.0)
    hybrid = HybridAligner(CPU, ctc=ctc, qwen=qwen)
    info = hybrid.info
    assert info.name == "hybrid"
    assert info.version == "1+ctc@t+qwen3-fa@t"
    assert info.models == ("ctc-model", "qwen3-fa-model")
    assert info.memory_mb == 200 and info.license == "Apache-2.0"
    assert hybrid.max_window_s == 170.0
    hybrid.prepare(np.zeros(32000, dtype=np.float32))
    assert ctc.prepared == [32000] and qwen.prepared == [32000]
    assert HybridAligner(CPU, ctc=ctc, qwen=Scripted("q", [])).max_window_s is None


def test_auto_picks_hybrid_only_when_the_qwen_package_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "qwen_available", lambda: False)
    assert registry.resolve_aligner("auto") == "ctc"
    assert registry.resolve_aligner("whisper-attn") == "whisper-attn"
    profile = get_profile("balanced").with_overrides({"align.aligner": "auto"})
    assert registry.create_aligner(profile.align, profile.asr, CPU).info.name == "ctc"
    monkeypatch.setattr(registry, "qwen_available", lambda: True)
    assert registry.resolve_aligner("auto") == "hybrid"
    aligner = registry.create_aligner(profile.align, profile.asr, CPU)
    assert aligner.info.name == "hybrid"
    assert aligner.info.models == ("wav2vec2-zh", "wav2vec2-en", "qwen3-forced-aligner")
