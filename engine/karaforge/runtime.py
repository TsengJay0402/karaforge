"""Small runtime primitives shared by stages, adapters and tools: progress and cancellation."""

from __future__ import annotations

import threading
from collections.abc import Callable

from karaforge.errors import JobCancelledError

ProgressFn = Callable[[float, str], None]
"""Callback ``(fraction, message)`` where ``fraction`` is in ``[0, 1]``."""


def null_progress(fraction: float, message: str = "") -> None:
    """Progress callback that ignores every report."""


def subprogress(parent: ProgressFn, start: float, end: float) -> ProgressFn:
    """Map a child's ``[0, 1]`` progress onto ``[start, end]`` of ``parent``.

    Args:
        parent: Callback that receives the mapped progress.
        start: Parent fraction that corresponds to the child's 0.
        end: Parent fraction that corresponds to the child's 1.

    Returns:
        A callback suitable for handing to a sub-task.
    """
    span = end - start

    def report(fraction: float, message: str = "") -> None:
        clamped = min(1.0, max(0.0, fraction))
        parent(start + span * clamped, message)

    return report


class CancelToken:
    """Cooperative cancellation flag that long-running code polls.

    Stages call :meth:`raise_if_cancelled` at safe points; tools that spawn subprocesses
    terminate them when :attr:`cancelled` becomes true.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation.  Safe to call from any thread, any number of times."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise :class:`~karaforge.errors.JobCancelledError` if cancellation was requested."""
        if self._event.is_set():
            raise JobCancelledError

    def wait(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` seconds; return ``True`` as soon as cancellation is requested."""
        return self._event.wait(timeout)
