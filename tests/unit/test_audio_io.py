from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from karaforge.audio.io import (
    FloatArray,
    audio_duration_ms,
    read_mono,
    read_wav,
    resample,
    write_wav,
)
from karaforge.audio.peaks import compute_peaks, write_peaks
from karaforge.errors import MediaError


def sine(
    frequency: float, seconds: float, rate: int, amplitude: float = 0.5
) -> npt.NDArray[np.float32]:
    samples = int(rate * seconds)
    t = np.arange(samples, dtype=np.float64) / rate
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def dominant_frequency(audio: FloatArray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(audio.astype(np.float64)))
    bins = np.fft.rfftfreq(len(audio), d=1.0 / rate)
    return float(bins[int(np.argmax(spectrum[1:])) + 1])  # skip the DC bin


def test_write_wav_then_read_wav_round_trip(tmp_path: Path) -> None:
    stereo = np.stack([sine(440.0, 0.05, 48000), sine(880.0, 0.05, 48000)], axis=1).astype(
        np.float32
    )
    path = tmp_path / "tone.wav"
    write_wav(path, stereo, 48000)
    audio, rate = read_wav(path)
    assert rate == 48000
    assert audio.ndim == 2
    assert audio.shape == stereo.shape
    assert audio.dtype == np.float32
    assert np.allclose(audio, stereo, atol=2**-15)


def test_write_wav_clips_out_of_range_values(tmp_path: Path) -> None:
    loud: npt.NDArray[np.float32] = np.array([[-5.0, -1.5, 0.0, 1.5, 5.0]], dtype=np.float32).T
    path = tmp_path / "loud.wav"
    write_wav(path, loud, 8000)
    audio, _ = read_wav(path)
    assert audio.shape == (5, 1)
    assert float(audio.min()) >= -1.0
    assert float(audio.max()) <= 1.0
    assert audio[0, 0] == pytest.approx(-1.0, abs=2**-15)
    assert audio[4, 0] == pytest.approx(1.0, abs=2**-15)


def test_read_wav_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(MediaError):
        read_wav(tmp_path / "missing.wav")


def test_resample_changes_length_proportionally() -> None:
    audio = sine(440.0, 0.5, 48000)
    down = resample(audio, 48000, 16000)
    assert down.shape[0] == pytest.approx(audio.shape[0] / 3, rel=0.01)
    up = resample(down, 16000, 48000)
    assert up.shape[0] == pytest.approx(audio.shape[0], rel=0.01)


def test_resample_same_rate_returns_original_array() -> None:
    audio = sine(440.0, 0.1, 16000)
    result = resample(audio, 16000, 16000)
    assert result is audio


def test_resample_preserves_dominant_frequency() -> None:
    audio = sine(1000.0, 0.5, 48000)
    down = resample(audio, 48000, 16000)
    assert dominant_frequency(down, 16000) == pytest.approx(1000.0, abs=20.0)


def test_resample_two_dimensional_along_first_axis_keeps_channels() -> None:
    left = sine(440.0, 0.2, 48000)
    right = sine(880.0, 0.2, 48000)
    stereo = np.stack([left, right], axis=1)
    down = resample(stereo, 48000, 16000)
    assert down.ndim == 2
    assert down.shape[1] == 2
    assert down.shape[0] == pytest.approx(stereo.shape[0] / 3, rel=0.01)
    # Each channel keeps its own frequency.
    assert dominant_frequency(np.ascontiguousarray(down[:, 0]), 16000) == pytest.approx(
        440.0, abs=20.0
    )
    assert dominant_frequency(np.ascontiguousarray(down[:, 1]), 16000) == pytest.approx(
        880.0, abs=20.0
    )


def test_read_mono_mixes_stereo_and_resamples(tmp_path: Path) -> None:
    stereo = np.stack([sine(440.0, 0.3, 48000), sine(440.0, 0.3, 48000)], axis=1).astype(np.float32)
    path = tmp_path / "stereo.wav"
    write_wav(path, stereo, 48000)
    mono = read_mono(path, 16000)
    assert mono.ndim == 1
    assert mono.shape[0] == pytest.approx(16000 * 0.3, rel=0.01)


def test_audio_duration_ms(tmp_path: Path) -> None:
    audio = sine(440.0, 1.5, 48000)
    path = tmp_path / "tone.wav"
    write_wav(path, audio, 48000)
    assert audio_duration_ms(path) == pytest.approx(1500, abs=10)


def test_compute_peaks_structure_and_levels() -> None:
    rate = 48000
    audio = sine(220.0, 0.3, rate, amplitude=0.9)
    peaks = compute_peaks(audio, rate)
    assert peaks["version"] == 1
    assert peaks["sample_rate"] == rate
    assert peaks["length"] == audio.size
    assert len(peaks["levels"]) == 4
    for level, size in zip(peaks["levels"], (256, 1024, 4096, 16384), strict=True):
        assert level["samples_per_bucket"] == size
        expected = math.ceil(audio.size / size)
        assert len(level["min"]) == expected
        assert len(level["max"]) == expected
        for low, high in zip(level["min"], level["max"], strict=True):
            assert -127 <= low <= 127
            assert -127 <= high <= 127
            assert low <= high


def test_compute_peaks_of_silence_is_all_zero() -> None:
    audio: FloatArray = np.zeros(48000, dtype=np.float32)
    peaks = compute_peaks(audio, 48000)
    for level in peaks["levels"]:
        assert level["min"] == [0] * len(level["min"])
        assert level["max"] == [0] * len(level["max"])


def test_compute_peaks_of_empty_signal_has_empty_levels() -> None:
    audio: FloatArray = np.zeros(0, dtype=np.float32)
    peaks = compute_peaks(audio, 16000)
    assert peaks["length"] == 0
    for level in peaks["levels"]:
        assert level["min"] == []
        assert level["max"] == []


def test_compute_peaks_matches_amplitude() -> None:
    audio = sine(100.0, 0.1, 8000, amplitude=0.5)
    peaks = compute_peaks(audio, 8000, bucket_sizes=(8000,))
    assert len(peaks["levels"]) == 1
    level = peaks["levels"][0]
    assert level["max"][0] == pytest.approx(63, abs=2)  # 0.5 * 127
    assert level["min"][0] == pytest.approx(-63, abs=2)


def test_write_peaks_produces_readable_json(tmp_path: Path) -> None:
    audio = sine(330.0, 0.05, 16000)
    path = tmp_path / "peaks.json"
    write_peaks(path, audio, 16000)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == compute_peaks(audio, 16000)
