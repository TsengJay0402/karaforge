"""Process-wide cache of loaded models so that each one is loaded only once."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar, cast

_T = TypeVar("_T")

_lock = threading.RLock()
_instances: dict[tuple[str, ...], Any] = {}


def shared(key: tuple[str, ...], factory: Callable[[], _T]) -> _T:
    """Return the object cached under ``key``, creating it with ``factory`` on first use.

    Args:
        key: Identifies the loaded model, e.g. ``("faster-whisper", "whisper-small", "cpu")``.
        factory: Loads the model.  Called at most once per key.
    """
    with _lock:
        if key not in _instances:
            _instances[key] = factory()
        return cast(_T, _instances[key])


def release_all() -> None:
    """Drop every cached model (frees memory; they are reloaded on next use)."""
    with _lock:
        _instances.clear()


def loaded_keys() -> list[tuple[str, ...]]:
    """Keys of the models currently held in memory."""
    with _lock:
        return list(_instances)
