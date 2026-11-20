"""The Qwen adapter's two pure helpers: sub-class peak position and order repair."""

from __future__ import annotations

from itertools import pairwise

import hypothesis.strategies as st
import numpy as np
import numpy.typing as npt
import pytest
from hypothesis import given

from karaforge.adapters.aligners.qwen import expected_bin, repair_order

F64 = npt.NDArray[np.float64]


def array(values: list[float]) -> F64:
    return np.array(values, dtype=np.float64)


# ---------------------------------------------------------------------------
# expected_bin


def test_expected_bin_one_hot_returns_peak_index_with_full_mass() -> None:
    # peak = 2, window = indices 0..4; mass = 1.0; position = (1.0 * 2) / 1.0 = 2.0.
    assert expected_bin(array([0.0, 0.0, 1.0, 0.0, 0.0])) == (2.0, 1.0)


def test_expected_bin_split_between_neighbours_returns_midpoint() -> None:
    # argmax picks the first of the tied peaks (5); the window covers both halves,
    # so position = (0.5 * 5 + 0.5 * 6) / (0.5 + 0.5) = 5.5 and mass = 1.0.
    assert expected_bin(array([0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.0])) == (5.5, 1.0)


def test_expected_bin_ignores_mass_far_from_peak() -> None:
    # peak = 5 (0.5), window = indices 3..8. The 0.3 at index 0 sits 5 classes away
    # and is excluded: mass = 0.2 + 0.5 + 0.2 = 0.9, position = (0.2*4 + 0.5*5 + 0.2*6) / 0.9
    # = 4.5 / 0.9 = 5.0 (without the exclusion it would be 4.8 / 1.2 = 4.0).
    position, mass = expected_bin(array([0.3, 0.0, 0.0, 0.0, 0.2, 0.5, 0.2, 0.0, 0.0, 0.0]))
    assert position == pytest.approx(4.5 / 0.9)
    assert mass == pytest.approx(0.9)


def test_expected_bin_all_zero_returns_zero_position_and_mass() -> None:
    # mass = 0.0 <= 0.0 short-circuits to (float(argmax), 0.0); argmax of all-zero is 0.
    assert expected_bin(array([0.0, 0.0, 0.0, 0.0, 0.0])) == (0.0, 0.0)


def test_expected_bin_peak_at_first_index_is_not_clamped_from_below() -> None:
    # peak = 0, low = max(0, -2) = 0, high = 0 + 3 = 3; window = [1.0, 0.0, 0.0]
    # gives position (1.0 * 0) / 1.0 = 0.0 and mass 1.0.
    assert expected_bin(array([1.0, 0.0, 0.0, 0.0])) == (0.0, 1.0)


def test_expected_bin_peak_at_last_index_is_not_clamped_from_above() -> None:
    # peak = 3, low = 1, high = min(4, 6) = 4; window = [0.0, 0.0, 1.0] over arange(1, 4)
    # gives position (1.0 * 3) / 1.0 = 3.0 and mass 1.0.
    assert expected_bin(array([0.0, 0.0, 0.0, 1.0])) == (3.0, 1.0)


def test_expected_bin_clamps_mass_above_one() -> None:
    # Not a distribution: window = [0.5, 0.4, 0.3] sums to 1.2, clamped to 1.0;
    # position = (0.4 * 1 + 0.3 * 2) / 1.2 = 1.0 / 1.2.
    position, mass = expected_bin(array([0.5, 0.4, 0.3]))
    assert position == pytest.approx(1.0 / 1.2)
    assert mass == 1.0


# ---------------------------------------------------------------------------
# repair_order


def test_repair_order_non_decreasing_input_is_returned_unchanged() -> None:
    times = [1.0, 2.0, 2.0, 3.0]
    result, flags = repair_order(times)
    assert result == [1.0, 2.0, 2.0, 3.0]
    assert flags == [False, False, False, False]
    # The whole input is on the longest non-decreasing subsequence, so nothing is replaced
    # and the input list itself is left untouched.
    assert times == [1.0, 2.0, 2.0, 3.0]


def test_repair_order_single_middle_outlier_is_interpolated() -> None:
    # Trusted = the 10/20/30 subsequence; the outlier at index 2 is filled with
    # 20 + (30 - 20) * ((2 - 2 + 1) / (3 - 2 + 1)) = 20 + 10 * 0.5 = 25.0.
    result, flags = repair_order([10.0, 20.0, 5.0, 30.0])
    assert result == [10.0, 20.0, 25.0, 30.0]
    assert flags == [False, False, True, False]


def test_repair_order_leading_outlier_takes_next_trusted_value() -> None:
    # Trusted = [10, 20] (indices 1, 2); index 0 has no left neighbour, so it takes
    # the next trusted value 10.0.
    result, flags = repair_order([50.0, 10.0, 20.0])
    assert result == [10.0, 10.0, 20.0]
    assert flags == [True, False, False]


def test_repair_order_trailing_outlier_takes_previous_trusted_value() -> None:
    # Trusted = [10, 20] (indices 0, 1); index 2 has no right neighbour, so it takes
    # the previous trusted value 20.0.
    result, flags = repair_order([10.0, 20.0, 5.0])
    assert result == [10.0, 20.0, 20.0]
    assert flags == [False, False, True]


def test_repair_order_run_between_trusted_values_is_interpolated() -> None:
    # Trusted = 10/100/200 (indices 0, 1, 4). The untrusted run at indices 2..3 is filled
    # with left=100, right=200 at shares (2-2+1)/(4-2+1)=1/3 and (3-2+1)/(4-2+1)=2/3.
    result, flags = repair_order([10.0, 100.0, 1.0, 2.0, 200.0])
    assert result[0] == 10.0
    assert result[1] == 100.0
    assert result[2] == pytest.approx(100.0 + 100.0 * (1 / 3))
    assert result[3] == pytest.approx(100.0 + 100.0 * (2 / 3))
    assert result[4] == 200.0
    assert flags == [False, False, True, True, False]


def test_repair_order_empty_input_returns_empty_lists() -> None:
    assert repair_order([]) == ([], [])


@given(st.lists(st.floats(0, 100), max_size=30))
def test_repair_order_property_result_is_sorted_with_same_length(values: list[float]) -> None:
    result, flags = repair_order(values)
    assert len(result) == len(values)
    assert len(flags) == len(values)
    # Values on the trusted (longest non-decreasing) subsequence keep their original value.
    kept = zip(result, values, flags, strict=True)
    assert all(value == original for value, original, replaced in kept if not replaced)
    # Small tolerance: the interpolation arithmetic may round to one ulp past a neighbour.
    assert all(earlier <= later + 1e-9 for earlier, later in pairwise(result))
