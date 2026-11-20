"""Multi-resolution waveform peaks for fast drawing in the editor.

``peaks.json`` holds, for several zoom levels, the minimum and maximum sample value of each
bucket of the (mono) signal, quantised to signed 8-bit.  The editor picks the level whose
bucket size is closest to one screen pixel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from karaforge.audio.io import FloatArray

PEAKS_VERSION = 1
DEFAULT_BUCKET_SIZES: tuple[int, ...] = (256, 1024, 4096, 16384)
"""Samples per bucket for each level (at 48 kHz: 5 ms, 21 ms, 85 ms, 341 ms)."""


def compute_peaks(
    mono: FloatArray, sample_rate: int, bucket_sizes: tuple[int, ...] = DEFAULT_BUCKET_SIZES
) -> dict[str, Any]:
    """Compute min/max peaks at several resolutions.

    Args:
        mono: Mono signal.
        sample_rate: Sample rate of ``mono``.
        bucket_sizes: Samples per bucket, one entry per level, ascending.

    Returns:
        A JSON-serialisable mapping with ``sample_rate``, ``length`` and ``levels``; each
        level has ``samples_per_bucket``, ``min`` and ``max`` (lists of integers in -127..127).
    """
    levels: list[dict[str, Any]] = []
    for size in bucket_sizes:
        count = int(np.ceil(mono.size / size)) if mono.size else 0
        padded = np.zeros(count * size, dtype=np.float32)
        padded[: mono.size] = mono
        buckets = padded.reshape(count, size) if count else padded.reshape(0, size)
        low = np.clip(np.rint(buckets.min(axis=1) * 127.0), -127, 127).astype(np.int16)
        high = np.clip(np.rint(buckets.max(axis=1) * 127.0), -127, 127).astype(np.int16)
        levels.append({"samples_per_bucket": size, "min": low.tolist(), "max": high.tolist()})
    return {
        "version": PEAKS_VERSION,
        "sample_rate": sample_rate,
        "length": int(mono.size),
        "levels": levels,
    }


def write_peaks(path: Path, mono: FloatArray, sample_rate: int) -> None:
    """Compute peaks for ``mono`` and write them as compact JSON."""
    payload = compute_peaks(mono, sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
