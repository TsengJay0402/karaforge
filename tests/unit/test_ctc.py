from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from karaforge.align.ctc import (
    CtcSpan,
    forced_align,
    log_softmax,
    min_frames,
    pooled_column,
    wildcard_column,
)

BLANK = 0


def emissions(
    frames: list[int | None], columns: int = 5, peak: float = 0.9
) -> npt.NDArray[np.float32]:
    """Posteriors in which frame ``i`` strongly favours ``frames[i]`` (``None`` = blank)."""
    rest = (1.0 - peak) / (columns - 1)
    matrix = np.full((len(frames), columns), rest, dtype=np.float64)
    for index, symbol in enumerate(frames):
        matrix[index, BLANK if symbol is None else symbol] = peak
    return np.log(matrix).astype(np.float32)


def spans(result: list[CtcSpan] | None) -> list[tuple[int, int]]:
    assert result is not None
    return [(span.start_frame, span.end_frame) for span in result]


def test_symbols_land_on_their_spikes() -> None:
    lattice = emissions([None, None, 1, None, None, 2, 2, None, 3, None])
    result = forced_align(lattice, [1, 2, 3])
    assert spans(result) == [(2, 3), (5, 7), (8, 9)]
    assert result is not None
    assert all(span.score == pytest.approx(0.9, abs=1e-5) for span in result)


def test_repeated_symbol_needs_a_blank_between() -> None:
    lattice = emissions([1, 1, None, 1, 1, None])
    assert spans(forced_align(lattice, [1, 1])) == [(0, 2), (3, 5)]
    # Without any blank-looking frame the algorithm still has to insert one.
    solid = emissions([1, 1, 1, 1, 1])
    first, second = spans(forced_align(solid, [1, 1]))
    assert first[1] < second[0]


def test_different_neighbours_may_touch() -> None:
    lattice = emissions([1, 1, 2, 2])
    assert spans(forced_align(lattice, [1, 2])) == [(0, 2), (2, 4)]


def test_alignment_is_forced_even_against_the_evidence() -> None:
    # The model "hears" 3 everywhere; the text says 1 then 2.
    lattice = emissions([3, 3, 3, 3, 3, 3])
    result = forced_align(lattice, [1, 2])
    assert result is not None
    assert result[0].start_frame < result[1].start_frame
    assert all(span.score < 0.1 for span in result)


def test_sequence_that_does_not_fit_returns_none() -> None:
    assert forced_align(emissions([1, 2]), [1, 2, 3]) is None
    assert forced_align(emissions([1, 1]), [1, 1]) is None  # needs a blank in between
    assert forced_align(emissions([1, None, 1]), [1, 1]) is not None
    assert min_frames([1, 1, 2, 2, 2]) == 5 + 3
    assert min_frames([]) == 0


def test_empty_target_and_single_frame() -> None:
    assert forced_align(emissions([None, None]), []) == []
    assert spans(forced_align(emissions([1]), [1])) == [(0, 1)]


def test_spans_are_ordered_and_disjoint_on_random_input() -> None:
    rng = np.random.default_rng(7)
    for _ in range(50):
        frames = int(rng.integers(8, 60))
        columns = int(rng.integers(3, 9))
        lattice = log_softmax(rng.normal(size=(frames, columns)).astype(np.float32) * 3)
        count = int(rng.integers(1, 6))
        targets = [int(value) for value in rng.integers(1, columns, size=count)]
        result = forced_align(lattice, targets)
        if result is None:
            assert frames < min_frames(targets)
            continue
        previous_end = 0
        for index, span in enumerate(result):
            assert previous_end <= span.start_frame < span.end_frame <= frames
            if index and targets[index] == targets[index - 1]:
                assert span.start_frame > previous_end
            previous_end = span.end_frame


def test_viterbi_finds_the_best_scoring_path() -> None:
    """Compare with brute force over every valid segmentation of a tiny lattice."""
    rng = np.random.default_rng(11)
    lattice = log_softmax(rng.normal(size=(7, 4)).astype(np.float32) * 2)
    targets = [1, 2, 1]

    def score(labels: list[int]) -> float:
        return float(sum(lattice[frame, label] for frame, label in enumerate(labels)))

    def collapse(labels: list[int]) -> list[int]:
        merged = [
            label for index, label in enumerate(labels) if index == 0 or label != labels[index - 1]
        ]
        return [label for label in merged if label != BLANK]

    best = -np.inf
    labels = [0] * 7
    for code in range(4**7):
        value = code
        for position in range(7):
            labels[position] = value % 4
            value //= 4
        if collapse(labels) == targets:
            best = max(best, score(labels))

    result = forced_align(lattice, targets)
    assert result is not None
    path = [BLANK] * 7
    for span, symbol in zip(result, targets, strict=True):
        for frame in range(span.start_frame, span.end_frame):
            path[frame] = symbol
    assert collapse(path) == targets
    assert score(path) == pytest.approx(best, abs=1e-4)


def test_wildcard_soaks_up_foreign_speech_before_the_text() -> None:
    # Frames 0-3 hold another line's symbol (4); the text (1, 2) starts at frame 6.
    base = emissions([4, 4, 4, 4, None, None, 1, 1, 2, 2], columns=5)
    star = wildcard_column(base[:, BLANK])
    lattice = np.concatenate([base, star[:, np.newaxis]], axis=1)
    star_index = 5
    without = forced_align(base, [1, 2])
    with_star = forced_align(lattice, [star_index, 1, 2])
    assert without is not None and with_star is not None
    assert spans(with_star)[1:] == [(6, 8), (8, 10)]
    assert spans(with_star)[0] == (0, 4)
    # Without the wildcard the first symbol is free to sit anywhere, here at its own spike
    # too; the wildcard matters when the foreign sound resembles the text (see next test).
    assert spans(without)[0][1] <= 8


def test_wildcard_does_not_steal_frames_from_the_text() -> None:
    base = emissions([1, 1, 1, None, 2, 2], columns=4)
    lattice = np.concatenate([base, wildcard_column(base[:, BLANK])[:, np.newaxis]], axis=1)
    result = forced_align(lattice, [4, 1, 2, 4])
    assert result is not None
    # The leading and trailing wildcards get the minimum; the text keeps its own frames.
    assert (result[1].start_frame, result[1].end_frame) in {(0, 3), (1, 3)}
    assert result[2].end_frame - result[2].start_frame >= 1


def test_pooled_column_adds_probabilities() -> None:
    probabilities = np.array([[0.1, 0.2, 0.3, 0.4], [0.7, 0.1, 0.1, 0.1]], dtype=np.float64)
    lattice = np.log(probabilities).astype(np.float32)
    pooled = pooled_column(lattice, [1, 3])
    assert np.exp(pooled) == pytest.approx([0.6, 0.2], abs=1e-6)
    assert pooled_column(lattice, [2]) is not None
    assert np.exp(pooled_column(lattice, [2])) == pytest.approx([0.3, 0.1], abs=1e-6)


def test_log_softmax_rows_sum_to_one() -> None:
    rng = np.random.default_rng(3)
    lattice = log_softmax(rng.normal(size=(5, 6)).astype(np.float32) * 10)
    assert np.exp(lattice.astype(np.float64)).sum(axis=1) == pytest.approx(np.ones(5), abs=1e-5)
    assert wildcard_column(lattice[:, BLANK]).shape == (5,)
