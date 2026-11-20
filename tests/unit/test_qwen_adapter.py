"""The Qwen aligner adapter, driven by a stand-in for the model.

The real model is 1.8 GB and needs an optional package, so these tests replace the loaded
wrapper with a small object that has the same surface (tokeniser, processor, a ``thinker``
that returns logits).  What is tested is the adapter's own logic: building the text with
timestamp slots, mapping words back to units, sub-class interpolation, order repair and the
handling of context units.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
import torch

from karaforge.adapters import pool
from karaforge.adapters.aligners import qwen
from karaforge.adapters.aligners.qwen import MODEL_ID, QwenAligner
from karaforge.adapters.base import AlignRequest, AlignUnit
from karaforge.device import DeviceChoice
from karaforge.errors import DependencyMissingError
from karaforge.text.tokenize import TokenKind

SLOT_ID = 7
CLASSES = 200
CPU = DeviceChoice(kind="cpu", name="test cpu")


class _Inputs(dict[str, Any]):
    def to(self, _target: object) -> _Inputs:
        return self


class _Tokenizer:
    def tokenize_space_lang(self, text: str) -> list[str]:
        """Like the real one: Chinese characters apart, other letters kept together."""
        words: list[str] = []
        buffer = ""
        for char in text:
            if "一" <= char <= "鿿":
                if buffer:
                    words.append(buffer)
                    buffer = ""
                words.append(char)
            elif char.isalnum() or char == "'":
                buffer += char
        if buffer:
            words.append(buffer)
        return words


class FakeWrapper:
    """Answers every timestamp slot with the classes queued in ``answers``."""

    timestamp_token_id = SLOT_ID
    timestamp_segment_time = 80.0

    def __init__(self, answers: list[dict[int, float]]) -> None:
        self.answers = answers
        self.texts: list[str] = []
        self.aligner_processor = _Tokenizer()
        self.model = self
        self.device = torch.device("cpu")
        self.dtype = torch.float32

    def processor(self, *, text: list[str], audio: list[Any], **_: Any) -> _Inputs:
        self.texts.append(text[0])
        slots = text[0].count("<timestamp>")
        ids = torch.tensor([[1, 2, 3, *([SLOT_ID] * slots)]])
        assert len(audio) == 1 and audio[0].dtype == np.float32
        return _Inputs(input_ids=ids)

    def thinker(self, *, input_ids: torch.Tensor) -> Any:
        length = int(input_ids.shape[1])
        logits = torch.full((1, length, CLASSES), -30.0)
        for slot, answer in enumerate(self.answers):
            for index, probability in answer.items():
                logits[0, 3 + slot, index] = float(np.log(probability))
        return type("Output", (), {"logits": logits})()


@pytest.fixture
def install() -> Iterator[Any]:
    """Put a fake wrapper where the adapter looks for the loaded model."""
    pool.release_all()

    def put(answers: list[dict[int, float]]) -> FakeWrapper:
        wrapper = FakeWrapper(answers)
        pool.shared(("qwen3-fa", MODEL_ID, "cpu"), lambda: wrapper)
        return wrapper

    yield put
    pool.release_all()


def han(text: str) -> AlignUnit:
    return AlignUnit(text=text, kind=TokenKind.HAN)


def word(text: str) -> AlignUnit:
    return AlignUnit(text=text, kind=TokenKind.WORD)


def request(units: list[AlignUnit], seconds: float = 4.0, **extra: Any) -> AlignRequest:
    audio = np.zeros(round(seconds * 16000), dtype=np.float32)
    return AlignRequest(audio=audio, units=units, language="zh-TW", **extra)


def test_info_describes_an_apache_licensed_optional_aligner() -> None:
    info = QwenAligner("default", CPU).info
    assert info.tag == "qwen3-fa@1"
    assert info.license == "Apache-2.0"
    assert info.models == (MODEL_ID,)
    assert info.supports_language("zh-TW") and info.supports_language("en")
    assert not info.supports_language("th")


def test_units_get_the_times_of_their_slots(install: Any) -> None:
    # Slots are (start, end) per word: 你 0.8–1.2 s, 好 1.2–1.6 s, world 2.0–2.8 s.
    wrapper = install([{10: 1.0}, {15: 1.0}, {15: 1.0}, {20: 1.0}, {25: 1.0}, {35: 1.0}])
    timings = QwenAligner("default", CPU).align(request([han("你"), han("好"), word("world")]))
    assert [(t.start_s, t.end_s) for t in timings] == [
        pytest.approx((0.8, 1.2)),
        pytest.approx((1.2, 1.6)),
        pytest.approx((2.0, 2.8)),
    ]
    assert [t.score for t in timings] == pytest.approx([1.0, 1.0, 1.0])
    assert wrapper.texts == [
        "<|audio_start|><|audio_pad|><|audio_end|>"
        "你<timestamp><timestamp>好<timestamp><timestamp>world<timestamp><timestamp>"
    ]


def test_probability_spread_over_neighbouring_classes_gives_sub_class_times(install: Any) -> None:
    # Start: 75 % on class 10 and 25 % on class 11 -> 10.25 classes = 0.82 s.
    install([{10: 0.75, 11: 0.25}, {20: 1.0}])
    (timing,) = QwenAligner("default", CPU).align(request([han("我")]))
    assert timing.start_s == pytest.approx(10.25 * 0.08)
    assert timing.score == pytest.approx(1.0)


def test_score_is_the_probability_mass_around_the_peak(install: Any) -> None:
    # 60 % at class 10, the rest far away (class 100): the model is unsure.
    install([{10: 0.6, 100: 0.4}, {20: 1.0}])
    (timing,) = QwenAligner("default", CPU).align(request([han("我")]))
    assert timing.start_s == pytest.approx(0.8)
    assert timing.score == pytest.approx(0.6, abs=0.01)


def test_out_of_order_predictions_are_repaired_and_marked_as_doubtful(install: Any) -> None:
    # The second word's start (class 3) lies before the first word: it is interpolated
    # between its neighbours (classes 15 and 30) and its score is cut.
    install([{10: 1.0}, {15: 1.0}, {3: 1.0}, {30: 1.0}, {30: 1.0}, {40: 1.0}])
    timings = QwenAligner("default", CPU).align(request([han("一"), han("二"), han("三")]))
    starts = [timing.start_s for timing in timings]
    assert starts == sorted(starts)
    assert timings[1].start_s == pytest.approx((15 + 30) / 2 * 0.08)
    assert timings[1].score == pytest.approx(0.3)
    assert timings[0].score == pytest.approx(1.0) and timings[2].score == pytest.approx(1.0)


def test_context_units_are_sent_to_the_model_but_not_returned(install: Any) -> None:
    answers = [{index * 5: 1.0} for index in range(8)]  # four words, two slots each
    wrapper = install(answers)
    timings = QwenAligner("default", CPU).align(
        request([han("中"), han("間")], prefix_units=[han("前")], suffix_units=[word("after")])
    )
    assert "前<timestamp><timestamp>中" in wrapper.texts[0]
    assert wrapper.texts[0].endswith("after<timestamp><timestamp>")
    # 中 owns slots 2–3 (classes 10, 15) and 間 slots 4–5 (classes 20, 25).
    assert [(t.start_s, t.end_s) for t in timings] == [
        pytest.approx((0.8, 1.2)),
        pytest.approx((1.6, 2.0)),
    ]


def test_a_unit_of_several_words_spans_from_its_first_to_its_last_word(install: Any) -> None:
    # "K歌" is one unit for us but two words for the model.
    install([{10: 1.0}, {12: 1.0}, {12: 1.0}, {20: 1.0}])
    (timing,) = QwenAligner("default", CPU).align(request([word("K歌")]))
    assert (timing.start_s, timing.end_s) == pytest.approx((0.8, 1.6))


def test_unpronounceable_units_take_the_previous_end(install: Any) -> None:
    install([{10: 1.0}, {20: 1.0}])
    timings = QwenAligner("default", CPU).align(request([han("啊"), word("…")]))
    assert (timings[1].start_s, timings[1].end_s, timings[1].score) == pytest.approx(
        (1.6, 1.6, 0.0)
    )


def test_times_are_clipped_to_the_window(install: Any) -> None:
    install([{10: 1.0}, {150: 1.0}])  # an end at 12 s in a 4 s window
    (timing,) = QwenAligner("default", CPU).align(request([han("長")], seconds=4.0))
    assert timing.end_s == pytest.approx(4.0)


def test_degenerate_requests_fall_back_to_an_even_spread(install: Any) -> None:
    wrapper = install([])
    aligner = QwenAligner("default", CPU)
    assert aligner.align(request([])) == []
    # Too short to hold anything, and a line of pure punctuation: no model call at all.
    short = aligner.align(request([han("一"), han("二")], seconds=0.2))
    assert [(t.start_s, t.end_s, t.score) for t in short] == [
        pytest.approx((0.0, 0.1, 0.0)),
        pytest.approx((0.1, 0.2, 0.0)),
    ]
    silent = aligner.align(request([word("…"), word("!")], seconds=2.0))
    assert [t.score for t in silent] == [0.0, 0.0]
    assert wrapper.texts == []


def test_a_slot_count_mismatch_falls_back_instead_of_guessing(install: Any) -> None:
    wrapper = install([{10: 1.0}, {20: 1.0}])
    wrapper.timestamp_token_id = 99  # the processor now produces no recognisable slots
    timings = QwenAligner("default", CPU).align(request([han("一"), han("二")], seconds=2.0))
    assert [t.score for t in timings] == [0.0, 0.0]


def test_missing_package_gives_install_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    pool.release_all()
    # ``None`` in ``sys.modules`` makes any import of the name fail, installed or not.
    monkeypatch.setitem(sys.modules, "qwen_asr", None)
    with pytest.raises(DependencyMissingError) as info:
        QwenAligner("default", CPU).align(request([han("一")]))
    assert "--extra qwen" in (info.value.hint_en or "")
    assert qwen.MODEL_ID == "qwen3-forced-aligner"
