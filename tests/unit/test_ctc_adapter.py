"""The CTC aligner adapter, driven by stand-ins for the wav2vec2 models.

The real models are hundreds of megabytes; these tests replace them with objects that return
hand-made frame probabilities, and check the adapter's own logic: homophone pooling, the
two-model lattice for mixed-language lines, wildcards, lag correction and evidence scores.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import numpy.typing as npt
import pytest

from karaforge.adapters import pool
from karaforge.adapters.aligners import ctc as adapter
from karaforge.adapters.aligners.ctc import CtcAligner
from karaforge.adapters.base import AlignRequest, AlignUnit
from karaforge.align.ctc import forced_align
from karaforge.device import DeviceChoice
from karaforge.text.tokenize import TokenKind

F32 = npt.NDArray[np.float32]
CPU = DeviceChoice(kind="cpu", name="test cpu")
FRAME = 0.02
ZH_LAG = 0.03
EN_LAG = 0.10
BLANK, BAR = 0, 1

# Chinese model: 星 and 行 are both read "xing".
ZH_CHARS = {"星": 2, "行": 3, "空": 4, "好": 5, "山": 6}
ZH_VOCAB = adapter._Vocabulary(  # pyright: ignore[reportPrivateUsage]
    blank=BLANK,
    silent=(BAR,),
    letters={},
    characters=ZH_CHARS,
    syllables={"xing": (2, 3), "kong": (4,), "hao": (5,), "shan": (6,)},
)
LETTERS = {letter: index + 2 for index, letter in enumerate("abcdefghijklmnopqrstuvwxyz'")}
EN_VOCAB = adapter._Vocabulary(  # pyright: ignore[reportPrivateUsage]
    blank=BLANK, silent=(BAR,), letters=LETTERS, characters={}, syllables={}
)


def lattice(frames: int, columns: int, spikes: dict[int, dict[int, float]]) -> F32:
    """Log-probabilities that are blank everywhere except at the given frames."""
    matrix = np.full((frames, columns), 1e-4, dtype=np.float64)
    matrix[:, BLANK] = 1.0
    for frame, values in spikes.items():
        matrix[frame, BLANK] = 1e-4
        for column, probability in values.items():
            matrix[frame, column] = probability
    matrix /= matrix.sum(axis=1, keepdims=True)
    return np.log(matrix).astype(np.float32)


class FakeModel:
    """Returns a fixed matrix, cut to the length of the audio it is asked about."""

    def __init__(self, vocabulary: object, matrix: F32) -> None:
        self.vocabulary = vocabulary
        self.matrix = matrix
        self.window_calls = 0
        self.song_calls = 0

    def log_probs(self, samples: npt.NDArray[np.float32]) -> F32:
        self.window_calls += 1
        return self.matrix[: max(0, (samples.size - 400) // 320 + 1)]

    def song_log_probs(self, key: str, samples: npt.NDArray[np.float32]) -> F32:
        self.song_calls += 1
        assert key
        return self.matrix[: max(0, (samples.size - 400) // 320 + 1)]


@pytest.fixture
def models() -> Iterator[dict[str, FakeModel]]:
    """Empty registry of fake models; tests fill it through :func:`install`."""
    pool.release_all()
    yield {}
    pool.release_all()


def install(models: dict[str, FakeModel], model_id: str, vocabulary: object, matrix: F32) -> None:
    fake = FakeModel(vocabulary, matrix)
    models[model_id] = fake
    pool.shared(("wav2vec2-ctc", model_id, "cpu"), lambda: fake)


def han(text: str, reading: str) -> AlignUnit:
    return AlignUnit(text=text, kind=TokenKind.HAN, reading=reading)


def word(text: str) -> AlignUnit:
    return AlignUnit(text=text, kind=TokenKind.WORD, reading=text.lower())


def audio(frames: int) -> npt.NDArray[np.float32]:
    return np.zeros(400 + 320 * (frames - 1), dtype=np.float32)


def test_info_lists_both_default_models_and_only_permissive_licences() -> None:
    info = CtcAligner("default", CPU).info
    assert info.models == ("wav2vec2-zh", "wav2vec2-en")
    assert info.license == "Apache-2.0"
    assert info.supports_language("zh-TW") and info.supports_language("en")
    single = CtcAligner("mms-fa", CPU).info
    assert single.models == ("mms-fa",) and "NC" in single.license


def test_a_syllable_is_found_through_any_of_its_homophones(models: dict[str, FakeModel]) -> None:
    # The model "hears" 行 where 星 is sung: same syllable, different character.
    install(models, "wav2vec2-zh", ZH_VOCAB, lattice(60, 7, {10: {3: 0.9}, 30: {4: 0.9}}))
    request = AlignRequest(
        audio=audio(60),
        units=[han("星", "xing"), han("空", "kong")],
        language="zh-TW",
        open_start=False,
        open_end=False,
    )
    first, second = CtcAligner("default", CPU).align(request)
    assert first.start_s == pytest.approx(10 * FRAME - ZH_LAG)
    assert second.start_s == pytest.approx(30 * FRAME - ZH_LAG)
    assert first.score > 0.8 and second.score > 0.8
    assert "wav2vec2-en" not in models  # a Chinese line never loads the English model


def test_a_mixed_line_uses_each_model_for_its_own_language(models: dict[str, FakeModel]) -> None:
    # 星 at frame 10 (Chinese model), "so" at frames 30-31 and "soft" at 50-53 (English model).
    install(models, "wav2vec2-zh", ZH_VOCAB, lattice(80, 7, {10: {2: 0.9}}))
    english = {
        30: {LETTERS["s"]: 0.9},
        31: {LETTERS["o"]: 0.9},
        50: {LETTERS["s"]: 0.9},
        51: {LETTERS["o"]: 0.9},
        52: {LETTERS["f"]: 0.9},
        53: {LETTERS["t"]: 0.9},
    }
    install(models, "wav2vec2-en", EN_VOCAB, lattice(80, 29, english))
    request = AlignRequest(
        audio=audio(80),
        units=[han("星", "xing"), word("so"), word("soft")],
        language="zh-TW",
        open_start=False,
        open_end=False,
    )
    star, so, soft = CtcAligner("default", CPU).align(request)
    assert star.start_s == pytest.approx(10 * FRAME - ZH_LAG)
    assert so.start_s == pytest.approx(30 * FRAME - EN_LAG)
    assert soft.start_s == pytest.approx(50 * FRAME - EN_LAG)
    assert soft.end_s == pytest.approx(54 * FRAME - EN_LAG)
    assert min(star.score, so.score, soft.score) > 0.8


def test_the_word_delimiter_counts_as_silence(models: dict[str, FakeModel]) -> None:
    # A strong "|" at frame 20 must not attract a token, nor make the gap expensive.
    matrix = lattice(60, 7, {10: {2: 0.9}, 20: {BAR: 0.99}, 40: {5: 0.9}})
    install(models, "wav2vec2-zh", ZH_VOCAB, matrix)
    request = AlignRequest(
        audio=audio(60),
        units=[han("星", "xing"), han("好", "hao")],
        language="zh",
        open_start=False,
        open_end=False,
    )
    first, second = CtcAligner("default", CPU).align(request)
    assert first.start_s == pytest.approx(10 * FRAME - ZH_LAG)
    assert second.start_s == pytest.approx(40 * FRAME - ZH_LAG)


def test_foreign_sound_is_absorbed_only_when_the_window_is_open(
    models: dict[str, FakeModel],
) -> None:
    # Frames 5-7 hold the tail of the previous line, which happens to end on the syllable
    # this line starts with (好); the line's own 好 is sung at frame 30, a little less
    # clearly.  A window that is "open" at the start lets a wildcard take the earlier sound.
    matrix = lattice(60, 7, {5: {5: 0.9}, 6: {5: 0.9}, 7: {5: 0.9}, 30: {5: 0.6}, 45: {4: 0.9}})
    install(models, "wav2vec2-zh", ZH_VOCAB, matrix)
    units = [han("好", "hao"), han("空", "kong")]
    aligner = CtcAligner("default", CPU)
    opened = aligner.align(
        AlignRequest(audio=audio(60), units=units, language="zh", open_start=True, open_end=False)
    )
    assert opened[0].start_s == pytest.approx(30 * FRAME - ZH_LAG)
    assert opened[1].start_s == pytest.approx(45 * FRAME - ZH_LAG)
    # Told that the window starts in silence, the aligner has no reason to skip the first,
    # clearer 好 — which is why the fine pass only closes a window when it really is silent.
    closed = aligner.align(
        AlignRequest(audio=audio(60), units=units, language="zh", open_start=False, open_end=False)
    )
    assert closed[0].start_s == pytest.approx(5 * FRAME - ZH_LAG)
    assert closed[1].start_s == pytest.approx(45 * FRAME - ZH_LAG)


def test_a_token_the_model_did_not_hear_gets_a_low_score(models: dict[str, FakeModel]) -> None:
    # 星 and 好 have clear spikes; nothing at all is heard for 空 between them.
    install(models, "wav2vec2-zh", ZH_VOCAB, lattice(60, 7, {10: {2: 0.9}, 40: {5: 0.9}}))
    request = AlignRequest(
        audio=audio(60),
        units=[han("星", "xing"), han("空", "kong"), han("好", "hao")],
        language="zh",
        open_start=False,
        open_end=False,
    )
    star, sky, good = CtcAligner("default", CPU).align(request)
    assert star.score > 0.8 and good.score > 0.8
    assert sky.score < 0.05
    assert star.start_s <= sky.start_s <= good.start_s


def test_a_misheard_syllable_still_counts_as_heard(models: dict[str, FakeModel]) -> None:
    # The model hears 山 where 好 is sung: wrong character, but clearly a syllable.
    install(models, "wav2vec2-zh", ZH_VOCAB, lattice(60, 7, {10: {2: 0.9}, 40: {6: 0.9}}))
    request = AlignRequest(
        audio=audio(60),
        units=[han("星", "xing"), han("好", "hao")],
        language="zh",
        open_start=False,
        open_end=False,
    )
    _star, good = CtcAligner("default", CPU).align(request)
    assert good.start_s == pytest.approx(40 * FRAME - ZH_LAG)
    assert good.score > 0.8


def test_units_the_model_cannot_spell_share_a_wildcard(models: dict[str, FakeModel]) -> None:
    # "…" has no letters; the English model can only say that *something* sounds at frame 20.
    install(models, "wav2vec2-en", EN_VOCAB, lattice(60, 29, {20: {LETTERS["x"]: 0.9}}))
    request = AlignRequest(
        audio=audio(60),
        units=[
            AlignUnit(text="…", kind=TokenKind.WORD, reading=""),
            AlignUnit(text="♪", kind=TokenKind.WORD, reading=""),
        ],
        language="en",
        open_start=False,
        open_end=False,
    )
    first, second = CtcAligner("default", CPU).align(request)
    assert first.start_s == pytest.approx(20 * FRAME - EN_LAG)
    assert (second.start_s, second.end_s) == (first.end_s, first.end_s)
    assert second.score == 0.0


def test_prepared_song_is_computed_once_and_sliced_per_window(
    models: dict[str, FakeModel],
) -> None:
    install(models, "wav2vec2-zh", ZH_VOCAB, lattice(200, 7, {110: {2: 0.9}, 130: {4: 0.9}}))
    song = audio(200)
    aligner = CtcAligner("default", CPU)
    aligner.prepare(song)
    # A window that starts 2 s (100 frames) into the song.
    offset = 100 * 320
    request = AlignRequest(
        audio=song[offset : offset + 400 + 320 * 59],
        units=[han("星", "xing"), han("空", "kong")],
        language="zh",
        open_start=False,
        open_end=False,
        offset_s=offset / 16000,
    )
    first, second = aligner.align(request)
    # Times are relative to the window: frame 110 of the song is frame 10 of the window.
    assert first.start_s == pytest.approx(10 * FRAME - ZH_LAG)
    assert second.start_s == pytest.approx(30 * FRAME - ZH_LAG)
    aligner.align(request)
    fake = models["wav2vec2-zh"]
    assert fake.window_calls == 0 and fake.song_calls == 2  # the model itself caches by key
    # A request that is not a slice of the prepared song falls back to the window itself.
    aligner.align(
        AlignRequest(audio=audio(60), units=[han("星", "xing")], language="zh", offset_s=None)
    )
    assert fake.window_calls == 1


def test_degenerate_requests(models: dict[str, FakeModel]) -> None:
    install(models, "wav2vec2-zh", ZH_VOCAB, lattice(60, 7, {}))
    aligner = CtcAligner("default", CPU)
    assert aligner.align(AlignRequest(audio=audio(60), units=[], language="zh")) == []
    # Too little audio for a single frame: an even spread with zero confidence.
    tiny = aligner.align(
        AlignRequest(
            audio=np.zeros(100, dtype=np.float32),
            units=[han("星", "xing"), han("空", "kong")],
            language="zh",
        )
    )
    assert [timing.score for timing in tiny] == [0.0, 0.0]
    # More symbols than frames: no alignment exists.
    crowded = aligner.align(
        AlignRequest(
            audio=audio(2),
            units=[han("星", "xing"), han("星", "xing"), han("星", "xing")],
            language="zh",
            open_start=False,
            open_end=False,
        )
    )
    assert [timing.score for timing in crowded] == [0.0, 0.0, 0.0]


def test_forced_align_with_a_blank_column_per_gap() -> None:
    # Two "models": columns 0/1 are their blanks, 2 and 3 their symbols.  Symbol 2 fires at
    # frame 2 and symbol 3 at frame 6; model A is silent after frame 3, model B before it.
    probabilities = np.full((9, 4), 0.01)
    probabilities[:, 0] = 0.98
    probabilities[:, 1] = 0.98
    probabilities[2] = [0.01, 0.98, 0.97, 0.01]
    probabilities[6] = [0.98, 0.01, 0.01, 0.97]
    emissions = np.log(probabilities).astype(np.float32)
    spans = forced_align(emissions, [2, 3], blank=[0, 0, 1])
    assert spans is not None
    assert [(span.start_frame, span.end_frame) for span in spans] == [(2, 3), (6, 7)]
    with pytest.raises(ValueError, match="one blank column"):
        forced_align(emissions, [2, 3], blank=[0, 1])
