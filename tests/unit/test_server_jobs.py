"""The job manager and the event bus, without any web server."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from karaforge.errors import ExportError, JobCancelledError
from karaforge.pipeline.runner import StageEvent
from karaforge.server.events import EventBus
from karaforge.server.jobs import Job, JobManager

Progress = Callable[[float, str], None]
OnStage = Callable[[StageEvent], None]


class Recorder(EventBus):
    """An event bus that also keeps everything that was published."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        super().publish(event)

    def states(self, job_id: str) -> list[str]:
        return [e["job"]["state"] for e in self.events if e["job"]["id"] == job_id]


def wait_for(job: Job, *states: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while job.state not in states:
        assert time.monotonic() < deadline, f"job stayed {job.state}"
        time.sleep(0.01)


def test_a_job_runs_and_reports_its_result() -> None:
    bus = Recorder()

    def runner(job: Job, progress: Progress, on_stage: OnStage) -> dict[str, Any]:
        on_stage(StageEvent("separate", "started"))
        progress(0.5, "halfway")
        return {"answer": job.params["x"] * 2}

    manager = JobManager(bus, runner)
    job = manager.submit("process", "song", {"x": 21})
    wait_for(job, "done")
    assert job.result == {"answer": 42}
    assert (job.progress, job.stage, job.message) == (1.0, "separate", "halfway")
    assert job.started_at is not None and job.finished_at is not None
    assert bus.states(job.id)[0] == "queued" and bus.states(job.id)[-1] == "done"
    assert "running" in bus.states(job.id)
    assert manager.get(job.id) is job and manager.get("nope") is None
    assert manager.active_for("song") is None and manager.last_for("song") is job
    exported = job.to_dict()
    assert exported["state"] == "done" and "cancel" not in exported
    manager.shutdown()


def test_engine_errors_become_bilingual_failures_and_crashes_are_reported() -> None:
    def runner(job: Job, _progress: Progress, _on_stage: OnStage) -> dict[str, Any]:
        if job.params.get("crash"):
            raise RuntimeError("boom")
        raise ExportError("匯出失敗", "Export failed", hint_zh="再試一次", hint_en="Try again")

    manager = JobManager(Recorder(), runner)
    failed = manager.submit("export", "song", {})
    wait_for(failed, "failed")
    assert failed.error is not None
    assert failed.error["message_zh"] == "匯出失敗" and failed.error["hint_en"] == "Try again"
    assert failed.error["code"] == "export_error"
    crashed = manager.submit("export", "song", {"crash": True})
    wait_for(crashed, "failed")
    assert crashed.error is not None and crashed.error["code"] == "internal_error"
    assert "boom" in (crashed.error["detail"] or "")
    manager.shutdown()


def test_jobs_run_one_at_a_time_and_can_be_cancelled_while_waiting_or_running() -> None:
    release = threading.Event()
    running: list[str] = []

    def runner(job: Job, _progress: Progress, _on_stage: OnStage) -> dict[str, Any]:
        running.append(job.id)
        while not release.is_set():
            if job.cancel.wait(0.01):
                raise JobCancelledError
        return {}

    manager = JobManager(Recorder(), runner)
    first = manager.submit("process", "a", {})
    second = manager.submit("process", "b", {})
    third = manager.submit("process", "b", {})
    wait_for(first, "running")
    assert (second.state, third.state) == ("queued", "queued")
    assert manager.active_for("b") is second
    # A waiting job is cancelled immediately and never starts.
    assert manager.cancel(second.id) is second
    assert second.state == "cancelled" and second.finished_at is not None
    # A running job stops at its next cancellation check.
    manager.cancel(first.id)
    wait_for(first, "cancelled")
    wait_for(third, "running")
    release.set()
    wait_for(third, "done")
    assert running == [first.id, third.id]
    assert manager.cancel("nope") is None
    assert [job.id for job in manager.list()] == [first.id, second.id, third.id]
    manager.shutdown()


def test_progress_events_are_throttled_but_the_final_state_is_always_sent() -> None:
    bus = Recorder()

    def runner(_job: Job, progress: Progress, _on_stage: OnStage) -> dict[str, Any]:
        for step in range(1000):
            progress(step / 1000, "")
        return {}

    manager = JobManager(bus, runner)
    job = manager.submit("process", "song", {})
    wait_for(job, "done")
    assert len(bus.events) < 50
    assert bus.events[-1]["job"]["state"] == "done" and bus.events[-1]["job"]["progress"] == 1.0
    manager.shutdown()


def test_shutdown_cancels_what_is_still_running() -> None:
    def runner(job: Job, _progress: Progress, _on_stage: OnStage) -> dict[str, Any]:
        job.cancel.wait(30)
        job.cancel.raise_if_cancelled()
        return {}

    manager = JobManager(Recorder(), runner)
    job = manager.submit("process", "song", {})
    wait_for(job, "running")
    manager.shutdown()
    assert job.state == "cancelled"


def test_events_published_from_a_thread_reach_async_subscribers() -> None:
    bus = EventBus()

    async def scenario() -> list[dict[str, Any]]:
        received: list[dict[str, Any]] = []
        stream = bus.subscribe()

        async def consume() -> None:
            async for event in stream:
                received.append(event)
                if len(received) == 3:
                    return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        assert bus.subscriber_count == 1
        thread = threading.Thread(target=lambda: [bus.publish({"n": n}) for n in range(3)])
        thread.start()
        await asyncio.wait_for(task, 2)
        thread.join()
        await stream.aclose()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        return received

    assert asyncio.run(scenario()) == [{"n": 0}, {"n": 1}, {"n": 2}]
    assert bus.subscriber_count == 0
    bus.publish({"n": 99})  # nobody listening: nothing happens


def test_a_slow_subscriber_loses_the_oldest_events_instead_of_blocking() -> None:
    bus = EventBus()

    async def scenario() -> list[int]:
        stream = bus.subscribe()
        first = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0.01)  # the subscription is registered now
        for number in range(400):
            bus.publish({"n": number})
        await asyncio.sleep(0.05)  # all 400 are delivered before the subscriber reads any
        seen = [(await first)["n"]]
        seen += [(await anext(stream))["n"] for _ in range(10)]
        await stream.aclose()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        return seen

    # The queue holds 256 events: the 144 oldest were dropped, the rest arrive in order.
    assert asyncio.run(scenario()) == list(range(144, 155))


@pytest.mark.parametrize("fraction", [-1.0, 0.25, 7.0])
def test_progress_is_clamped(fraction: float) -> None:
    def runner(_job: Job, progress: Progress, _on_stage: OnStage) -> dict[str, Any]:
        progress(fraction, "x")
        raise JobCancelledError

    manager = JobManager(Recorder(), runner)
    job = manager.submit("process", None, {})
    wait_for(job, "cancelled")
    assert job.progress == min(1.0, max(0.0, fraction))
    manager.shutdown()
