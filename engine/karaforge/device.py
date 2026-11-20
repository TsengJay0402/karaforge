"""Choosing the compute device (CUDA, Apple MPS or CPU) and the number of CPU threads."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

DeviceKind = Literal["cpu", "cuda", "mps"]
DevicePreference = Literal["auto", "cpu", "cuda", "mps"]

ENV_THREADS = "KARAFORGE_THREADS"
ENV_DEVICE = "KARAFORGE_DEVICE"
_MAX_DEFAULT_THREADS = 8


@dataclass(frozen=True)
class DeviceChoice:
    """Result of resolving a device preference."""

    kind: DeviceKind
    name: str
    """Human-readable description, e.g. the GPU model."""
    fallback_reason_zh: str | None = None
    fallback_reason_en: str | None = None
    """Set when the requested device was not available and the CPU is used instead."""


@lru_cache(maxsize=1)
def _probe() -> tuple[bool, str, bool]:
    """Return ``(cuda_available, cuda_name, mps_available)``; safe when torch is missing."""
    try:
        import torch
    except ImportError:
        return False, "", False
    cuda = bool(torch.cuda.is_available())
    name = str(torch.cuda.get_device_name(0)) if cuda else ""
    mps_backend = getattr(torch.backends, "mps", None)
    mps = bool(mps_backend is not None and mps_backend.is_available())
    return cuda, name, mps


def resolve_device(preference: DevicePreference = "auto") -> DeviceChoice:
    """Pick the device to run models on.

    ``auto`` prefers CUDA, then MPS, then the CPU.  An explicit ``cuda`` or ``mps`` request
    that cannot be satisfied falls back to the CPU and explains why, so callers can tell the
    user instead of failing.  The ``KARAFORGE_DEVICE`` environment variable overrides
    ``auto``.
    """
    if preference == "auto":
        override = os.environ.get(ENV_DEVICE, "").strip().lower()
        if override == "cpu":
            preference = "cpu"
        elif override == "cuda":
            preference = "cuda"
        elif override == "mps":
            preference = "mps"
    cuda, cuda_name, mps = _probe()
    if preference == "cpu":
        return DeviceChoice("cpu", "CPU")
    if preference in ("auto", "cuda") and cuda:
        return DeviceChoice("cuda", cuda_name or "CUDA")
    if preference in ("auto", "mps") and mps:
        return DeviceChoice("mps", "Apple MPS")
    if preference == "cuda":
        return DeviceChoice(
            "cpu",
            "CPU",
            "找不到可用的 CUDA 裝置(或安裝的是 CPU 版 PyTorch),改用 CPU。",
            "No usable CUDA device (or a CPU-only PyTorch build is installed); using the CPU.",
        )
    if preference == "mps":
        return DeviceChoice(
            "cpu",
            "CPU",
            "這台機器無法使用 Apple MPS,改用 CPU。",
            "Apple MPS is not available on this machine; using the CPU.",
        )
    return DeviceChoice("cpu", "CPU")


def cpu_threads() -> int:
    """Number of CPU threads models may use.

    ``KARAFORGE_THREADS`` wins; otherwise the number of cores, capped at eight so that a
    shared machine is not saturated.
    """
    raw = os.environ.get(ENV_THREADS, "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    available = os.cpu_count() or 1
    return max(1, min(_MAX_DEFAULT_THREADS, available))
