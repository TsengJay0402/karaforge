from __future__ import annotations

import pytest

from karaforge import device
from karaforge.device import cpu_threads, resolve_device


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KARAFORGE_DEVICE", raising=False)
    monkeypatch.delenv("KARAFORGE_THREADS", raising=False)


def stub_probe(monkeypatch: pytest.MonkeyPatch, cuda: bool, mps: bool) -> None:
    name = "NVIDIA GeForce Fake GPU" if cuda else ""
    monkeypatch.setattr(device, "_probe", lambda: (cuda, name, mps))


def test_auto_prefers_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_probe(monkeypatch, cuda=True, mps=False)
    choice = resolve_device("auto")
    assert choice.kind == "cuda"
    assert choice.name == "NVIDIA GeForce Fake GPU"
    assert choice.fallback_reason_zh is None
    assert choice.fallback_reason_en is None


def test_auto_uses_mps_without_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_probe(monkeypatch, cuda=False, mps=True)
    choice = resolve_device("auto")
    assert choice.kind == "mps"
    assert choice.name == "Apple MPS"


def test_auto_falls_back_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_probe(monkeypatch, cuda=False, mps=False)
    choice = resolve_device("auto")
    assert choice.kind == "cpu"
    assert choice.name == "CPU"
    assert choice.fallback_reason_zh is None
    assert choice.fallback_reason_en is None


def test_explicit_cuda_without_gpu_falls_back_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_probe(monkeypatch, cuda=False, mps=False)
    choice = resolve_device("cuda")
    assert choice.kind == "cpu"
    assert choice.fallback_reason_zh is not None
    assert choice.fallback_reason_en is not None


def test_explicit_mps_without_backend_falls_back_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_probe(monkeypatch, cuda=False, mps=False)
    choice = resolve_device("mps")
    assert choice.kind == "cpu"
    assert choice.fallback_reason_zh is not None
    assert choice.fallback_reason_en is not None


def test_explicit_cpu_always_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_probe(monkeypatch, cuda=True, mps=True)
    choice = resolve_device("cpu")
    assert choice.kind == "cpu"
    assert choice.name == "CPU"
    assert choice.fallback_reason_zh is None


def test_env_device_cpu_overrides_auto_even_with_cuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_probe(monkeypatch, cuda=True, mps=False)
    monkeypatch.setenv("KARAFORGE_DEVICE", "cpu")
    choice = resolve_device("auto")
    assert choice.kind == "cpu"
    assert choice.fallback_reason_zh is None


def test_env_device_does_not_affect_explicit_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_probe(monkeypatch, cuda=True, mps=False)
    monkeypatch.setenv("KARAFORGE_DEVICE", "cpu")
    choice = resolve_device("cuda")
    assert choice.kind == "cuda"


def test_cpu_threads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARAFORGE_THREADS", "3")
    assert cpu_threads() == 3


def test_cpu_threads_invalid_environment_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for raw in ("not a number", "0", "0.5", ""):
        monkeypatch.setenv("KARAFORGE_THREADS", raw)
        assert 1 <= cpu_threads() <= 8
    monkeypatch.delenv("KARAFORGE_THREADS")
    assert 1 <= cpu_threads() <= 8
