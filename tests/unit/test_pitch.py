"""Unit tests of the pYIN pitch track and the per-token note assignment."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from karaforge.audio.pitch import estimate_f0, load_f0, note_of, save_f0, token_pitches
from karaforge.project import Line, Token
from support import song_project, timed_line


def constant_f0(hz: float, frames: int, unvoiced: slice | None = None) -> npt.NDArray[np.float32]:
    """A pitch track of ``frames`` frames at a constant ``hz``, NaN inside ``unvoiced``."""
    f0 = np.full(frames, hz, dtype=np.float32)
    if unvoiced is not None:
        f0[unvoiced] = np.nan
    return f0


# ------------------------------------------------------------------------------------ note_of


def test_note_of_returns_the_midi_note_of_the_median_voiced_frame() -> None:
    assert note_of(constant_f0(440.0, 10), 0.0, 0.2) == 69  # 69 + 12*log2(440/440) = 69
    # 69 + 12*log2(261.63/440) = 69 - 8.9947 = 60.005 -> 60
    assert note_of(constant_f0(261.63, 10), 0.0, 0.2) == 60
    assert note_of(constant_f0(220.0, 10), 0.0, 0.2) == 57  # 69 - 12
    # A single 440 Hz frame among many does not move the median: 5 x 220 Hz vs 3 x 440 Hz.
    f0 = np.full(8, 220.0, dtype=np.float32)
    f0[2:5] = 440.0
    assert note_of(f0, 0.0, 0.16) == 57


def test_note_of_needs_two_voiced_frames_and_ignores_nan() -> None:
    assert note_of(np.full(10, np.nan, dtype=np.float32), 0.0, 0.2) is None
    # One voiced frame is not enough even though the span covers five frames.
    f0 = np.full(10, np.nan, dtype=np.float32)
    f0[3] = 440.0
    assert note_of(f0, 0.0, 0.1) is None
    # Exactly two voiced frames, separated by NaN, are enough.
    f0[3] = np.nan
    f0[4] = f0[6] = 330.0  # 69 + 12*log2(330/440) = 69 - 4.98 = 64.02 -> 64
    assert note_of(f0, 0.0, 0.2) == 64


def test_note_of_clips_a_span_past_the_end_of_the_track() -> None:
    # 10 frames of 220 Hz; the span runs from frame 8 to well past the end, so frames 8..9.
    f0 = constant_f0(220.0, 10)
    assert note_of(f0, 0.16, 1.0) == 57
    # A span that starts at the very end clips to an empty slice: no voiced frame.
    assert note_of(f0, 0.2, 0.4) is None


# ------------------------------------------------------------------------------ token_pitches


def test_token_pitches_carries_and_backfills_notes_within_a_line() -> None:
    line = timed_line("L001", "你好嗎嘿喔", 0, 400)
    assert len(line.tokens) == 5
    # 200 frames = 4 s: token spans are frames 0-20, 20-40, 40-60, 60-80, 80-100.
    f0 = constant_f0(440.0, 200)
    f0[0:20] = np.nan  # token 0 unvoiced, later backfilled from token 1
    f0[40:60] = np.nan  # token 2 unvoiced, takes the previous token's note
    f0[60:100] = 220.0  # tokens 3 and 4
    pitches = token_pitches(song_project([line]), f0)
    assert pitches == {
        ("L001", 0): 69,
        ("L001", 1): 69,
        ("L001", 2): 69,
        ("L001", 3): 57,
        ("L001", 4): 57,
    }


def test_token_pitches_skips_untimed_tokens_and_unvoiced_lines() -> None:
    unvoiced = timed_line("L001", "啦啦", 3_000, 400)  # frames 150-190, all NaN below
    assert token_pitches(song_project([unvoiced]), np.full(200, np.nan, dtype=np.float32)) == {}

    partial = Line(
        id="L002",
        tokens=[
            Token(text="啦", start_ms=5_000, end_ms=5_400),  # frames 250-270 of a 6 s track
            Token(text="啦"),
            Token(text="啦", start_ms=5_800, end_ms=6_200),
        ],
    )
    # In this track the first line (frames 150-190) is voiced, the tail of the second is not.
    f0 = constant_f0(440.0, 300, unvoiced=slice(270, 300))
    pitches = token_pitches(song_project([unvoiced, partial]), f0)
    # L002: token 1 has no time and is skipped; token 2 (frames 290-310) has no voiced frame
    # and takes the note of token 0.
    assert pitches == {
        ("L001", 0): 69,
        ("L001", 1): 69,
        ("L002", 0): 69,
        ("L002", 2): 69,
    }
    assert ("L002", 1) not in pitches


# --------------------------------------------------------------------------------- save / load


def test_save_and_load_f0_round_trip_preserves_nan(tmp_path: Path) -> None:
    f0 = constant_f0(220.0, 25, unvoiced=slice(5, 10))
    target = tmp_path / "f0.npz"
    save_f0(target, f0)
    loaded = load_f0(target)
    assert loaded.dtype == np.float32
    assert np.array_equal(loaded, f0, equal_nan=True)


# -------------------------------------------------------------------------------- estimate_f0


def test_estimate_f0_tracks_a_220hz_sine() -> None:
    rate = 16_000
    t = np.arange(rate, dtype=np.float64) / rate
    samples = (0.5 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
    f0 = estimate_f0(samples, rate)
    # 1 s at HOP_S = 0.02 -> 1 + 16000 // 320 = 51 frames.
    assert 45 <= f0.size <= 55
    voiced = f0[np.isfinite(f0)]
    assert voiced.size > 0
    assert abs(float(np.median(voiced)) - 220.0) < 2.0


def test_estimate_f0_on_a_short_input_is_all_nan() -> None:
    samples = np.ones(500, dtype=np.float32)  # 500 < the 1024-sample frame length
    f0 = estimate_f0(samples, 16_000)
    # round(500 / 16000 / 0.02) = round(1.5625) = 2 frames.
    assert f0.size == 2
    assert np.all(np.isnan(f0))


def test_estimate_f0_silence_is_unvoiced() -> None:
    f0 = estimate_f0(np.zeros(16_000, dtype=np.float32), 16_000)
    assert f0.size > 0
    assert not np.isfinite(f0).any()


@pytest.mark.parametrize("hz", [220.0, 440.0])
def test_estimate_f0_matches_the_input_frequency(hz: float) -> None:
    rate = 16_000
    t = np.arange(rate, dtype=np.float64) / rate
    samples = (0.5 * np.sin(2.0 * np.pi * hz * t)).astype(np.float32)
    f0 = estimate_f0(samples, rate)
    voiced = f0[np.isfinite(f0)]
    assert voiced.size > 0
    assert abs(float(np.median(voiced)) - hz) < 2.0
