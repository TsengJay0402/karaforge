"""Background jobs: one worker thread runs them one at a time.

Processing a song keeps every core busy, so running two jobs at once would only make both
slower.  Jobs are therefore queued; each can be cancelled while it waits or while it runs
(the engine checks the cancellation token between and inside stages).

Downloading a video from a link mostly waits for the network, so those jobs have a queue and
a worker of their own: a download does not wait for another song to finish processing.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from karaforge.errors import JobCancelledError, KaraForgeError
from karaforge.pipeline.runner import StageEvent
from karaforge.runtime import CancelToken
from karaforge.server.events import EventBus

JobState = Literal["queued", "running", "done", "failed", "cancelled"]
JobKind = Literal["process", "align", "export", "models", "import"]
FINISHED: tuple[JobState, ...] = ("done", "failed", "cancelled")
_LANES: dict[str, str] = {"import": "network"}
"""Kinds of job that run beside the others, one at a time among themselves."""
_PROGRESS_INTERVAL_S = 0.15
_KEEP_FINISHED = 100
log = logging.getLogger("karaforge.server.jobs")


@dataclass
class Job:
    """One unit of background work and its current state."""

    id: str
    kind: JobKind
    project_id: str | None
    params: dict[str, Any]
    state: JobState = "queued"
    progress: float = 0.0
    stage: str | None = None
    message: str = ""
    error: dict[str, str | None] | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel: CancelToken = field(default_factory=CancelToken, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """The job as sent to the browser."""
        return {
            "id": self.id,
            "kind": self.kind,
            "project_id": self.project_id,
            "params": self.params,
            "state": self.state,
            "progress": round(self.progress, 4),
            "stage": self.stage,
            "message": self.message,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


JobRunner = Callable[
    [Job, Callable[[float, str], None], Callable[[StageEvent], None]], dict[str, Any]
]
"""Does the work of a job: ``(job, progress, on_stage_event) -> result``."""


class JobManager:
    """Queue, run, cancel and remember jobs.

    Args:
        bus: Where state changes are announced (``{"type": "job", "job": {...}}``).
        runner: Executes a job; see :data:`JobRunner`.
    """

    def __init__(self, bus: EventBus, runner: JobRunner) -> None:
        self._bus = bus
        self._runner = runner
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._queues: dict[str, queue.Queue[str | None]] = {}
        self._workers: list[threading.Thread] = []
        for lane in ("main", *sorted(set(_LANES.values()))):
            waiting: queue.Queue[str | None] = queue.Queue()
            worker = threading.Thread(
                target=self._work, args=(waiting,), name=f"kf-jobs-{lane}", daemon=True
            )
            self._queues[lane] = waiting
            self._workers.append(worker)
            worker.start()

    # ------------------------------------------------------------------ public API

    def submit(self, kind: JobKind, project_id: str | None, params: dict[str, Any]) -> Job:
        """Queue a job and return it."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, project_id=project_id, params=params)
        with self._lock:
            self._jobs[job.id] = job
            self._forget_old()
        self._announce(job)
        self._queues[_LANES.get(kind, "main")].put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        """Look a job up by id."""
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """All remembered jobs, oldest first."""
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at)

    def active_for(self, project_id: str) -> Job | None:
        """The queued or running job of a project, if any (the oldest one)."""
        return next(
            (
                job
                for job in self.list()
                if job.project_id == project_id and job.state not in FINISHED
            ),
            None,
        )

    def last_for(self, project_id: str) -> Job | None:
        """The most recent job of a project, finished or not."""
        jobs = [job for job in self.list() if job.project_id == project_id]
        return jobs[-1] if jobs else None

    def cancel(self, job_id: str) -> Job | None:
        """Ask a job to stop.  A queued job is cancelled at once; a running one stops soon."""
        job = self.get(job_id)
        if job is None:
            return None
        job.cancel.cancel()
        with self._lock:
            waiting = job.state == "queued"
            if waiting:
                job.state = "cancelled"
                job.finished_at = time.time()
        if waiting:
            self._announce(job)
        return job

    def shutdown(self) -> None:
        """Cancel everything and stop the worker threads."""
        for job in self.list():
            if job.state not in FINISHED:
                job.cancel.cancel()
        for waiting in self._queues.values():
            waiting.put(None)
        for worker in self._workers:
            worker.join(timeout=10)

    # --------------------------------------------------------------------- internals

    def _forget_old(self) -> None:
        finished = [job for job in self._jobs.values() if job.state in FINISHED]
        finished.sort(key=lambda job: job.finished_at or 0.0)
        for job in finished[: max(0, len(finished) - _KEEP_FINISHED)]:
            del self._jobs[job.id]

    def _announce(self, job: Job) -> None:
        self._bus.publish({"type": "job", "job": job.to_dict()})

    def _work(self, waiting: queue.Queue[str | None]) -> None:
        while True:
            job_id = waiting.get()
            if job_id is None:
                return
            job = self.get(job_id)
            if job is None or job.state != "queued":
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        job.state = "running"
        job.started_at = time.time()
        self._announce(job)
        last_sent = 0.0

        def on_progress(fraction: float, message: str) -> None:
            nonlocal last_sent
            job.progress = min(1.0, max(0.0, fraction))
            if message:
                job.message = message
            now = time.monotonic()
            if now - last_sent >= _PROGRESS_INTERVAL_S:
                last_sent = now
                self._announce(job)

        def on_stage(event: StageEvent) -> None:
            if event.status == "started":
                job.stage = event.stage
                self._announce(job)

        try:
            job.result = self._runner(job, on_progress, on_stage)
            job.state = "done"
            job.progress = 1.0
        except JobCancelledError:
            job.state = "cancelled"
        except KaraForgeError as error:
            job.state = "cancelled" if job.cancel.cancelled else "failed"
            job.error = error.to_dict()
        except Exception as error:
            log.exception("job %s (%s) crashed", job.id, job.kind)
            job.state = "failed"
            job.error = {
                "code": "internal_error",
                "message_zh": "發生沒有預期到的錯誤。",
                "message_en": "An unexpected error occurred.",
                "hint_zh": "請把下面的錯誤內容回報給開發者。",
                "hint_en": "Please report the detail below to the developers.",
                "detail": "".join(traceback.format_exception_only(type(error), error)).strip(),
            }
        finally:
            job.finished_at = time.time()
            self._announce(job)
