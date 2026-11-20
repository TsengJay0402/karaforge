"""Event fan-out from worker threads to the browsers listening on ``/api/events``."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Any

Event = dict[str, Any]
_QUEUE_SIZE = 256


class EventBus:
    """Publish from any thread; consume from asyncio.

    Every subscriber has its own bounded queue.  A subscriber that falls behind loses its
    oldest events rather than blocking the publisher (job progress is only ever interesting
    in its latest state).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Queue[Event]]] = {}
        self._next_id = 0

    def publish(self, event: Event) -> None:
        """Deliver ``event`` to every current subscriber.  Safe to call from any thread."""
        with self._lock:
            targets = list(self._subscribers.values())
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(_offer, queue, event)
            except RuntimeError:
                continue  # the subscriber's loop is gone; its generator will clean up

    @property
    def subscriber_count(self) -> int:
        """Number of open subscriptions."""
        with self._lock:
            return len(self._subscribers)

    async def subscribe(self) -> AsyncIterator[Event]:
        """Yield events as they are published, until the consumer stops iterating."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        loop = asyncio.get_running_loop()
        with self._lock:
            token = self._next_id
            self._next_id += 1
            self._subscribers[token] = (loop, queue)
        try:
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                self._subscribers.pop(token, None)


def _offer(queue: asyncio.Queue[Event], event: Event) -> None:
    """Put ``event`` into ``queue``, dropping the oldest entry when it is full."""
    while True:
        try:
            queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
