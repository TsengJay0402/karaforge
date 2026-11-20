from __future__ import annotations

import random
from itertools import pairwise

import pytest

from karaforge.align.coarse import LineWindow
from karaforge.align.confidence import coarse_agreement, onset_agreement, score_tokens
from karaforge.align.fine import TokenTiming
from karaforge.align.refine import RefinedToken, RefineSettings, refine
from support import make_features

ALWAYS_SINGING = [(0.0, 60.0)]


def timing(start: float, end: float | None = None, **changes: object) -> TokenTiming:
    token = TokenTiming(start_s=start, end_s=end if end is not None else start + 0.2, score=0.8)
    for name, value in changes.items():
        setattr(token, name, value)
    return token


def starts(lines: list[list[RefinedToken]]) -> list[float]:
    return [round(token.start_s, 3) for line in lines for token in line]


def test_start_in_silence_moves_to_where_the_voice_comes_in() -> None:
    features = make_features(20.0, [(5.0, 8.0)])
    result = refine([[timing(3.9), timing(5.6), timing(6.2)]], features, RefineSettings(), 20.0)
    first = result[0][0]
    assert first.start_s == pytest.approx(5.0, abs=0.011)
    assert first.left_silence is True
    assert first.raw_start_s == 3.9
    assert result[0][1].left_silence is False


def test_start_in_silence_stays_when_no_voice_follows_before_the_next_token() -> None:
    features = make_features(20.0, [(8.0, 9.0)])
    result = refine([[timing(3.0), timing(4.0)], [timing(8.2)]], features, RefineSettings(), 20.0)
    assert result[0][0].start_s == pytest.approx(3.0)
    assert result[0][0].left_silence is False


def test_onset_snapping_respects_the_limit() -> None:
    features = make_features(20.0, ALWAYS_SINGING, onsets=[5.03, 6.2, 7.0])
    lines = [[timing(5.0), timing(6.0), timing(7.05)]]
    snapped = refine(lines, features, RefineSettings(onset_snap_ms=60), 20.0)
    assert starts(snapped) == [5.03, 6.0, 7.0]
    assert [token.snapped for token in snapped[0]] == [True, False, True]
    assert snapped[0][1].onset_distance_s == pytest.approx(0.2)

    wide = refine(lines, features, RefineSettings(onset_snap_ms=250), 20.0)
    assert starts(wide) == [5.03, 6.2, 7.0]

    off = refine(lines, features, RefineSettings(onset_snap=False), 20.0)
    assert starts(off) == [5.0, 6.0, 7.05]
    assert not any(token.snapped for token in off[0])


def test_two_tokens_never_share_one_onset() -> None:
    features = make_features(20.0, ALWAYS_SINGING, onsets=[5.0])
    result = refine([[timing(4.97), timing(5.03)]], features, RefineSettings(), 20.0)
    first, second = result[0]
    assert first.start_s == pytest.approx(5.0)
    assert first.snapped
    assert not second.snapped
    assert second.start_s >= first.start_s + 0.06 - 1e-9


def test_starts_become_strictly_increasing_with_the_minimum_gap() -> None:
    features = make_features(20.0, ALWAYS_SINGING)
    lines = [[timing(5.0), timing(5.0), timing(4.9)], [timing(5.01), timing(9.0)]]
    result = refine(lines, features, RefineSettings(min_token_ms=80, onset_snap=False), 20.0)
    values = starts(result)
    assert values == pytest.approx([5.0, 5.08, 5.16, 5.24, 9.0])
    assert all(later - earlier >= 0.08 - 1e-9 for earlier, later in pairwise(values))


def test_locked_tokens_are_never_moved_even_when_neighbours_collide() -> None:
    features = make_features(20.0, ALWAYS_SINGING, onsets=[5.02, 5.31])
    locked = timing(5.3, 5.5, locked=True, score=1.0)
    lines = [[timing(5.0), timing(5.45), locked, timing(5.31)]]
    result = refine(lines, features, RefineSettings(), 20.0)
    assert (result[0][2].start_s, result[0][2].end_s) == (5.3, 5.5)
    assert result[0][2].locked
    values = starts(result)
    assert values == sorted(values)
    assert values[1] <= 5.3
    assert values[3] >= 5.3 + 0.06 - 1e-9


def test_locked_tokens_survive_random_inputs_unchanged() -> None:
    rng = random.Random(20261120)
    features = make_features(
        60.0, [(2.0, 20.0), (25.0, 50.0)], onsets=[rng.uniform(2.0, 50.0) for _ in range(120)]
    )
    for _ in range(200):
        lines: list[list[TokenTiming]] = []
        cursor = rng.uniform(1.0, 5.0)
        expected: list[tuple[float, float]] = []
        for _line in range(rng.randint(1, 5)):
            line: list[TokenTiming] = []
            for _token in range(rng.randint(1, 8)):
                cursor += rng.uniform(0.05, 1.5)
                jitter = rng.uniform(-0.8, 0.8)
                is_locked = rng.random() < 0.3
                start = cursor if is_locked else max(0.0, cursor + jitter)
                token = timing(start, start + rng.uniform(0.05, 0.6), locked=is_locked)
                if is_locked:
                    expected.append((token.start_s, token.end_s))
                line.append(token)
            lines.append(line)
        result = refine(lines, features, RefineSettings(), 60.0)
        actual = [(token.start_s, token.end_s) for line in result for token in line if token.locked]
        assert actual == expected
        for refined_line in result:
            for refined_token in refined_line:
                in_range = 0.0 <= refined_token.start_s <= refined_token.end_s <= 60.0
                assert in_range or refined_token.locked


def test_a_token_ends_where_the_next_one_starts() -> None:
    features = make_features(20.0, ALWAYS_SINGING)
    result = refine(
        [[timing(5.0, 5.1), timing(5.5, 5.6), timing(6.0, 6.1)]],
        features,
        RefineSettings(onset_snap=False),
        20.0,
    )
    assert [round(token.end_s, 3) for token in result[0][:2]] == [5.5, 6.0]


def test_a_pause_ends_the_token_at_the_energy_drop() -> None:
    features = make_features(20.0, [(5.0, 5.6), (6.4, 9.0)])
    lines = [[timing(5.0), timing(6.4), timing(7.0)]]
    result = refine(lines, features, RefineSettings(onset_snap=False, pause_threshold_ms=300), 20.0)
    assert result[0][0].end_s == pytest.approx(5.6, abs=0.011)
    assert result[0][1].end_s == pytest.approx(7.0)

    # A gap shorter than the threshold is not a pause: the token runs into the next one.
    patient = refine(
        lines, features, RefineSettings(onset_snap=False, pause_threshold_ms=900), 20.0
    )
    assert patient[0][0].end_s == pytest.approx(6.4)


def test_last_token_is_held_until_the_voice_fades() -> None:
    features = make_features(30.0, [(5.0, 9.3), (14.0, 16.0)])
    lines = [[timing(5.0), timing(6.0, 6.2)], [timing(14.0)]]
    result = refine(lines, features, RefineSettings(onset_snap=False), 30.0)
    assert result[0][1].end_s == pytest.approx(9.3, abs=0.011)

    capped = refine(lines, features, RefineSettings(onset_snap=False, max_tail_ms=1500), 30.0)
    assert capped[0][1].end_s == pytest.approx(7.5, abs=0.011)


def test_last_token_never_runs_into_the_next_line() -> None:
    features = make_features(30.0, [(5.0, 20.0)])
    lines = [[timing(5.0), timing(6.0)], [timing(8.0), timing(9.0)]]
    result = refine(lines, features, RefineSettings(onset_snap=False), 30.0)
    assert result[0][1].end_s == pytest.approx(8.0)


def test_without_long_note_handling_the_aligner_end_is_kept() -> None:
    features = make_features(30.0, [(5.0, 9.3)])
    lines = [[timing(5.0), timing(6.0, 6.25)]]
    result = refine(lines, features, RefineSettings(onset_snap=False, long_note=False), 30.0)
    assert result[0][1].end_s == pytest.approx(6.25)


def test_empty_features_do_not_break_refinement() -> None:
    features = make_features(0.0, [])
    result = refine([[timing(1.0, 1.4), timing(2.0, 2.3)]], features, RefineSettings(), 10.0)
    assert starts(result) == [1.0, 2.0]
    assert result[0][0].end_s == pytest.approx(2.0)
    assert result[0][0].onset_distance_s is None


# ------------------------------------------------------------------------------ confidence


def refined(start: float, **changes: object) -> RefinedToken:
    token = RefinedToken(
        start_s=start,
        end_s=start + 0.3,
        score=0.8,
        locked=False,
        estimated=False,
        raw_start_s=start,
    )
    for name, value in changes.items():
        setattr(token, name, value)
    return token


def test_confidence_orders_tokens_by_the_evidence_for_them() -> None:
    window = LineWindow(10.0, 14.0, 0.9, "asr", [10.0, 11.0, 12.0, None, None])
    line = [
        refined(10.0, onset_distance_s=0.0),  # everything agrees
        refined(11.5, onset_distance_s=0.0),  # far from where the recogniser heard it
        refined(12.0, onset_distance_s=0.3, score=0.2),  # weak aligner score, no onset
        refined(13.0, locked=True),
        refined(13.5, estimated=True),
    ]
    values = score_tokens([line], [window])[0]
    assert values[3] == 1.0
    assert values[4] == pytest.approx(0.1)
    assert values[0] > 0.85
    assert values[0] > values[1] > values[2]
    assert all(0.0 <= value <= 1.0 for value in values)


def test_lines_placed_without_a_transcript_score_lower() -> None:
    token = refined(10.0, onset_distance_s=0.0)
    heard = LineWindow(10.0, 12.0, 1.0, "asr", [10.0])
    guessed = LineWindow(10.0, 12.0, 0.0, "interpolated", [None])
    assert score_tokens([[token]], [heard])[0][0] > score_tokens([[token]], [guessed])[0][0] + 0.2


def test_agreement_helpers() -> None:
    window = LineWindow(0.0, 1.0, 0.5, "asr", [])
    near, far = refined(10.1), refined(12.0)
    assert coarse_agreement(near, 10.0, window) == pytest.approx(0.3 * 0.5 + 0.7)
    assert coarse_agreement(far, 10.0, window) < 0.2
    assert coarse_agreement(near, None, window) == pytest.approx(0.25)
    assert coarse_agreement(near, None, LineWindow(0, 1, 1.0, "anchor", [])) == pytest.approx(0.8)
    assert coarse_agreement(near, None, LineWindow(0, 1, 0.0, "regions", [])) == pytest.approx(0.15)
    assert onset_agreement(refined(1.0, onset_distance_s=0.005)) == pytest.approx(1.0)
    assert onset_agreement(refined(1.0, onset_distance_s=0.2)) < 0.05
    assert onset_agreement(refined(1.0)) == pytest.approx(0.3)
